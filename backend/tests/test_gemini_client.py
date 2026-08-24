from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from py_gasbuddy import APIError, CloudflareBlocked, LibraryError, MissingSearchData

from app.models.schemas import (
    ChatMessage,
    EvConnectorDetail,
    EvStation,
    FuelPrice,
    GasPriceForecast,
    GasStation,
)
from app.services import gemini_client
from app.services.afdc_client import AfdcError
from app.services.gemini_client import (
    EV_FILTERED_FETCH_LIMIT,
    EV_MAX_STATIONS_IN_RESPONSE,
    ChatError,
    ChatService,
)
from app.services.ev_search import EvStationSearchResult
from app.services.gasbuddy_client import GASBUDDY_PAGE_SIZE, StationSearchResult
from app.services.geocoding import GeocodingError


class _FakeGeminiResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=httpx.Request("POST", "https://example.test"),
                response=self,  # type: ignore[arg-type]
            )

    def json(self):
        return self._body


class FakeGasBuddyService:
    def __init__(self, stations=None, error=None, pages=None):
        # `pages`: {cursor_used_to_request: (stations, next_cursor)};
        # `None` key = page 1. `stations` is shorthand for a single page
        # with no follow-up (`{None: (stations, None)}`).
        self._pages = (
            dict(pages) if pages is not None else {None: (stations or [], None)}
        )
        self._error = error
        self.calls: list[dict] = []

    async def search_nearest_stations(
        self, *, query=None, lat=None, lon=None, limit=10, cursor=None
    ):
        self.calls.append(
            {"query": query, "lat": lat, "lon": lon, "limit": limit, "cursor": cursor}
        )
        if self._error:
            raise self._error
        if cursor not in self._pages:
            raise AssertionError(f"unexpected GasBuddy call with cursor={cursor!r}")
        stations, next_cursor = self._pages[cursor]
        return StationSearchResult(
            stations=stations, next_cursor=next_cursor, lat=lat or 0.0, lon=lon or 0.0
        )


def _make_station(
    name="Shell",
    price=158.9,
    distance_miles=0.5,
    brand=None,
    premium=None,
    regular_reported_minutes_ago=None,
    premium_reported_minutes_ago=None,
):
    return GasStation(
        station_id=name,
        name=name,
        brand=brand if brand is not None else name,
        address="1 Main St",
        distance_miles=distance_miles,
        regular=FuelPrice(
            price=price,
            formatted_price=f"{price}¢",
            last_updated=_iso_minutes_ago(regular_reported_minutes_ago),
        ),
        premium=(
            FuelPrice(
                price=premium,
                formatted_price=f"{premium}¢",
                last_updated=_iso_minutes_ago(premium_reported_minutes_ago),
            )
            if premium is not None
            else None
        ),
    )


def _iso_minutes_ago(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


class FakeEvSearchService:
    def __init__(self, stations=None, error=None):
        self._stations = stations or []
        self._error = error
        self.calls: list[dict] = []

    async def search_nearest_ev_stations(
        self, *, query=None, lat=None, lon=None, limit=20, radius_km=None
    ):
        self.calls.append(
            {
                "query": query,
                "lat": lat,
                "lon": lon,
                "limit": limit,
                "radius_km": radius_km,
            }
        )
        if self._error:
            raise self._error
        return EvStationSearchResult(
            stations=self._stations,
            total_results=len(self._stations),
            lat=lat or 0.0,
            lon=lon or 0.0,
        )


def _make_ev_station(
    name="ChargePoint",
    network="ChargePoint",
    distance_miles=0.5,
    connector_types=None,
    level1_count=None,
    level2_count=2,
    dc_fast_count=1,
    connector_details=None,
):
    return EvStation(
        station_id=name,
        name=name,
        network=network,
        address="1 Main St",
        distance_miles=distance_miles,
        level1_count=level1_count,
        level2_count=level2_count,
        dc_fast_count=dc_fast_count,
        connector_types=(
            connector_types if connector_types is not None else ["J1772", "J1772COMBO"]
        ),
        connector_details=connector_details or [],
    )


class FakeForecastService:
    def __init__(self, result=None, error=None):
        self._result = result or GasPriceForecast(lat=0.0, lon=0.0)
        self._error = error
        self.calls: list[dict] = []

    async def forecast(self, lat, lon):
        self.calls.append({"lat": lat, "lon": lon})
        if self._error:
            raise self._error
        return self._result


def _make_forecast(**overrides):
    defaults = dict(
        lat=0.0,
        lon=0.0,
        today_average_price=150.0,
        forecasted_price=152.0,
        today_average_formatted="150.0¢",
        forecasted_price_formatted="152.0¢",
        price_change=2.0,
        price_change_formatted="+2.0¢",
        trend_direction="up",
        daily_change_pct=0.0133,
        source="statcan",
        source_period_end="2026-07",
        stations_sampled=12,
        today_lowest_price=145.0,
        today_highest_price=160.0,
        today_lowest_formatted="145.0¢",
        today_highest_formatted="160.0¢",
        forecasted_lowest_price=146.9,
        forecasted_highest_price=162.1,
        forecasted_lowest_formatted="146.9¢",
        forecasted_highest_formatted="162.1¢",
        lowest_price_change=1.9,
        lowest_price_change_formatted="+1.9¢",
        highest_price_change=2.1,
        highest_price_change_formatted="+2.1¢",
    )
    defaults.update(overrides)
    return GasPriceForecast(**defaults)


def _text_response(text: str, status_code=200):
    return _FakeGeminiResponse(
        {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": text}]},
                    "finishReason": "STOP",
                }
            ]
        },
        status_code=status_code,
    )


def _function_call_response(name: str, args: dict):
    return _FakeGeminiResponse(
        {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"functionCall": {"name": name, "args": args}}],
                    },
                    "finishReason": "STOP",
                }
            ]
        }
    )


def _configured_service(gasbuddy=None, ev_search=None, forecast=None) -> ChatService:
    # Bypasses get_settings() (which reads the real environment) so these
    # tests can exercise a "configured" ChatService regardless of what's
    # actually in .env.
    service = ChatService(
        gasbuddy or FakeGasBuddyService(),
        ev_search or FakeEvSearchService(),
        forecast or FakeForecastService(),
    )
    service._api_key = "test-key"
    return service


@pytest.mark.asyncio
async def test_returns_the_assistant_reply():
    fake_post = AsyncMock(return_value=_text_response("Hello there!"))
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service().send(
            [ChatMessage(role="user", content="Hi")]
        )

    assert reply.message == ChatMessage(role="assistant", content="Hello there!")
    assert reply.gas_stations == []
    assert reply.ev_stations == []


@pytest.mark.asyncio
async def test_sends_the_system_instruction_and_full_conversation():
    fake_post = AsyncMock(return_value=_text_response("ok"))
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service().send(
            [
                ChatMessage(role="user", content="First"),
                ChatMessage(role="assistant", content="First reply"),
                ChatMessage(role="user", content="Second"),
            ]
        )

    args, kwargs = fake_post.call_args
    assert kwargs["params"] == {"key": "test-key"}
    payload = kwargs["json"]
    assert payload["systemInstruction"]["parts"][0]["text"]
    # "assistant" maps to Gemini's "model" role; "user" stays "user".
    assert payload["contents"] == [
        {"role": "user", "parts": [{"text": "First"}]},
        {"role": "model", "parts": [{"text": "First reply"}]},
        {"role": "user", "parts": [{"text": "Second"}]},
    ]


@pytest.mark.asyncio
async def test_raises_a_clear_error_when_no_api_key_is_configured():
    service = ChatService(FakeGasBuddyService(), FakeEvSearchService(), FakeForecastService())
    service._api_key = ""
    fake_post = AsyncMock()
    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(ChatError, match="GEMINI_API_KEY"):
            await service.send([ChatMessage(role="user", content="Hi")])

    fake_post.assert_not_called()


