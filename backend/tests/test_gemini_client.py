from unittest.mock import AsyncMock, patch

import httpx
import pytest
from py_gasbuddy import APIError, CloudflareBlocked, LibraryError, MissingSearchData

from app.models.schemas import ChatMessage, FuelPrice, GasStation
from app.services import gemini_client
from app.services.gemini_client import ChatError, ChatService
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
    name="Shell", price=158.9, distance_miles=0.5, brand=None, premium=None
):
    return GasStation(
        station_id=name,
        name=name,
        brand=brand if brand is not None else name,
        address="1 Main St",
        distance_miles=distance_miles,
        regular=FuelPrice(price=price, formatted_price=f"{price}¢"),
        premium=(
            FuelPrice(price=premium, formatted_price=f"{premium}¢")
            if premium is not None
            else None
        ),
    )


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


def _configured_service(gasbuddy=None) -> ChatService:
    # Bypasses get_settings() (which reads the real environment) so these
    # tests can exercise a "configured" ChatService regardless of what's
    # actually in .env.
    service = ChatService(gasbuddy or FakeGasBuddyService())
    service._api_key = "test-key"
    return service


@pytest.mark.asyncio
async def test_returns_the_assistant_reply():
    fake_post = AsyncMock(return_value=_text_response("Hello there!"))
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service().send(
            [ChatMessage(role="user", content="Hi")]
        )

    assert reply == ChatMessage(role="assistant", content="Hello there!")


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
    service = ChatService(FakeGasBuddyService())
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

    assert reply.role == "assistant"
    assert reply.content == gemini_client.RATE_LIMIT_MESSAGE


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

    assert reply.content == "Hello!"
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

    assert reply.content == "Hello!"
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

    assert reply.content == "Hello!"
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
            location=(1.0, 2.0),
        )

    assert reply.content == "Shell is 158.9¢, 0.5 mi away."
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
            location=(43.4, -80.5),
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
            location=None,
        )

    assert reply.content == "Share your location and I can help."
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
            location=(1.0, 2.0),
        )

    assert reply.content == "Try again shortly."


@pytest.mark.asyncio
async def test_stops_calling_the_tool_after_the_round_cap_and_forces_a_final_answer():
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _function_call_response("find_nearby_gas_stations", {}),
            _function_call_response("find_nearby_gas_stations", {}),
            _text_response("Final answer."),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            location=(1.0, 2.0),
        )

    assert reply.content == "Final answer."
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
            location=(1.0, 2.0),
        )

    assert reply.content == "I can't do that."


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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
        )

    assert reply.content == "No big name brands nearby, sorry."
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
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
            location=(1.0, 2.0),
        )

    assert reply.content == "No Shell nearby, sorry."
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
            location=(1.0, 2.0),
        )

    assert reply.content == "No premium prices reported."
    second_payload = fake_post.call_args_list[1].kwargs["json"]
    function_response = next(
        c for c in second_payload["contents"] if "functionResponse" in c["parts"][0]
    )
    error = function_response["parts"][0]["functionResponse"]["response"]["error"]
    assert "premium" in error