@pytest.mark.asyncio
async def test_raises_with_the_providers_own_error_message_on_a_rejected_request():
    fake_response = _FakeGeminiResponse(
        {"error": {"code": 400, "message": "API key not valid", "status": "INVALID_ARGUMENT"}},
        status_code=400,
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        with pytest.raises(ChatError, match="API key not valid"):
            await _configured_service().send([ChatMessage(role="user", content="Hi")])


@pytest.mark.asyncio
async def test_raises_a_generic_error_when_the_failure_response_has_no_message():
    # 500 is retried once (see test_retries_once_on_a_transient_5xx_response)
    # before giving up — every attempt fails here, so this exercises that
    # exhausted-retry path.
    fake_response = _FakeGeminiResponse({}, status_code=500)
    with patch(
        "httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)
    ), patch("app.services.gemini_client.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(ChatError, match="status 500"):
            await _configured_service().send([ChatMessage(role="user", content="Hi")])


@pytest.mark.asyncio
async def test_returns_a_friendly_message_instead_of_erroring_on_a_rate_limit():
    fake_response = _FakeGeminiResponse(
        {"error": {"code": 429, "message": "Resource exhausted"}}, status_code=429
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        reply = await _configured_service().send(
            [ChatMessage(role="user", content="Hi")]
        )

    assert reply.message.role == "assistant"
    assert reply.message.content == gemini_client.RATE_LIMIT_MESSAGE


@pytest.mark.asyncio
async def test_raises_when_the_request_itself_fails():
    # Every attempt fails, so this exhausts the built-in retry (see
    # test_retries_once_on_a_transient_network_error for the
    # retry-then-succeed case) before finally raising.
    fake_post = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ):
        with pytest.raises(ChatError):
            await _configured_service().send([ChatMessage(role="user", content="Hi")])
    assert fake_post.call_count == gemini_client.GEMINI_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_retries_once_on_a_transient_network_error():
    fake_post = AsyncMock(
        side_effect=[httpx.ReadTimeout("timed out"), _text_response("Hello!")]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        reply = await _configured_service().send(
            [ChatMessage(role="user", content="Hi")]
        )

    assert reply.message.content == "Hello!"
    assert fake_post.call_count == 2
    sleep_mock.assert_awaited_once_with(gemini_client.GEMINI_RETRY_PAUSE_SECONDS)


@pytest.mark.asyncio
async def test_recovers_from_two_consecutive_transient_timeouts():
    # Confirmed live: a single retry isn't always enough — two back-to-
    # back ReadTimeouts happened in the same request before a second
    # retry attempt was added.
    fake_post = AsyncMock(
        side_effect=[
            httpx.ReadTimeout("timed out"),
            httpx.ReadTimeout("timed out again"),
            _text_response("Hello!"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service().send(
            [ChatMessage(role="user", content="Hi")]
        )

    assert reply.message.content == "Hello!"
    assert fake_post.call_count == 3
    assert fake_post.call_count == gemini_client.GEMINI_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_retries_once_on_a_transient_5xx_response():
    fake_post = AsyncMock(
        side_effect=[
            _FakeGeminiResponse({"error": {"message": "overloaded"}}, status_code=503),
            _text_response("Hello!"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service().send(
            [ChatMessage(role="user", content="Hi")]
        )

    assert reply.message.content == "Hello!"
    assert fake_post.call_count == 2


@pytest.mark.asyncio
async def test_does_not_retry_a_4xx_that_isnt_a_rate_limit():
    fake_post = AsyncMock(
        return_value=_FakeGeminiResponse(
            {"error": {"message": "API key not valid"}}, status_code=400
        )
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(ChatError, match="API key not valid"):
            await _configured_service().send([ChatMessage(role="user", content="Hi")])

    # A real client error should never be retried — it'll fail the same
    # way every time, so retrying just wastes time and quota.
    assert fake_post.call_count == 1


@pytest.mark.asyncio
async def test_raises_on_a_malformed_success_response():
    fake_response = _FakeGeminiResponse({"candidates": []})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        with pytest.raises(ChatError):
            await _configured_service().send([ChatMessage(role="user", content="Hi")])


@pytest.mark.asyncio
async def test_calls_the_tool_and_returns_a_final_reply_using_its_results():
    gasbuddy = FakeGasBuddyService(stations=[_make_station("Shell", price=158.9)])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", {}),
            _text_response("Shell is 158.9¢, 0.5 mi away."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            gas_location=(1.0, 2.0),
        )

    assert reply.message.content == "Shell is 158.9¢, 0.5 mi away."
    assert gasbuddy.calls == [
        {
            "query": None,
            "lat": 1.0,
            "lon": 2.0,
            "limit": GASBUDDY_PAGE_SIZE,
            "cursor": None,
        }
    ]

    second_call_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response_contents = [
        c
        for c in second_call_payload["contents"]
        if "functionResponse" in c["parts"][0]
    ]
    assert len(function_response_contents) == 1
    function_response = function_response_contents[0]["parts"][0]["functionResponse"]
    assert function_response["name"] == "find_nearby_gas_stations"
    assert function_response["response"]["stations"][0]["name"] == "Shell"


@pytest.mark.asyncio
async def test_geocodes_a_named_place_from_the_function_call_args():
    gasbuddy = FakeGasBuddyService(stations=[_make_station("Esso")])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"location": "Toronto"}
            ),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas in Toronto?")]
        )

    assert gasbuddy.calls == [
        {
            "query": "Toronto",
            "lat": None,
            "lon": None,
            "limit": GASBUDDY_PAGE_SIZE,
            "cursor": None,
        }
    ]


@pytest.mark.asyncio
async def test_uses_the_provided_location_when_the_model_omits_it():
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", {}),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            gas_location=(43.4, -80.5),
        )

    assert gasbuddy.calls[0]["lat"] == 43.4
    assert gasbuddy.calls[0]["lon"] == -80.5


@pytest.mark.asyncio
async def test_reports_no_location_available_back_to_the_model_without_calling_gasbuddy():
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", {}),
            _text_response("Share your location and I can help."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            gas_location=None,
        )

    assert reply.message.content == "Share your location and I can help."
    assert gasbuddy.calls == []
    second_call_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response_contents = [
        c
        for c in second_call_payload["contents"]
        if "functionResponse" in c["parts"][0]
    ]
    error = function_response_contents[0]["parts"][0]["functionResponse"]["response"][
        "error"
    ]
    assert "location" in error.lower()


@pytest.mark.asyncio
async def test_a_tool_execution_error_is_reported_to_the_model_instead_of_crashing():
    gasbuddy = FakeGasBuddyService(error=CloudflareBlocked("blocked"))
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", {}),
            _text_response("Try again shortly."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            gas_location=(1.0, 2.0),
        )

    assert reply.message.content == "Try again shortly."


@pytest.mark.asyncio
async def test_stops_calling_the_tool_after_the_round_cap_and_forces_a_final_answer():
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", {}),
            _function_call_response("find_nearby_gas_stations", {}),
            _function_call_response("find_nearby_gas_stations", {}),
            _text_response("Final answer."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            gas_location=(1.0, 2.0),
        )

    assert reply.message.content == "Final answer."
    assert fake_post.call_count == gemini_client.MAX_TOOL_ROUNDS
    # The final round's request must not offer tools, since that's what
    # structurally forces a plain-text reply instead of another call.
    last_payload = fake_post.call_args_list[-1].kwargs["json"]
    assert "tools" not in last_payload


@pytest.mark.asyncio
async def test_unknown_tool_name_is_reported_without_crashing():
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("some_other_tool", {}),
            _text_response("I can't do that."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service().send(
            [ChatMessage(role="user", content="hi")],
            gas_location=(1.0, 2.0),
        )

    assert reply.message.content == "I can't do that."


# --- brand_tier ----------------------------------------------------------


@pytest.mark.asyncio
async def test_brand_tier_major_includes_pioneer_and_canadian_tire():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Pioneer", distance_miles=0.3),
            _make_station("Canadian Tire", distance_miles=0.5),
            _make_station("Joe's Gas", distance_miles=0.4),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"brand_tier": "major"}
            ),
            _text_response("Found major brands."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="big name brands near me")],
            gas_location=(1.0, 2.0),
        )

    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    # Pioneer and Canadian Tire are both major brands — Joe's Gas isn't.
    assert {s["name"] for s in payload["stations"]} == {"Pioneer", "Canadian Tire"}


@pytest.mark.asyncio
async def test_brand_tier_lesser_known_excludes_pioneer_and_canadian_tire():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Pioneer", distance_miles=0.3),
            _make_station("Canadian Tire", distance_miles=0.5),
            _make_station("Joe's Gas", distance_miles=0.4),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"brand_tier": "lesser_known"}
            ),
            _text_response("Found an independent station."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="independent station near me")],
            gas_location=(1.0, 2.0),
        )

    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    assert [s["name"] for s in payload["stations"]] == ["Joe's Gas"]


@pytest.mark.asyncio
async def test_brand_tier_fetches_page_two_when_no_major_match_in_page_one():
    gasbuddy = FakeGasBuddyService(
        pages={
            None: ([_make_station("Joe's Gas", distance_miles=0.3)], "20"),
            "20": ([_make_station("Pioneer", distance_miles=1.2)], None),
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"brand_tier": "major"}
            ),
            _text_response("Found Pioneer further out."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="big name brand near me")],
            gas_location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 2
    sleep_mock.assert_awaited_once_with(gemini_client.SECOND_PAGE_PAUSE_SECONDS)


@pytest.mark.asyncio
async def test_brand_tier_combined_with_fuel_grade():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Joe's Gas", distance_miles=0.3, premium=150.0),
            _make_station("Pioneer", distance_miles=0.5, premium=195.9),
            _make_station("Canadian Tire", distance_miles=0.7, premium=189.9),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations",
                {"brand_tier": "major", "fuel_grade": "premium"},
            ),
            _text_response("Cheapest big name premium is Canadian Tire."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest big name premium near me?")],
            gas_location=(1.0, 2.0),
        )

    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    # Joe's Gas is cheaper but isn't a major brand — excluded entirely,
    # not merely sorted last.
    assert [s["name"] for s in payload["stations"]] == ["Canadian Tire", "Pioneer"]
    assert payload["cheapest"]["name"] == "Canadian Tire"


@pytest.mark.asyncio
async def test_brand_tier_reports_a_clear_message_when_none_match():
    gasbuddy = FakeGasBuddyService(
        pages={
            None: ([_make_station("Joe's Gas", distance_miles=0.3)], "20"),
            "20": ([_make_station("Anne's Fuel", distance_miles=1.2)], None),
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"brand_tier": "major"}
            ),
            _text_response("No big name brands nearby, sorry."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="big name brand near me")],
            gas_location=(1.0, 2.0),
        )

    assert reply.message.content == "No big name brands nearby, sorry."
    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    error = function_response["parts"][0]["functionResponse"]["response"]["error"]
    assert "major" in error


# --- brands / exclude_brands / max_distance_miles / fuel_grade ---------


@pytest.mark.asyncio
async def test_brands_filter_is_applied_in_code_not_by_the_model():
    gasbuddy = FakeGasBuddyService(
        pages={
            None: (
                [
                    _make_station("Esso", distance_miles=0.3),
                    _make_station("Shell", distance_miles=0.6),
                ],
                None,
            )
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"brands": ["Shell"]}
            ),
            _text_response("Found a Shell."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find a Shell near me")],
            gas_location=(1.0, 2.0),
        )

    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    assert [s["name"] for s in payload["stations"]] == ["Shell"]


@pytest.mark.asyncio
async def test_multiple_brands_are_or_matched():
    gasbuddy = FakeGasBuddyService(
        pages={
            None: (
                [
                    _make_station("Esso", distance_miles=0.3),
                    _make_station("Shell", distance_miles=0.5),
                    _make_station("Petro-Canada", distance_miles=0.7),
                ],
                None,
            )
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations",
                {"brands": ["Shell", "Petro-Canada"]},
            ),
            _text_response("Found both."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="Shell or Petro-Canada near me")],
            gas_location=(1.0, 2.0),
        )

    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    assert {s["name"] for s in payload["stations"]} == {"Shell", "Petro-Canada"}


@pytest.mark.asyncio
async def test_exclude_brands_removes_matching_stations():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Petro-Canada", distance_miles=0.3),
            _make_station("Shell", distance_miles=0.5),
            _make_station("Esso", distance_miles=0.7),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations",
                {"exclude_brands": ["Petro-Canada", "Shell"]},
            ),
            _text_response("Only Esso is left."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user",
                    content="gas stations near me that are not Petro-Canada or Shell",
                )
            ],
            gas_location=(1.0, 2.0),
        )

    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    assert [s["name"] for s in payload["stations"]] == ["Esso"]


@pytest.mark.asyncio
async def test_brands_and_exclude_brands_combined_excludes_take_precedence():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Shell", distance_miles=0.3),
            _make_station("Esso", distance_miles=0.5),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations",
                {"brands": ["Shell", "Esso"], "exclude_brands": ["Shell"]},
            ),
            _text_response("Only Esso matches."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="Shell or Esso, but not Shell")],
            gas_location=(1.0, 2.0),
        )

    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    assert [s["name"] for s in payload["stations"]] == ["Esso"]


@pytest.mark.asyncio
async def test_brands_filter_fetches_page_two_when_not_found_in_page_one():
    gasbuddy = FakeGasBuddyService(
        pages={
            None: ([_make_station("Esso", distance_miles=0.3)], "20"),
            "20": ([_make_station("Shell", distance_miles=1.2)], None),
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"brands": ["Shell"]}
            ),
            _text_response("Found a Shell further out."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find a Shell near me")],
            gas_location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 2
    assert gasbuddy.calls[1]["cursor"] == "20"
    sleep_mock.assert_awaited_once_with(gemini_client.SECOND_PAGE_PAUSE_SECONDS)


@pytest.mark.asyncio
async def test_brands_filter_stops_after_page_one_when_found():
    # A next_cursor IS available, but should never be used — the brand
    # was already found in page 1 (proves the Cloudflare-safety
    # requirement: no unnecessary second call).
    gasbuddy = FakeGasBuddyService(
        pages={None: ([_make_station("Shell", distance_miles=0.3)], "20")}
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"brands": ["Shell"]}
            ),
            _text_response("Found it."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find a Shell near me")],
            gas_location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 1
    sleep_mock.assert_not_called()


@pytest.mark.asyncio
async def test_distance_fetches_page_two_when_page_one_doesnt_reach_the_radius():
    gasbuddy = FakeGasBuddyService(
        pages={
            None: ([_make_station("A", distance_miles=0.5)], "20"),
            "20": ([_make_station("B", distance_miles=3.0)], None),
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"max_distance_miles": 4.0}
            ),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas within 4 miles")],
            gas_location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 2
    sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_distance_stops_after_page_one_when_it_already_exceeds_the_radius():
    gasbuddy = FakeGasBuddyService(
        pages={
            None: (
                [
                    _make_station("A", distance_miles=0.5),
                    _make_station("B", distance_miles=5.0),
                ],
                "20",
            )
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"max_distance_miles": 4.0}
            ),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas within 4 miles")],
            gas_location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 1
    sleep_mock.assert_not_called()
    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    assert [s["name"] for s in payload["stations"]] == ["A"]


@pytest.mark.asyncio
async def test_fuel_grade_sorts_and_includes_cheapest_and_average_price():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("A", distance_miles=0.3, premium=205.0),
            _make_station("B", distance_miles=0.5, premium=195.0),
            _make_station("C", distance_miles=0.7, premium=199.0),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"fuel_grade": "premium"}
            ),
            _text_response("B is cheapest."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest premium near me?")],
            gas_location=(1.0, 2.0),
        )

    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    assert [s["name"] for s in payload["stations"]] == ["B", "C", "A"]
    assert payload["cheapest"]["name"] == "B"
    assert payload["average_price"] == pytest.approx((205.0 + 195.0 + 199.0) / 3)
    assert "sorted_by" in payload


@pytest.mark.asyncio
async def test_fuel_grade_combined_with_brands_reflects_only_the_matching_set():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Shell", distance_miles=0.3, premium=210.0),
            _make_station("Esso", distance_miles=0.4, premium=150.0),
            _make_station("Shell", distance_miles=0.6, premium=200.0),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations",
                {"brands": ["Shell"], "fuel_grade": "premium"},
            ),
            _text_response("Cheapest Shell premium."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest Shell premium near me?")],
            gas_location=(1.0, 2.0),
        )

    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    # Esso is cheaper but wasn't requested — excluded entirely, not just
    # sorted last, and the average/cheapest reflect only the two Shells.
    assert [s["name"] for s in payload["stations"]] == ["Shell", "Shell"]
    assert payload["cheapest"]["premium_price"] == "200.0¢"
    assert payload["average_price"] == pytest.approx((210.0 + 200.0) / 2)


@pytest.mark.asyncio
async def test_no_stations_match_the_requested_brand():
    gasbuddy = FakeGasBuddyService(
        pages={
            None: ([_make_station("Esso", distance_miles=0.3)], "20"),
            "20": ([_make_station("Petro-Canada", distance_miles=1.2)], None),
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"brands": ["Shell"]}
            ),
            _text_response("No Shell nearby, sorry."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find a Shell near me")],
            gas_location=(1.0, 2.0),
        )

    assert reply.message.content == "No Shell nearby, sorry."
    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    error = function_response["parts"][0]["functionResponse"]["response"]["error"]
    assert "Shell" in error


@pytest.mark.asyncio
async def test_no_stations_report_the_requested_fuel_grade():
    gasbuddy = FakeGasBuddyService(
        stations=[_make_station("A", premium=None), _make_station("B", premium=None)]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"fuel_grade": "premium"}
            ),
            _text_response("No premium prices reported."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest premium near me?")],
            gas_location=(1.0, 2.0),
        )

    assert reply.message.content == "No premium prices reported."
    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    error = function_response["parts"][0]["functionResponse"]["response"]["error"]
    assert "premium" in error


# --- calculate_fuel_cost --------------------------------------------------


def test_cost_for_volume():
    result = gemini_client._calculate_fuel_cost(
        {"mode": "cost_for_volume", "volume_litres": 50, "price_per_litre": 1.45, "price_unit": "dollars"}
    )
    assert result["cost"] == pytest.approx(72.50)
    assert result["cost_formatted"] == "$72.50"


def test_cost_for_volume_second_example():
    result = gemini_client._calculate_fuel_cost(
        {"mode": "cost_for_volume", "volume_litres": 60, "price_per_litre": 1.39, "price_unit": "dollars"}
    )
    assert result["cost"] == pytest.approx(83.40)
    assert result["cost_formatted"] == "$83.40"


def test_cost_for_volume_missing_inputs_is_an_error():
    result = gemini_client._calculate_fuel_cost({"mode": "cost_for_volume"})
    assert "error" in result


def test_volume_for_budget():
    result = gemini_client._calculate_fuel_cost(
        {"mode": "volume_for_budget", "budget": 60, "price_per_litre": 1.42, "price_unit": "dollars"}
    )
    assert result["volume_litres"] == pytest.approx(60 / 1.42)


def test_savings_via_two_absolute_prices():
    result = gemini_client._calculate_fuel_cost(
        {
            "mode": "savings",
            "volume_litres": 50,
            "price_per_litre": 1.40,
            "compare_price_per_litre": 1.47,
            "price_unit": "dollars",
        }
    )
    assert result["savings"] == pytest.approx(3.50)
    assert result["savings_formatted"] == "$3.50"


def test_savings_via_direct_price_difference_in_cents():
    result = gemini_client._calculate_fuel_cost(
        {
            "mode": "savings",
            "volume_litres": 55,
            "price_difference": 6,
            "price_unit": "cents",
        }
    )
    assert result["savings"] == pytest.approx(55 * 0.06)
    assert result["savings_formatted"] == "$3.30"


def test_savings_missing_both_comparison_forms_is_an_error():
    result = gemini_client._calculate_fuel_cost(
        {"mode": "savings", "volume_litres": 50}
    )
    assert "error" in result


def test_fill_up_cost():
    result = gemini_client._calculate_fuel_cost(
        {
            "mode": "fill_up_cost",
            "tank_capacity_litres": 60,
            "current_fill_percent": 25,
            "price_per_litre": 1.45,
            "price_unit": "dollars",
        }
    )
    assert result["volume_needed_litres"] == pytest.approx(45.0)
    assert result["cost"] == pytest.approx(65.25)
    assert result["cost_formatted"] == "$65.25"


def test_fill_up_cost_invalid_percent_is_an_error():
    result = gemini_client._calculate_fuel_cost(
        {
            "mode": "fill_up_cost",
            "tank_capacity_litres": 60,
            "current_fill_percent": 150,
            "price_per_litre": 1.45,
            "price_unit": "dollars",
        }
    )
    assert "error" in result


def test_unknown_mode_is_an_error():
    result = gemini_client._calculate_fuel_cost({"mode": "not_a_real_mode"})
    assert "error" in result


@pytest.mark.asyncio
async def test_cheapest_includes_a_raw_price_and_unit_for_chaining():
    gasbuddy = FakeGasBuddyService(
        stations=[_make_station("Shell", distance_miles=0.5, premium=195.9)]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"fuel_grade": "premium"}
            ),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest premium near me?")],
            gas_location=(1.0, 2.0),
        )

    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    assert payload["cheapest"]["price_per_litre"] == pytest.approx(195.9)
    assert payload["cheapest"]["price_unit"] == "cents"
    assert payload["average_price_unit"] == "cents"


@pytest.mark.asyncio
async def test_max_distance_km_filters_equivalently_to_miles():
    # 5 km ≈ 3.107 miles — a station at 3.0 mi should match, one at 3.5
    # mi should not.
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Close", distance_miles=3.0),
            _make_station("Far", distance_miles=3.5),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"max_distance_km": 5}
            ),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas within 5 km")],
            gas_location=(1.0, 2.0),
        )

    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    assert [s["name"] for s in payload["stations"]] == ["Close"]


@pytest.mark.asyncio
async def test_chains_a_station_search_into_a_calculator_call():
    # Mirrors "Find the cheapest Shell and calculate the cost of 60 L."
    gasbuddy = FakeGasBuddyService(
        stations=[_make_station("Shell", distance_miles=0.5, premium=None)]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations",
                {"brands": ["Shell"], "fuel_grade": "regular"},
            ),
            _function_call_response(
                "calculate_fuel_cost",
                {
                    "mode": "cost_for_volume",
                    "volume_litres": 60,
                    "price_per_litre": 158.9,
                    "price_unit": "cents",
                },
            ),
            _text_response("It would cost $95.34."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user",
                    content="Find the cheapest Shell and calculate the cost of 60 L.",
                )
            ],
            gas_location=(1.0, 2.0),
        )

    assert reply.message.content == "It would cost $95.34."
    # Round 2's request must include the calculator's functionResponse
    # with the correct computed cost.
    third_payload = fake_post.call_args_list[2].kwargs["json"]
    calc_response = next(
        c
        for c in third_payload["contents"]
        if "functionResponse" in c["parts"][0]
        and c["parts"][0]["functionResponse"]["name"] == "calculate_fuel_cost"
    )
    result = calc_response["parts"][0]["functionResponse"]["response"]
    assert result["cost"] == pytest.approx(60 * 1.589)
    assert result["cost_formatted"] == "$95.34"


# --- find_nearby_ev_chargers -----------------------------------------------


@pytest.mark.asyncio
async def test_finds_ev_chargers_with_just_a_location():
    ev_search = FakeEvSearchService(
        stations=[_make_ev_station("ChargePoint", distance_miles=0.5)]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_ev_chargers", {}),
            _text_response("Found a charger nearby."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content="where can I charge my EV?")],
            ev_location=(1.0, 2.0),
        )

    assert reply.message.content == "Found a charger nearby."
    assert ev_search.calls == [
        {"query": None, "lat": 1.0, "lon": 2.0, "limit": 20, "radius_km": None}
    ]
    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    assert payload["stations"][0]["name"] == "ChargePoint"
    assert payload["stations"][0]["connector_types"] == ["J1772", "J1772COMBO"]


@pytest.mark.asyncio
async def test_geocodes_a_named_place_for_ev_chargers():
    ev_search = FakeEvSearchService(stations=[_make_ev_station()])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_ev_chargers", {"location": "Toronto"}
            ),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content="EV chargers in Toronto")]
        )

    assert ev_search.calls == [
        {"query": "Toronto", "lat": None, "lon": None, "limit": 20, "radius_km": None}
    ]


@pytest.mark.asyncio
async def test_max_distance_km_is_passed_straight_through_as_radius_km():
    ev_search = FakeEvSearchService(stations=[_make_ev_station()])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_ev_chargers", {"max_distance_km": 10}
            ),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content="EV chargers within 10 km")],
            ev_location=(1.0, 2.0),
        )

    assert ev_search.calls == [
        {"query": None, "lat": 1.0, "lon": 2.0, "limit": 20, "radius_km": 10.0}
    ]


@pytest.mark.asyncio
async def test_ev_chargers_reports_no_location_available_without_calling_the_service():
    ev_search = FakeEvSearchService(stations=[_make_ev_station()])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_ev_chargers", {}),
            _text_response("Please share your location."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content="where can I charge my EV?")],
            ev_location=None,
        )

    assert reply.message.content == "Please share your location."
    assert ev_search.calls == []


@pytest.mark.asyncio
async def test_ev_chargers_reports_no_results_found():
    ev_search = FakeEvSearchService(stations=[])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_ev_chargers", {}),
            _text_response("No EV chargers nearby, sorry."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content="where can I charge my EV?")],
            ev_location=(1.0, 2.0),
        )

    assert reply.message.content == "No EV chargers nearby, sorry."


@pytest.mark.asyncio
async def test_ev_chargers_geocoding_error_is_reported_not_crashed():
    ev_search = FakeEvSearchService(error=GeocodingError("Could not find that place."))
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_ev_chargers", {"location": "Nowhereville"}
            ),
            _text_response("I couldn't find that place."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content="EV chargers in Nowhereville")]
        )

    assert reply.message.content == "I couldn't find that place."


@pytest.mark.asyncio
async def test_ev_chargers_geocoding_error_gives_the_model_actionable_fallback_options():
    ev_search = FakeEvSearchService(error=GeocodingError("Could not find that place."))
    payload = await _run_ev_filter_call(
        ev_search, {"location": "Nowhereville"}, message="EV chargers in Nowhereville"
    )

    assert payload["error"] == gemini_client.LOCATION_NOT_FOUND_MESSAGE
    assert "postal code" in payload["error"]
    assert "share their current location" in payload["error"]
    assert "Gas or EV tab" in payload["error"]


@pytest.mark.asyncio
async def test_gas_stations_geocoding_error_gives_the_model_actionable_fallback_options():
    gasbuddy = FakeGasBuddyService(error=GeocodingError("Could not find that place."))
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"location": "Nowhereville"}
            ),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas stations in Nowhereville")]
        )

    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    payload = function_response["parts"][0]["functionResponse"]["response"]
    assert payload["error"] == gemini_client.LOCATION_NOT_FOUND_MESSAGE


@pytest.mark.asyncio
async def test_ev_chargers_afdc_error_is_reported_not_crashed():
    ev_search = FakeEvSearchService(error=AfdcError("AFDC is down"))
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_ev_chargers", {}),
            _text_response("Sorry, try again shortly."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content="where can I charge my EV?")],
            ev_location=(1.0, 2.0),
        )

    assert reply.message.content == "Sorry, try again shortly."


# --- find_nearby_ev_chargers filters ---------------------------------------


def _ev_filter_fixture():
    return [
        _make_ev_station(
            "ChargePoint Station",
            network="ChargePoint Network",
            connector_types=["J1772"],
            level2_count=2,
            dc_fast_count=0,
        ),
        _make_ev_station(
            "Tesla Supercharger",
            network="Tesla",
            connector_types=["TESLA"],
            level2_count=0,
            dc_fast_count=8,
            connector_details=[
                EvConnectorDetail(
                    connector_type="TESLA", power_kw=250.0, voltage=480.0, amps=520.0
                )
            ],
        ),
        _make_ev_station(
            "FLO Fast",
            network="FLO",
            connector_types=["J1772COMBO"],
            level2_count=1,
            dc_fast_count=1,
            connector_details=[
                EvConnectorDetail(
                    connector_type="J1772COMBO", power_kw=50.0, voltage=400.0, amps=125.0
                )
            ],
        ),
    ]


async def _run_ev_filter_call(ev_search, args, message="find EV chargers near me"):
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_ev_chargers", args),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content=message)],
            ev_location=(1.0, 2.0),
        )
    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    return function_response["parts"][0]["functionResponse"]["response"]


@pytest.mark.asyncio
async def test_ev_networks_filter_is_applied_in_code_not_by_the_model():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"networks": ["ChargePoint"]})

    assert [s["name"] for s in payload["stations"]] == ["ChargePoint Station"]
    assert payload["filters_applied"]["networks"] == ["ChargePoint"]
    assert ev_search.calls[0]["limit"] == EV_FILTERED_FETCH_LIMIT


@pytest.mark.asyncio
async def test_ev_exclude_networks_removes_matching_stations():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"exclude_networks": ["Tesla"]})

    assert sorted(s["name"] for s in payload["stations"]) == [
        "ChargePoint Station",
        "FLO Fast",
    ]


@pytest.mark.asyncio
async def test_ev_connector_types_filter_accepts_common_aliases():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"connector_types": ["CCS"]})

    assert [s["name"] for s in payload["stations"]] == ["FLO Fast"]
    assert payload["filters_applied"]["connector_types"] == ["J1772COMBO"]


@pytest.mark.asyncio
async def test_ev_charger_levels_filter():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"charger_levels": ["dc_fast"]})

    assert sorted(s["name"] for s in payload["stations"]) == [
        "FLO Fast",
        "Tesla Supercharger",
    ]


@pytest.mark.asyncio
async def test_ev_chargers_min_filter():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"chargers_min": 3})

    assert [s["name"] for s in payload["stations"]] == ["Tesla Supercharger"]
    assert payload["filters_applied"]["chargers_range"] == (3.0, None, None)


@pytest.mark.asyncio
async def test_ev_chargers_max_filter():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"chargers_max": 2})

    assert sorted(s["name"] for s in payload["stations"]) == [
        "ChargePoint Station",
        "FLO Fast",
    ]


@pytest.mark.asyncio
async def test_ev_chargers_equals_filter():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"chargers_equals": 8})

    assert [s["name"] for s in payload["stations"]] == ["Tesla Supercharger"]


@pytest.mark.asyncio
async def test_ev_power_kw_min_filter_only_matches_stations_with_matching_connector_details():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"power_kw_min": 100})

    assert [s["name"] for s in payload["stations"]] == ["Tesla Supercharger"]


@pytest.mark.asyncio
async def test_ev_power_kw_max_filter():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"power_kw_max": 100})

    assert [s["name"] for s in payload["stations"]] == ["FLO Fast"]


@pytest.mark.asyncio
async def test_ev_power_kw_equals_filter():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"power_kw_equals": 250})

    assert [s["name"] for s in payload["stations"]] == ["Tesla Supercharger"]


@pytest.mark.asyncio
async def test_ev_voltage_min_filter():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"voltage_min": 450})

    assert [s["name"] for s in payload["stations"]] == ["Tesla Supercharger"]


@pytest.mark.asyncio
async def test_ev_amperage_max_filter():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"amperage_max": 200})

    assert [s["name"] for s in payload["stations"]] == ["FLO Fast"]


@pytest.mark.asyncio
async def test_ev_power_spec_filter_excludes_stations_with_no_connector_details():
    # ChargePoint Station has no connector_details at all (an AFDC-only
    # station, per the app's own data model) — it must never match a
    # power/voltage/amperage filter, even though it's the only station.
    ev_search = FakeEvSearchService(
        stations=[
            _make_ev_station(
                "ChargePoint Station",
                network="ChargePoint Network",
                connector_types=["J1772"],
            )
        ]
    )
    payload = await _run_ev_filter_call(ev_search, {"power_kw_min": 1})

    assert "error" in payload
    assert "at least 1 kW" in payload["error"]


@pytest.mark.asyncio
async def test_ev_combined_network_and_charger_level_filters():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(
        ev_search,
        {"networks": ["ChargePoint", "FLO"], "charger_levels": ["level2"]},
    )

    assert sorted(s["name"] for s in payload["stations"]) == [
        "ChargePoint Station",
        "FLO Fast",
    ]


@pytest.mark.asyncio
async def test_ev_zero_match_after_filtering_reports_a_clear_message():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"networks": ["NonExistentNetwork"]})

    assert "error" in payload
    assert "at all" not in payload["error"]
    assert "NonExistentNetwork" in payload["error"]


@pytest.mark.asyncio
async def test_ev_fetch_uses_the_default_limit_when_no_filters_are_set():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    await _run_ev_filter_call(ev_search, {})

    assert ev_search.calls[0]["limit"] == 20


@pytest.mark.asyncio
async def test_ev_connector_types_available_summarizes_the_returned_stations():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {})

    assert payload["connector_types_available"] == ["J1772", "J1772COMBO", "TESLA"]


@pytest.mark.asyncio
async def test_ev_sort_by_voltage_highest_ranks_and_drops_stations_without_connector_details():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(
        ev_search, {"sort_by": "voltage", "sort_order": "highest"}
    )

    assert [s["name"] for s in payload["stations"]] == [
        "Tesla Supercharger",
        "FLO Fast",
    ]
    assert payload["top_match"]["name"] == "Tesla Supercharger"
    assert "highest" in payload["sorted_by"]
    assert ev_search.calls[0]["limit"] == EV_FILTERED_FETCH_LIMIT


@pytest.mark.asyncio
async def test_ev_sort_by_voltage_lowest_reverses_the_ranking():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(
        ev_search, {"sort_by": "voltage", "sort_order": "lowest"}
    )

    assert [s["name"] for s in payload["stations"]] == [
        "FLO Fast",
        "Tesla Supercharger",
    ]
    assert payload["top_match"]["name"] == "FLO Fast"


@pytest.mark.asyncio
async def test_ev_sort_by_chargers_highest_uses_total_plug_count():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(
        ev_search, {"sort_by": "chargers", "sort_order": "highest"}
    )

    assert [s["name"] for s in payload["stations"]] == [
        "Tesla Supercharger",
        "ChargePoint Station",
        "FLO Fast",
    ]
    assert payload["top_match"]["name"] == "Tesla Supercharger"


@pytest.mark.asyncio
async def test_ev_sort_by_defaults_to_highest_when_sort_order_is_omitted():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {"sort_by": "chargers"})

    assert payload["top_match"]["name"] == "Tesla Supercharger"


@pytest.mark.asyncio
async def test_ev_sort_by_distance_defaults_to_lowest_and_returns_the_nearest():
    ev_search = FakeEvSearchService(
        stations=[
            _make_ev_station("Far", distance_miles=5.0),
            _make_ev_station("Near", distance_miles=0.4),
            _make_ev_station("Mid", distance_miles=2.0),
        ]
    )
    payload = await _run_ev_filter_call(ev_search, {"sort_by": "distance"})

    assert [s["name"] for s in payload["stations"]] == ["Near", "Mid", "Far"]
    assert payload["top_match"]["name"] == "Near"


@pytest.mark.asyncio
async def test_ev_sort_by_distance_highest_returns_the_farthest():
    ev_search = FakeEvSearchService(
        stations=[
            _make_ev_station("Far", distance_miles=5.0),
            _make_ev_station("Near", distance_miles=0.4),
        ]
    )
    payload = await _run_ev_filter_call(
        ev_search, {"sort_by": "distance", "sort_order": "highest"}
    )

    assert payload["top_match"]["name"] == "Far"


@pytest.mark.asyncio
async def test_ev_top_n_widens_cards_beyond_the_single_top_match():
    ev_search = FakeEvSearchService(
        stations=[
            _make_ev_station("Far", distance_miles=5.0),
            _make_ev_station("Near", distance_miles=0.4),
            _make_ev_station("Mid", distance_miles=2.0),
            _make_ev_station("Farthest", distance_miles=8.0),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_ev_chargers", {"sort_by": "distance", "top_n": 3}
            ),
            _text_response("Here are the 3 nearest chargers."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content="What are the 3 nearest EV chargers to me?")],
            ev_location=(1.0, 2.0),
        )

    assert [s.name for s in reply.ev_stations] == ["Near", "Mid", "Far"]


@pytest.mark.asyncio
async def test_ev_top_n_larger_than_available_stations_cards_all_of_them():
    ev_search = FakeEvSearchService(
        stations=[
            _make_ev_station("Near", distance_miles=0.4),
            _make_ev_station("Far", distance_miles=5.0),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_ev_chargers", {"sort_by": "distance", "top_n": 50}
            ),
            _text_response("Here are the nearest chargers."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content="nearest EV chargers to me?")],
            ev_location=(1.0, 2.0),
        )

    assert {s.name for s in reply.ev_stations} == {"Near", "Far"}


@pytest.mark.asyncio
async def test_ev_sort_with_no_rankable_stations_reports_a_clear_message():
    ev_search = FakeEvSearchService(
        stations=[
            _make_ev_station(
                "ChargePoint Station",
                network="ChargePoint Network",
                connector_types=["J1772"],
            )
        ]
    )
    payload = await _run_ev_filter_call(
        ev_search, {"sort_by": "voltage", "sort_order": "highest"}
    )

    assert "error" in payload
    assert "voltage" in payload["error"]


@pytest.mark.asyncio
async def test_ev_response_is_capped_to_the_nearest_stations_when_matches_exceed_the_cap():
    stations = [
        _make_ev_station(f"Station {i}", network="ChargePoint", distance_miles=i)
        for i in range(EV_MAX_STATIONS_IN_RESPONSE + 5)
    ]
    ev_search = FakeEvSearchService(stations=stations)
    payload = await _run_ev_filter_call(ev_search, {})

    assert payload["station_count"] == EV_MAX_STATIONS_IN_RESPONSE
    assert len(payload["stations"]) == EV_MAX_STATIONS_IN_RESPONSE
    # Order (by distance) is preserved by the cap — the nearest stations
    # survive, not an arbitrary slice.
    assert [s["name"] for s in payload["stations"]] == [
        f"Station {i}" for i in range(EV_MAX_STATIONS_IN_RESPONSE)
    ]
    assert payload["total_matching_count"] == EV_MAX_STATIONS_IN_RESPONSE + 5
    assert "note" in payload


@pytest.mark.asyncio
async def test_ev_response_omits_total_matching_count_when_under_the_cap():
    ev_search = FakeEvSearchService(stations=_ev_filter_fixture())
    payload = await _run_ev_filter_call(ev_search, {})

    assert "total_matching_count" not in payload
    assert "note" not in payload


# --- find_nearby_gas_and_ev_stations ---------------------------------------


def _gas_station_at(name, lat, lon, brand=None, distance_miles=0.0):
    return GasStation(
        station_id=name,
        name=name,
        brand=brand if brand is not None else name,
        address="1 Main St",
        latitude=lat,
        longitude=lon,
        distance_miles=distance_miles,
        regular=FuelPrice(price=150.0, formatted_price="150.0¢"),
    )


def _ev_station_at(name, lat, lon, network=None, distance_miles=0.0):
    return EvStation(
        station_id=name,
        name=name,
        network=network if network is not None else name,
        address="1 Charger Way",
        latitude=lat,
        longitude=lon,
        distance_miles=distance_miles,
        level2_count=1,
        connector_types=["J1772"],
    )


async def _run_combined_call(
    gasbuddy, ev_search, args, message="find a gas station and EV charger near each other"
):
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_and_ev_stations", args),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy=gasbuddy, ev_search=ev_search).send(
            [ChatMessage(role="user", content=message)],
            gas_location=(1.0, 2.0),
            ev_location=(1.0, 2.0),
        )
    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    return function_response["parts"][0]["functionResponse"]["response"]


def test_closest_gas_ev_pair_finds_the_true_minimum():
    gas_stations = [
        _gas_station_at("Near Shell", 43.0, -80.0),
        _gas_station_at("Far Esso", 50.0, -80.0),
    ]
    ev_stations = [
        _ev_station_at("Near ChargePoint", 44.0, -80.0),
        _ev_station_at("Far Tesla", 50.001, -80.001),
    ]

    result = gemini_client._closest_gas_ev_pair(gas_stations, ev_stations)

    assert result is not None
    gas, ev, distance = result
    assert gas.name == "Far Esso"
    assert ev.name == "Far Tesla"
    assert distance < 1.0


def test_closest_gas_ev_pair_is_none_when_either_side_is_empty():
    gas_stations = [_gas_station_at("Shell", 43.0, -80.0)]

    assert gemini_client._closest_gas_ev_pair(gas_stations, []) is None
    assert gemini_client._closest_gas_ev_pair([], []) is None


def test_closest_gas_ev_pair_skips_stations_missing_coordinates():
    gas_stations = [
        GasStation(station_id="No coords", name="No coords", latitude=None, longitude=None),
        _gas_station_at("Has coords", 43.0, -80.0),
    ]
    ev_stations = [_ev_station_at("EV", 43.001, -80.001)]

    result = gemini_client._closest_gas_ev_pair(gas_stations, ev_stations)

    assert result is not None
    gas, _ev, _distance = result
    assert gas.name == "Has coords"


@pytest.mark.asyncio
async def test_combined_search_surfaces_the_closest_pair_beyond_the_display_cap():
    cap = gemini_client.GAS_AND_EV_MAX_STATIONS_IN_RESPONSE
    # The true closest pair (index `cap + 4`) is deliberately ranked LAST
    # by distance-from-user on both sides — proving the cap on the
    # *displayed* lists is applied after pairing, not before (which would
    # have hidden this pair from the search entirely).
    gas_stations = [
        _gas_station_at(f"Gas {i}", 43.0 + i * 0.01, -80.0, distance_miles=i)
        for i in range(cap + 4)
    ] + [_gas_station_at(f"Gas {cap + 4}", 50.0, -80.0, distance_miles=cap + 4)]
    ev_stations = [
        _ev_station_at(f"EV {i}", 44.0 + i * 0.01, -80.0, distance_miles=i)
        for i in range(cap + 4)
    ] + [_ev_station_at(f"EV {cap + 4}", 50.001, -80.001, distance_miles=cap + 4)]

    gasbuddy = FakeGasBuddyService(stations=gas_stations)
    ev_search = FakeEvSearchService(stations=ev_stations)
    payload = await _run_combined_call(gasbuddy, ev_search, {})

    # The pairing logic considered the full fetched set (not just the
    # first `cap` by distance-from-user) — proven by finding the pair
    # ranked last on both sides. The full gas_stations/ev_stations lists
    # aren't in the payload at all once a pair exists (see the dedicated
    # test for that) — the cap only ever applied to those lists, which no
    # longer ship alongside a pair answer.
    assert payload["gas_station_count"] == cap
    assert payload["ev_station_count"] == cap
    assert "gas_stations" not in payload
    assert "ev_stations" not in payload
    assert payload["closest_pair"]["gas_station"]["name"] == f"Gas {cap + 4}"
    assert payload["closest_pair"]["ev_charger"]["name"] == f"EV {cap + 4}"
    assert payload["closest_pair"]["distance_between_miles"] < 1.0
    assert "closest_pair_note" in payload


@pytest.mark.asyncio
async def test_combined_search_omits_full_station_lists_from_the_model_when_a_pair_exists():
    # The model must never see the broader candidate lists once there's a
    # verified pair to relay — confirmed live, giving it visibility into
    # other nearby stations let it occasionally name one of THOSE instead
    # of the actual closest_pair, even on a first-time request.
    gasbuddy = FakeGasBuddyService(
        stations=[_gas_station_at("Gas A", 43.0, -80.0), _gas_station_at("Gas B", 43.1, -80.0)]
    )
    ev_search = FakeEvSearchService(
        stations=[_ev_station_at("EV A", 43.001, -80.001)]
    )
    payload = await _run_combined_call(gasbuddy, ev_search, {})

    assert "closest_pair" in payload
    assert "gas_stations" not in payload
    assert "ev_stations" not in payload
    assert payload["gas_station_count"] == 2
    assert payload["ev_station_count"] == 1


@pytest.mark.asyncio
async def test_combined_search_includes_full_station_lists_when_no_pair_exists():
    gasbuddy = FakeGasBuddyService(stations=[_gas_station_at("Gas A", 43.0, -80.0)])
    ev_search = FakeEvSearchService(stations=[])

    payload = await _run_combined_call(gasbuddy, ev_search, {})

    assert "closest_pair" not in payload
    assert [s["name"] for s in payload["gas_stations"]] == ["Gas A"]


@pytest.mark.asyncio
async def test_combined_search_filters_are_applied_before_pairing():
    gas_stations = [
        _gas_station_at("Esso Close", 43.0, -80.0, brand="Esso"),
        _gas_station_at("Shell Far", 43.05, -80.0, brand="Shell"),
    ]
    ev_stations = [
        _ev_station_at("Tesla Close", 43.001, -80.001, network="Tesla"),
        _ev_station_at("ChargePoint Far", 43.06, -80.0, network="ChargePoint"),
    ]
    gasbuddy = FakeGasBuddyService(stations=gas_stations)
    ev_search = FakeEvSearchService(stations=ev_stations)

    # Unfiltered: Esso Close + Tesla Close is the true closest pair.
    unfiltered = await _run_combined_call(
        FakeGasBuddyService(stations=gas_stations),
        FakeEvSearchService(stations=ev_stations),
        {},
    )
    assert unfiltered["closest_pair"]["gas_station"]["name"] == "Esso Close"
    assert unfiltered["closest_pair"]["ev_charger"]["name"] == "Tesla Close"

    # Filtered to Shell + ChargePoint: only the farther pair qualifies.
    filtered = await _run_combined_call(
        gasbuddy, ev_search, {"brands": ["Shell"], "networks": ["ChargePoint"]}
    )
    assert filtered["closest_pair"]["gas_station"]["name"] == "Shell Far"
    assert filtered["closest_pair"]["ev_charger"]["name"] == "ChargePoint Far"
    assert filtered["filters_applied"]["brands"] == ["Shell"]
    assert filtered["filters_applied"]["networks"] == ["ChargePoint"]


@pytest.mark.asyncio
async def test_combined_search_degrades_gracefully_when_only_ev_side_has_matches():
    gasbuddy = FakeGasBuddyService(stations=[])
    ev_search = FakeEvSearchService(stations=[_ev_station_at("EV", 43.0, -80.0)])

    payload = await _run_combined_call(gasbuddy, ev_search, {})

    assert payload["ev_station_count"] == 1
    assert payload["gas_station_count"] == 0
    assert "closest_pair" not in payload
    assert "gas_lookup_note" in payload
    assert gasbuddy.calls and ev_search.calls


@pytest.mark.asyncio
async def test_combined_search_reports_a_single_error_when_both_sides_find_nothing():
    gasbuddy = FakeGasBuddyService(stations=[])
    ev_search = FakeEvSearchService(stations=[])

    payload = await _run_combined_call(gasbuddy, ev_search, {})

    assert "error" in payload


@pytest.mark.asyncio
async def test_combined_search_geocoding_error_on_both_sides_is_reported_once():
    gasbuddy = FakeGasBuddyService(error=GeocodingError("not found"))
    ev_search = FakeEvSearchService(error=GeocodingError("not found"))

    payload = await _run_combined_call(gasbuddy, ev_search, {})

    assert payload["error"] == gemini_client.LOCATION_NOT_FOUND_MESSAGE


@pytest.mark.asyncio
async def test_combined_search_one_side_erroring_does_not_crash_the_other():
    gasbuddy = FakeGasBuddyService(error=CloudflareBlocked("blocked"))
    ev_search = FakeEvSearchService(stations=[_ev_station_at("EV", 43.0, -80.0)])

    payload = await _run_combined_call(gasbuddy, ev_search, {})

    assert payload["ev_station_count"] == 1
    assert "blocking" in payload["gas_lookup_note"]
    assert "closest_pair" not in payload


@pytest.mark.asyncio
async def test_exclude_gas_and_ev_stations_forces_the_next_nearest_pair():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _gas_station_at("Near Gas", 43.0, -80.0),
            _gas_station_at("Far Gas", 43.5, -80.0),
        ]
    )
    ev_search = FakeEvSearchService(
        stations=[
            _ev_station_at("Near EV", 43.0001, -80.0001),
            _ev_station_at("Far EV", 43.5005, -80.0005),
        ]
    )
    payload = await _run_combined_call(
        gasbuddy,
        ev_search,
        {"exclude_gas_stations": ["Near Gas"], "exclude_ev_stations": ["Near EV"]},
    )

    assert payload["closest_pair"]["gas_station"]["name"] == "Far Gas"
    assert payload["closest_pair"]["ev_charger"]["name"] == "Far EV"
    assert payload["filters_applied"]["exclude_gas_stations"] == ["Near Gas"]
    assert payload["filters_applied"]["exclude_ev_stations"] == ["Near EV"]


@pytest.mark.asyncio
async def test_excluding_every_gas_station_falls_back_to_the_no_match_note():
    gasbuddy = FakeGasBuddyService(stations=[_gas_station_at("Only Gas", 43.0, -80.0)])
    ev_search = FakeEvSearchService(stations=[_ev_station_at("Only EV", 43.001, -80.001)])

    payload = await _run_combined_call(
        gasbuddy, ev_search, {"exclude_gas_stations": ["Only Gas"]}
    )

    assert payload["ev_station_count"] == 1
    assert "gas_lookup_note" in payload
    assert "closest_pair" not in payload


@pytest.mark.asyncio
async def test_asking_for_another_pair_with_exclusions_returns_a_genuinely_different_result():
    # Directly covers the reported bug: "find another gas station and EV
    # charger" must produce a real, code-verified DIFFERENT pair — both in
    # the text (via a real second tool call) and in the cards
    # (ChatTurnResult.gas_stations/ev_stations), not a repeat of turn 1's.
    gasbuddy = FakeGasBuddyService(
        stations=[
            _gas_station_at("Near Gas", 43.0, -80.0),
            _gas_station_at("Far Gas", 43.5, -80.0),
        ]
    )
    ev_search = FakeEvSearchService(
        stations=[
            _ev_station_at("Near EV", 43.0001, -80.0001),
            _ev_station_at("Far EV", 43.5005, -80.0005),
        ]
    )

    fake_post_1 = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_and_ev_stations", {}),
            _text_response("Near Gas and Near EV are closest to each other."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post_1):
        reply1 = await _configured_service(gasbuddy=gasbuddy, ev_search=ev_search).send(
            [ChatMessage(role="user", content="find closest gas and ev pair")],
            gas_location=(1.0, 2.0),
            ev_location=(1.0, 2.0),
        )

    assert [s.name for s in reply1.gas_stations] == ["Near Gas"]
    assert [s.name for s in reply1.ev_stations] == ["Near EV"]

    fake_post_2 = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_and_ev_stations",
                {"exclude_gas_stations": ["Near Gas"], "exclude_ev_stations": ["Near EV"]},
            ),
            _text_response("Far Gas and Far EV are another close pair."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post_2):
        reply2 = await _configured_service(gasbuddy=gasbuddy, ev_search=ev_search).send(
            [
                ChatMessage(role="user", content="find closest gas and ev pair"),
                ChatMessage(role="assistant", content=reply1.message.content),
                ChatMessage(role="user", content="find another gas station and ev charger"),
            ],
            gas_location=(1.0, 2.0),
            ev_location=(1.0, 2.0),
        )

    assert [s.name for s in reply2.gas_stations] == ["Far Gas"]
    assert [s.name for s in reply2.ev_stations] == ["Far EV"]
    assert reply1.gas_stations[0].name != reply2.gas_stations[0].name
    assert reply1.ev_stations[0].name != reply2.ev_stations[0].name


# --- get_gas_price_forecast -------------------------------------------------


async def _run_forecast_call(
    forecast_service, args, message="what's tomorrow's gas price?", gas_location=(1.0, 2.0)
):
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("get_gas_price_forecast", args),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        kwargs = {} if gas_location is None else {"gas_location": gas_location}
        await _configured_service(forecast=forecast_service).send(
            [ChatMessage(role="user", content=message)], **kwargs
        )
    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    return function_response["parts"][0]["functionResponse"]["response"]


@pytest.mark.asyncio
async def test_forecast_relays_all_computed_fields():
    forecast_service = FakeForecastService(result=_make_forecast())
    payload = await _run_forecast_call(forecast_service, {})

    assert forecast_service.calls == [{"lat": 1.0, "lon": 2.0}]
    assert payload["forecasted_price"] == 152.0
    assert payload["trend_direction"] == "up"
    assert payload["price_change"] == 2.0
    assert payload["forecasted_lowest_price"] == 146.9
    assert payload["forecasted_highest_price"] == 162.1
    assert payload["lowest_price_change"] == 1.9
    assert payload["highest_price_change"] == 2.1
    assert "next-day forecast ONLY" in payload["note"]


@pytest.mark.asyncio
async def test_forecast_geocodes_a_named_place_before_calling_the_service():
    forecast_service = FakeForecastService(result=_make_forecast())
    with patch(
        "app.services.gemini_client.geocode", new=AsyncMock(return_value=(10.0, 20.0))
    ):
        payload = await _run_forecast_call(
            forecast_service,
            {"location": "Toronto"},
            message="tomorrow's gas price in Toronto",
        )

    assert forecast_service.calls == [{"lat": 10.0, "lon": 20.0}]
    assert payload["forecasted_price"] == 152.0


@pytest.mark.asyncio
async def test_forecast_reports_no_location_available_without_calling_the_service():
    forecast_service = FakeForecastService(result=_make_forecast())
    payload = await _run_forecast_call(forecast_service, {}, gas_location=None)

    assert payload["error"] == gemini_client.NO_LOCATION_MESSAGE
    assert forecast_service.calls == []


@pytest.mark.asyncio
async def test_forecast_geocoding_error_is_reported():
    forecast_service = FakeForecastService(result=_make_forecast())
    with patch(
        "app.services.gemini_client.geocode",
        new=AsyncMock(side_effect=GeocodingError("not found")),
    ):
        payload = await _run_forecast_call(
            forecast_service, {"location": "Nowhereville"}
        )

    assert payload["error"] == gemini_client.LOCATION_NOT_FOUND_MESSAGE
    assert forecast_service.calls == []


@pytest.mark.asyncio
async def test_forecast_source_none_adds_the_honesty_note():
    forecast_service = FakeForecastService(
        result=_make_forecast(
            source="none",
            trend_direction="flat",
            daily_change_pct=None,
            forecasted_price=150.0,
            price_change=0.0,
        )
    )
    payload = await _run_forecast_call(forecast_service, {})

    assert "source is 'none'" in payload["note"]
    assert "not an actual prediction" in payload["note"] or "actual prediction" in payload["note"]


@pytest.mark.asyncio
async def test_forecast_zero_stations_sampled_reports_a_clear_error():
    forecast_service = FakeForecastService(result=_make_forecast(stations_sampled=0))
    payload = await _run_forecast_call(forecast_service, {})

    assert "error" in payload
    assert "No nearby gas stations" in payload["error"]


@pytest.mark.asyncio
async def test_forecast_cloudflare_blocked_is_reported_not_crashed():
    forecast_service = FakeForecastService(error=CloudflareBlocked("blocked"))
    payload = await _run_forecast_call(forecast_service, {})

    assert "error" in payload
    assert "blocking" in payload["error"]


# --- gas price report freshness ---------------------------------------------


async def _run_gas_filter_call(gasbuddy, args, message="gas stations near me"):
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", args),
            _text_response("ok"),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.gemini_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content=message)],
            gas_location=(1.0, 2.0),
        )
    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    return function_response["parts"][0]["functionResponse"]["response"]


def test_minutes_since_computes_whole_minutes_for_a_known_offset():
    timestamp = _iso_minutes_ago(12)
    assert gemini_client._minutes_since(timestamp) == 12


def test_minutes_since_returns_none_for_missing_or_bad_input():
    assert gemini_client._minutes_since(None) is None
    assert gemini_client._minutes_since("not a timestamp") is None


def test_format_minutes_ago_buckets():
    assert gemini_client._format_minutes_ago(0) == "just now"
    assert gemini_client._format_minutes_ago(1) == "1 minute ago"
    assert gemini_client._format_minutes_ago(12) == "12 minutes ago"
    assert gemini_client._format_minutes_ago(60) == "1 hour ago"
    assert gemini_client._format_minutes_ago(150) == "2 hours ago"
    assert gemini_client._format_minutes_ago(60 * 24 * 2) == "2 days ago"


def test_station_summary_includes_report_age_per_grade():
    station = _make_station(
        regular_reported_minutes_ago=5, premium=189.9, premium_reported_minutes_ago=200
    )

    summary = gemini_client._station_summary(station)

    assert summary["regular_reported_minutes_ago"] == 5
    assert summary["regular_reported"] == "5 minutes ago"
    assert summary["premium_reported_minutes_ago"] == 200
    assert summary["premium_reported"] == "3 hours ago"
    # No diesel price at all — both fields are None, not an error.
    assert summary["diesel_reported_minutes_ago"] is None
    assert summary["diesel_reported"] is None


@pytest.mark.asyncio
async def test_max_report_age_minutes_filters_out_stale_prices():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Fresh", regular_reported_minutes_ago=10),
            _make_station("Stale", regular_reported_minutes_ago=120),
        ]
    )
    payload = await _run_gas_filter_call(gasbuddy, {"max_report_age_minutes": 30})

    assert [s["name"] for s in payload["stations"]] == ["Fresh"]
    assert payload["filters_applied"]["max_report_age_minutes"] == 30.0


@pytest.mark.asyncio
async def test_max_report_age_minutes_combined_with_fuel_grade_finds_cheapest_among_fresh():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Cheap but stale", price=140.0, regular_reported_minutes_ago=120),
            _make_station("Pricier but fresh", price=160.0, regular_reported_minutes_ago=5),
        ]
    )
    payload = await _run_gas_filter_call(
        gasbuddy, {"fuel_grade": "regular", "max_report_age_minutes": 30}
    )

    assert payload["cheapest"]["name"] == "Pricier but fresh"
    assert [s["name"] for s in payload["stations"]] == ["Pricier but fresh"]


@pytest.mark.asyncio
async def test_max_report_age_minutes_reports_a_clear_message_when_nothing_is_fresh_enough():
    gasbuddy = FakeGasBuddyService(
        stations=[_make_station("Stale", regular_reported_minutes_ago=120)]
    )
    payload = await _run_gas_filter_call(gasbuddy, {"max_report_age_minutes": 30})

    assert "error" in payload
    assert "30" in payload["error"]


@pytest.mark.asyncio
async def test_sort_by_recency_orders_freshest_first_and_sets_most_recent():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Oldest", regular_reported_minutes_ago=180),
            _make_station("Freshest", regular_reported_minutes_ago=2),
            _make_station("Middle", regular_reported_minutes_ago=45),
        ]
    )
    payload = await _run_gas_filter_call(gasbuddy, {"sort_by_recency": True})

    assert [s["name"] for s in payload["stations"]] == ["Freshest", "Middle", "Oldest"]
    assert payload["most_recent"]["name"] == "Freshest"
    assert "recency" in payload["sorted_by"]


@pytest.mark.asyncio
async def test_sort_by_recency_drops_stations_with_no_report_time():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Has timestamp", regular_reported_minutes_ago=10),
            _make_station("No timestamp"),
        ]
    )
    payload = await _run_gas_filter_call(gasbuddy, {"sort_by_recency": True})

    assert [s["name"] for s in payload["stations"]] == ["Has timestamp"]


@pytest.mark.asyncio
async def test_sort_by_recency_combined_with_fuel_grade_can_surface_different_stations():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Cheap and stale", price=140.0, regular_reported_minutes_ago=180),
            _make_station("Pricey but fresh", price=170.0, regular_reported_minutes_ago=2),
        ]
    )
    payload = await _run_gas_filter_call(
        gasbuddy, {"fuel_grade": "regular", "sort_by_recency": True}
    )

    # cheapest still answers "cheapest", most_recent still answers
    # "freshest" — they don't have to agree, and the final list/sorted_by
    # reflect recency (the more specific ask) since both were set.
    assert payload["cheapest"]["name"] == "Cheap and stale"
    assert payload["most_recent"]["name"] == "Pricey but fresh"
    assert [s["name"] for s in payload["stations"]] == ["Pricey but fresh", "Cheap and stale"]
    assert "recency" in payload["sorted_by"]


@pytest.mark.asyncio
async def test_sort_by_distance_orders_nearest_first_and_sets_nearest():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Far", distance_miles=5.0),
            _make_station("Near", distance_miles=0.3),
            _make_station("Mid", distance_miles=2.0),
        ]
    )
    payload = await _run_gas_filter_call(gasbuddy, {"sort_by_distance": True})

    assert [s["name"] for s in payload["stations"]] == ["Near", "Mid", "Far"]
    assert payload["nearest"]["name"] == "Near"
    assert "distance" in payload["sorted_by"]


@pytest.mark.asyncio
async def test_sort_by_distance_and_fuel_grade_together_can_surface_different_stations():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Near but pricey", distance_miles=0.3, price=170.0),
            _make_station("Far but cheap", distance_miles=5.0, price=140.0),
        ]
    )
    payload = await _run_gas_filter_call(
        gasbuddy, {"fuel_grade": "regular", "sort_by_distance": True}
    )

    # nearest still answers "closest", cheapest still answers "cheapest"
    # — they don't have to agree, and the final list/sorted_by reflect
    # distance (the more specific ask) since both were set.
    assert payload["nearest"]["name"] == "Near but pricey"
    assert payload["cheapest"]["name"] == "Far but cheap"
    assert [s["name"] for s in payload["stations"]] == ["Near but pricey", "Far but cheap"]
    assert "distance" in payload["sorted_by"]


@pytest.mark.asyncio
async def test_gas_top_n_is_echoed_in_filters_applied():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Cheapest", price=140.0),
            _make_station("Mid", price=160.0),
        ]
    )
    payload = await _run_gas_filter_call(
        gasbuddy, {"fuel_grade": "regular", "top_n": 2}
    )

    assert payload["filters_applied"]["top_n"] == 2


@pytest.mark.asyncio
async def test_gas_top_n_larger_than_available_stations_cards_all_of_them():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Near", distance_miles=0.3),
            _make_station("Far", distance_miles=5.0),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"sort_by_distance": True, "top_n": 50}
            ),
            _text_response("Here are the nearest gas stations."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="nearest gas stations to me?")],
            gas_location=(1.0, 2.0),
        )

    assert {s.name for s in reply.gas_stations} == {"Near", "Far"}


# --- ChatTurnResult station data (for chat card rendering) -----------------


@pytest.mark.asyncio
async def test_gas_station_search_populates_chatturnresult_gas_stations():
    gasbuddy = FakeGasBuddyService(stations=[_make_station("Shell"), _make_station("Esso")])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", {}),
            _text_response("Here are some stations."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            gas_location=(1.0, 2.0),
        )

    assert {s.name for s in reply.gas_stations} == {"Shell", "Esso"}
    assert reply.ev_stations == []


@pytest.mark.asyncio
async def test_ev_charger_search_populates_chatturnresult_ev_stations():
    ev_search = FakeEvSearchService(stations=[_make_ev_station("ChargePoint")])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_ev_chargers", {}),
            _text_response("Here's a charger."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content="EV chargers near me?")],
            ev_location=(1.0, 2.0),
        )

    assert {s.name for s in reply.ev_stations} == {"ChargePoint"}
    assert reply.gas_stations == []


@pytest.mark.asyncio
async def test_combined_search_populates_both_chatturnresult_station_lists():
    gasbuddy = FakeGasBuddyService(stations=[_gas_station_at("Shell", 43.0, -80.0)])
    ev_search = FakeEvSearchService(stations=[_ev_station_at("ChargePoint", 43.0, -80.0)])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_and_ev_stations", {}),
            _text_response("Here's both."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy=gasbuddy, ev_search=ev_search).send(
            [ChatMessage(role="user", content="gas and ev near me?")],
            gas_location=(1.0, 2.0),
            ev_location=(1.0, 2.0),
        )

    assert {s.name for s in reply.gas_stations} == {"Shell"}
    assert {s.name for s in reply.ev_stations} == {"ChargePoint"}


@pytest.mark.asyncio
async def test_calculator_only_turn_returns_no_stations():
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "calculate_fuel_cost",
                {"mode": "cost_for_volume", "volume_litres": 40, "price_per_litre": 1.5},
            ),
            _text_response("That'll cost $60."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service().send(
            [ChatMessage(role="user", content="cost of 40L at $1.50/L?")]
        )

    assert reply.gas_stations == []
    assert reply.ev_stations == []


@pytest.mark.asyncio
async def test_forecast_only_turn_returns_no_stations():
    forecast_service = FakeForecastService(result=_make_forecast())
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("get_gas_price_forecast", {}),
            _text_response("Prices are trending up."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(forecast=forecast_service).send(
            [ChatMessage(role="user", content="gas price tomorrow?")],
            gas_location=(1.0, 2.0),
        )

    assert reply.gas_stations == []
    assert reply.ev_stations == []


@pytest.mark.asyncio
async def test_a_station_found_by_two_tool_calls_in_one_turn_is_not_duplicated():
    gasbuddy = FakeGasBuddyService(stations=[_make_station("Shell")])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", {"brands": ["Shell"]}),
            _function_call_response("find_nearby_gas_stations", {"brands": ["Shell"]}),
            _text_response("Found Shell twice, but it's the same station."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="compare Shell to Shell?")],
            gas_location=(1.0, 2.0),
        )

    assert len(reply.gas_stations) == 1
    assert reply.gas_stations[0].name == "Shell"


@pytest.mark.asyncio
async def test_error_tool_response_contributes_no_stations():
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", {}),
            _text_response("Please share your location."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service().send(
            [ChatMessage(role="user", content="gas near me?")],
            gas_location=None,
        )

    assert reply.gas_stations == []
    assert reply.ev_stations == []


# --- ChatTurnResult cards reflect the highlighted answer, not the pool -----


@pytest.mark.asyncio
async def test_cheapest_query_only_cards_the_cheapest_station_not_every_match():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Cheap", price=150.0),
            _make_station("Mid", price=160.0),
            _make_station("Pricey", price=170.0),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", {"fuel_grade": "regular"}),
            _text_response("Cheap has the lowest price."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest gas near me?")],
            gas_location=(1.0, 2.0),
        )

    assert [s.name for s in reply.gas_stations] == ["Cheap"]


@pytest.mark.asyncio
async def test_recency_query_only_cards_the_freshest_station():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Stale", regular_reported_minutes_ago=180),
            _make_station("Fresh", regular_reported_minutes_ago=2),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", {"sort_by_recency": True}),
            _text_response("Fresh was reported most recently."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="most recently updated gas price?")],
            gas_location=(1.0, 2.0),
        )

    assert [s.name for s in reply.gas_stations] == ["Fresh"]


@pytest.mark.asyncio
async def test_cheapest_and_recency_together_can_card_two_distinct_stations():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Cheap and stale", price=140.0, regular_reported_minutes_ago=180),
            _make_station("Pricey but fresh", price=170.0, regular_reported_minutes_ago=2),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations",
                {"fuel_grade": "regular", "sort_by_recency": True},
            ),
            _text_response("Here's the cheapest and the freshest."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest and freshest gas near me?")],
            gas_location=(1.0, 2.0),
        )

    assert {s.name for s in reply.gas_stations} == {"Cheap and stale", "Pricey but fresh"}


@pytest.mark.asyncio
async def test_closest_gas_station_query_only_cards_the_nearest_station_not_every_match():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Near", distance_miles=0.3),
            _make_station("Mid", distance_miles=2.0),
            _make_station("Far", distance_miles=5.0),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", {"sort_by_distance": True}),
            _text_response("Near is the closest gas station."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="What is the closest gas station to me?")],
            gas_location=(1.0, 2.0),
        )

    assert [s.name for s in reply.gas_stations] == ["Near"]


@pytest.mark.asyncio
async def test_top_n_gas_query_cards_the_requested_count_not_just_one():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _make_station("Priciest", price=180.0),
            _make_station("Cheapest", price=140.0),
            _make_station("Mid", price=160.0),
            _make_station("Second cheapest", price=150.0),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_gas_stations", {"fuel_grade": "regular", "top_n": 3}
            ),
            _text_response("Here are the 3 cheapest gas stations."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="What are the 3 cheapest gas stations near me?")],
            gas_location=(1.0, 2.0),
        )

    assert [s.name for s in reply.gas_stations] == ["Cheapest", "Second cheapest", "Mid"]


@pytest.mark.asyncio
async def test_closest_ev_station_query_only_cards_the_nearest_station_not_every_match():
    ev_search = FakeEvSearchService(
        stations=[
            _make_ev_station("Near", distance_miles=0.3),
            _make_ev_station("Mid", distance_miles=2.0),
            _make_ev_station("Far", distance_miles=5.0),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_ev_chargers", {"sort_by": "distance"}),
            _text_response("Near is the closest EV station."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content="What is the closest EV station to me?")],
            ev_location=(1.0, 2.0),
        )

    assert [s.name for s in reply.ev_stations] == ["Near"]


@pytest.mark.asyncio
async def test_ev_ranking_query_only_cards_the_top_match_not_every_match():
    ev_search = FakeEvSearchService(
        stations=[
            _make_ev_station(
                "Low kW",
                connector_details=[
                    EvConnectorDetail(connector_type="J1772COMBO", power_kw=50.0)
                ],
            ),
            _make_ev_station(
                "High kW",
                connector_details=[
                    EvConnectorDetail(connector_type="J1772COMBO", power_kw=250.0)
                ],
            ),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response(
                "find_nearby_ev_chargers", {"sort_by": "power_kw", "sort_order": "highest"}
            ),
            _text_response("High kW is the fastest."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(ev_search=ev_search).send(
            [ChatMessage(role="user", content="highest kW charger near me?")],
            ev_location=(1.0, 2.0),
        )

    assert [s.name for s in reply.ev_stations] == ["High kW"]


@pytest.mark.asyncio
async def test_closest_pair_query_only_cards_the_pair_not_every_nearby_station():
    gasbuddy = FakeGasBuddyService(
        stations=[
            _gas_station_at("Near Gas", 43.0, -80.0),
            _gas_station_at("Far Gas", 50.0, -80.0),
        ]
    )
    ev_search = FakeEvSearchService(
        stations=[
            _ev_station_at("Near EV", 44.0, -80.0),
            _ev_station_at("Far EV", 50.001, -80.001),
        ]
    )
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_and_ev_stations", {}),
            _text_response("Far Gas and Far EV are closest to each other."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy=gasbuddy, ev_search=ev_search).send(
            [
                ChatMessage(
                    role="user",
                    content="find a gas station and EV charger closest to each other",
                )
            ],
            gas_location=(1.0, 2.0),
            ev_location=(1.0, 2.0),
        )

    assert [s.name for s in reply.gas_stations] == ["Far Gas"]
    assert [s.name for s in reply.ev_stations] == ["Far EV"]
