import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from py_gasbuddy import APIError, CloudflareBlocked, LibraryError, MissingSearchData

from app.models.schemas import ChatMessage, FuelPrice, GasStation
from app.services import chat_client
from app.services.chat_client import ChatError, ChatService
from app.services.gasbuddy_client import GASBUDDY_PAGE_SIZE, StationSearchResult
from app.services.geocoding import GeocodingError


class _FakeGroqResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=httpx.Request("POST", chat_client.GROQ_URL),
                response=self,  # type: ignore[arg-type]
            )

    def json(self):
        return self._body


class FakeGasBuddyService:
    def __init__(self, stations=None, error=None, pages=None, by_query=None):
        # `pages`: {cursor_used_to_request: (stations, next_cursor)};
        # `None` key = page 1. `stations` is shorthand for a single page
        # with no follow-up (`{None: (stations, None)}`).
        #
        # `by_query`: {query: stations_or_exception} — for multi-location
        # tests, where each place needs its own distinct single-page
        # result (or its own failure) regardless of cursor. Takes
        # precedence over `pages` when given.
        self._pages = (
            dict(pages) if pages is not None else {None: (stations or [], None)}
        )
        self._by_query = dict(by_query) if by_query is not None else None
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
        if self._by_query is not None:
            if query not in self._by_query:
                raise AssertionError(f"unexpected GasBuddy call with query={query!r}")
            value = self._by_query[query]
            if isinstance(value, Exception):
                raise value
            return StationSearchResult(
                stations=value, next_cursor=None, lat=lat or 0.0, lon=lon or 0.0
            )
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


def _success_body(content: str):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _tool_call_body(name: str, arguments: dict, call_id: str = "call_1"):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                }
            }
        ]
    }


def _configured_service(gasbuddy=None) -> ChatService:
    # Bypasses get_settings() (which reads the real environment, and has a
    # real key configured in this dev setup) so these tests can exercise a
    # "configured" ChatService regardless of what's actually in .env.
    service = ChatService(gasbuddy or FakeGasBuddyService())
    service._api_key = "test-key"
    return service


@pytest.mark.asyncio
async def test_returns_the_assistant_reply():
    fake_response = _FakeGroqResponse(_success_body("Hello there!"))
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        reply = await _configured_service().send(
            [ChatMessage(role="user", content="Hi")]
        )

    assert reply.role == "assistant"
    assert reply.content == "Hello there!"


@pytest.mark.asyncio
async def test_sends_the_system_prompt_and_full_conversation_to_groq():
    fake_response = _FakeGroqResponse(_success_body("ok"))
    fake_post = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service().send(
            [
                ChatMessage(role="user", content="First"),
                ChatMessage(role="assistant", content="First reply"),
                ChatMessage(role="user", content="Second"),
            ]
        )

    args, kwargs = fake_post.call_args
    assert args[0] == chat_client.GROQ_URL
    sent_messages = kwargs["json"]["messages"]
    assert sent_messages[0]["role"] == "system"
    assert sent_messages[1:] == [
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "First reply"},
        {"role": "user", "content": "Second"},
    ]


@pytest.mark.asyncio
async def test_raises_a_clear_error_when_no_api_key_is_configured():
    # Confirmed live: an empty key produces an "Authorization: Bearer "
    # header that httpx's own http.client rejects locally before any
    # request is sent, with a confusing low-level error — this check
    # exists specifically to avoid surfacing that instead. Forces the key
    # empty directly rather than relying on the environment having none
    # configured (dev's own backend/.env has a real one).
    service = ChatService(FakeGasBuddyService())
    service._api_key = ""
    fake_post = AsyncMock()
    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(ChatError, match="GROQ_API_KEY"):
            await service.send([ChatMessage(role="user", content="Hi")])

    fake_post.assert_not_called()


@pytest.mark.asyncio
async def test_raises_with_groqs_own_error_message_on_a_rejected_request():
    # Confirmed live: an invalid/missing API key gets this exact shape back
    # from Groq (a 401), so there's no separate "missing key" check here —
    # the request just fails the same way an invalid key does.
    fake_response = _FakeGroqResponse(
        {"error": {"message": "Invalid API Key"}}, status_code=401
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        with pytest.raises(ChatError, match="Invalid API Key"):
            await _configured_service().send([ChatMessage(role="user", content="Hi")])


@pytest.mark.asyncio
async def test_raises_a_generic_error_when_the_failure_response_has_no_message():
    fake_response = _FakeGroqResponse({}, status_code=500)
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        with pytest.raises(ChatError, match="status 500"):
            await _configured_service().send([ChatMessage(role="user", content="Hi")])


@pytest.mark.asyncio
async def test_returns_a_friendly_message_instead_of_erroring_on_a_groq_rate_limit():
    fake_response = _FakeGroqResponse(
        {"error": {"message": "Rate limit reached for model ... on TPM"}},
        status_code=429,
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        reply = await _configured_service().send(
            [ChatMessage(role="user", content="Hi")]
        )

    assert reply.role == "assistant"
    assert reply.content == chat_client.RATE_LIMIT_MESSAGE


@pytest.mark.asyncio
async def test_rate_limit_message_also_returned_when_hit_after_a_tool_call():
    # The limit can just as easily be hit on the round AFTER a tool call
    # (its prompt is bigger, carrying the tool result) as on the first —
    # this should be caught regardless of which round it happens on.
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(_tool_call_body("find_nearby_gas_stations", {})),
            _FakeGroqResponse(
                {"error": {"message": "Rate limit reached"}}, status_code=429
            ),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            location=(1.0, 2.0),
        )

    assert reply.content == chat_client.RATE_LIMIT_MESSAGE


@pytest.mark.asyncio
async def test_raises_when_the_request_itself_fails():
    fake_post = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(ChatError):
            await _configured_service().send([ChatMessage(role="user", content="Hi")])


@pytest.mark.asyncio
async def test_raises_on_a_malformed_success_response():
    fake_response = _FakeGroqResponse({"choices": []})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        with pytest.raises(ChatError):
            await _configured_service().send([ChatMessage(role="user", content="Hi")])


@pytest.mark.asyncio
async def test_calls_the_tool_and_returns_a_final_reply_using_its_results():
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {}, call_id="call_abc"
                )
            ),
            _FakeGroqResponse(_success_body("The cheapest is Shell at 158.9¢.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            location=(41.88, -87.63),
        )

    assert reply.content == "The cheapest is Shell at 158.9¢."
    assert gasbuddy.calls == [
        {
            "query": None,
            "lat": 41.88,
            "lon": -87.63,
            "limit": GASBUDDY_PAGE_SIZE,
            "cursor": None,
        }
    ]

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_messages = [m for m in second_call_messages if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_abc"
    assert "Shell" in tool_messages[0]["content"]


@pytest.mark.asyncio
async def test_geocodes_a_named_place_from_the_tool_arguments():
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"location": "Toronto"}
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas in Toronto?")],
            location=(41.88, -87.63),
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
            _FakeGroqResponse(_tool_call_body("find_nearby_gas_stations", {})),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            location=(1.0, 2.0),
        )

    assert gasbuddy.calls == [
        {
            "query": None,
            "lat": 1.0,
            "lon": 2.0,
            "limit": GASBUDDY_PAGE_SIZE,
            "cursor": None,
        }
    ]


@pytest.mark.asyncio
async def test_reports_no_location_available_back_to_the_model_without_calling_gasbuddy():
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(_tool_call_body("find_nearby_gas_stations", {})),
            _FakeGroqResponse(_success_body("Where are you located?")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            location=None,
        )

    assert gasbuddy.calls == []
    assert reply.content == "Where are you located?"

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    assert "location" in json.loads(tool_message["content"])["error"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,expected_substring",
    [
        (CloudflareBlocked(), "temporarily blocking"),
        (MissingSearchData(), "Missing search parameters"),
        (LibraryError("boom"), "GasBuddy lookup failed"),
        (APIError("boom"), "GasBuddy lookup failed"),
        (GeocodingError("nowhere"), "nowhere"),
        (RuntimeError("boom"), "unexpectedly"),
    ],
)
async def test_a_tool_execution_error_is_reported_to_the_model_instead_of_crashing(
    error, expected_substring
):
    gasbuddy = FakeGasBuddyService(error=error)
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(_tool_call_body("find_nearby_gas_stations", {})),
            _FakeGroqResponse(_success_body("Sorry, something went wrong.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            location=(1.0, 2.0),
        )

    assert reply.content == "Sorry, something went wrong."
    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    assert expected_substring in json.loads(tool_message["content"])["error"]


@pytest.mark.asyncio
async def test_stops_calling_the_tool_after_the_round_cap_and_forces_a_final_answer():
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body("find_nearby_gas_stations", {}, call_id="call_1")
            ),
            _FakeGroqResponse(
                _tool_call_body("find_nearby_gas_stations", {}, call_id="call_2")
            ),
            _FakeGroqResponse(_success_body("Final answer.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            location=(1.0, 2.0),
        )

    assert reply.content == "Final answer."
    assert len(gasbuddy.calls) == 2

    third_call_payload = fake_post.call_args_list[2].kwargs["json"]
    assert "tools" not in third_call_payload


@pytest.mark.asyncio
async def test_sends_the_tool_definition_on_every_round_that_allows_it():
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(_tool_call_body("find_nearby_gas_stations", {})),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            location=(1.0, 2.0),
        )

    first_payload = fake_post.call_args_list[0].kwargs["json"]
    assert first_payload["tools"][0]["function"]["name"] == "find_nearby_gas_stations"


# --- Brand / distance / count filters ---------------------------------


@pytest.mark.asyncio
async def test_brand_filter_stops_after_page_one_when_found():
    page1 = [
        _make_station("Other", price=170.0, distance_miles=0.3),
        _make_station("Shell", price=158.9, distance_miles=0.6),
    ]
    # A next_cursor IS available, but should never be used — the brand was
    # already found in page 1.
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20")})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body("find_nearby_gas_stations", {"brand": "Shell"})
            ),
            _FakeGroqResponse(_success_body("Found a Shell.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find a Shell near me")],
            location=(1.0, 2.0),
        )

    assert reply.content == "Found a Shell."
    assert len(gasbuddy.calls) == 1
    sleep_mock.assert_not_called()

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert payload["station_count"] == 1
    assert payload["stations"][0]["name"] == "Shell"


@pytest.mark.asyncio
async def test_brand_filter_fetches_page_two_when_not_found_in_page_one():
    page1 = [_make_station("Esso", distance_miles=0.3)]
    page2 = [_make_station("Shell", price=158.9, distance_miles=1.2)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body("find_nearby_gas_stations", {"brand": "Shell"})
            ),
            _FakeGroqResponse(_success_body("Found a Shell further out.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find a Shell near me")],
            location=(1.0, 2.0),
        )

    assert reply.content == "Found a Shell further out."
    assert len(gasbuddy.calls) == 2
    assert gasbuddy.calls[1]["cursor"] == "20"
    sleep_mock.assert_awaited_once_with(chat_client.SECOND_PAGE_PAUSE_SECONDS)

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert payload["stations"][0]["name"] == "Shell"


@pytest.mark.asyncio
async def test_brand_filter_reports_a_clear_message_when_never_found():
    page1 = [_make_station("Esso", distance_miles=0.3)]
    page2 = [_make_station("Petro-Canada", distance_miles=1.2)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body("find_nearby_gas_stations", {"brand": "Shell"})
            ),
            _FakeGroqResponse(_success_body("No Shell nearby, sorry.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find a Shell near me")],
            location=(1.0, 2.0),
        )

    assert reply.content == "No Shell nearby, sorry."
    assert len(gasbuddy.calls) == 2
    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    error = json.loads(tool_message["content"])["error"]
    assert "Shell" in error
    assert "2" in error


@pytest.mark.asyncio
async def test_brand_tier_major_filters_out_independent_stations():
    page1 = [
        _make_station("Joe's Gas", price=155.0, distance_miles=0.3),
        _make_station("Shell", price=158.9, distance_miles=0.6),
    ]
    # A next_cursor IS available, but should never be used — enough major
    # matches (the default threshold of 1) were already found in page 1.
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20")})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"brand_tier": "major"}
                )
            ),
            _FakeGroqResponse(_success_body("Found a big name brand.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find a big name brand near me")],
            location=(1.0, 2.0),
        )

    assert reply.content == "Found a big name brand."
    assert len(gasbuddy.calls) == 1
    sleep_mock.assert_not_called()

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert [s["name"] for s in payload["stations"]] == ["Shell"]
    assert payload["filters_applied"]["brand_tier"] == "major"


@pytest.mark.asyncio
async def test_brand_tier_lesser_known_filters_out_major_chains():
    page1 = [
        _make_station("Shell", price=158.9, distance_miles=0.3),
        _make_station("Joe's Gas", price=155.0, distance_miles=0.6),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20")})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"brand_tier": "lesser_known"}
                )
            ),
            _FakeGroqResponse(_success_body("Found an independent station.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find an independent station near me")],
            location=(1.0, 2.0),
        )

    assert reply.content == "Found an independent station."
    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert [s["name"] for s in payload["stations"]] == ["Joe's Gas"]
    assert payload["filters_applied"]["brand_tier"] == "lesser_known"


@pytest.mark.asyncio
async def test_brand_tier_fetches_page_two_when_not_enough_major_matches_yet():
    page1 = [_make_station("Joe's Gas", distance_miles=0.3)]
    page2 = [_make_station("Shell", price=158.9, distance_miles=1.2)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"brand_tier": "major"}
                )
            ),
            _FakeGroqResponse(_success_body("Found a big name brand further out.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find a big name brand near me")],
            location=(1.0, 2.0),
        )

    assert reply.content == "Found a big name brand further out."
    assert len(gasbuddy.calls) == 2
    assert gasbuddy.calls[1]["cursor"] == "20"
    sleep_mock.assert_awaited_once_with(chat_client.SECOND_PAGE_PAUSE_SECONDS)

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert [s["name"] for s in payload["stations"]] == ["Shell"]


@pytest.mark.asyncio
async def test_brand_tier_reports_a_clear_message_when_none_match():
    page1 = [_make_station("Joe's Gas", distance_miles=0.3)]
    page2 = [_make_station("Anne's Fuel", distance_miles=1.2)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"brand_tier": "major"}
                )
            ),
            _FakeGroqResponse(_success_body("No big name brands nearby, sorry.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find a big name brand near me")],
            location=(1.0, 2.0),
        )

    assert reply.content == "No big name brands nearby, sorry."
    assert len(gasbuddy.calls) == 2
    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    error = json.loads(tool_message["content"])["error"]
    assert "major" in error
    assert "2" in error


@pytest.mark.asyncio
async def test_brand_tier_combined_with_fuel_grade_sorts_within_the_matching_tier_only():
    page1 = [
        _make_station("Joe's Gas", distance_miles=0.3, premium=150.0),
        _make_station("Esso", distance_miles=0.6, premium=198.9),
        _make_station("Pioneer", distance_miles=1.9, premium=195.9),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brand_tier": "major", "fuel_grade": "premium"},
                )
            ),
            _FakeGroqResponse(_success_body("Cheapest big name premium is Pioneer.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest big name premium near me?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    # Joe's Gas is cheaper but isn't a major brand, so it must be excluded
    # entirely — not merely sorted last.
    assert [s["name"] for s in payload["stations"]] == ["Pioneer", "Esso"]


@pytest.mark.asyncio
async def test_brands_filter_finds_all_requested_brands_in_a_single_call():
    page1 = [
        _make_station("Petro-Canada", price=164.9, distance_miles=0.3),
        _make_station("Esso", price=170.0, distance_miles=0.5),
        _make_station("Shell", price=158.9, distance_miles=0.6),
    ]
    # A next_cursor IS available, but should never be used — both
    # requested brands were already found in page 1.
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20")})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brands": ["Shell", "Petro-Canada"]},
                )
            ),
            _FakeGroqResponse(_success_body("Found both.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        reply = await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user",
                    content="find the nearest Shell and Petro-Canada stations",
                )
            ],
            location=(1.0, 2.0),
        )

    assert reply.content == "Found both."
    assert len(gasbuddy.calls) == 1
    sleep_mock.assert_not_called()

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert {s["name"] for s in payload["stations"]} == {"Petro-Canada", "Shell"}
    assert payload["filters_applied"]["brands"] == ["Shell", "Petro-Canada"]


@pytest.mark.asyncio
async def test_brands_filter_fetches_page_two_when_one_brand_missing_from_page_one():
    page1 = [_make_station("Shell", distance_miles=0.3)]
    page2 = [_make_station("Petro-Canada", distance_miles=1.2)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brands": ["Shell", "Petro-Canada"]},
                )
            ),
            _FakeGroqResponse(_success_body("Found both, one further out.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        reply = await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user",
                    content="find the nearest Shell and Petro-Canada stations",
                )
            ],
            location=(1.0, 2.0),
        )

    assert reply.content == "Found both, one further out."
    assert len(gasbuddy.calls) == 2
    assert gasbuddy.calls[1]["cursor"] == "20"
    sleep_mock.assert_awaited_once_with(chat_client.SECOND_PAGE_PAUSE_SECONDS)

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert {s["name"] for s in payload["stations"]} == {"Shell", "Petro-Canada"}


@pytest.mark.asyncio
async def test_brands_filter_reports_a_clear_message_when_none_match():
    page1 = [_make_station("Esso", distance_miles=0.3)]
    page2 = [_make_station("Ultramar", distance_miles=1.2)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brands": ["Shell", "Petro-Canada"]},
                )
            ),
            _FakeGroqResponse(_success_body("Neither is nearby, sorry.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user",
                    content="find the nearest Shell and Petro-Canada stations",
                )
            ],
            location=(1.0, 2.0),
        )

    assert reply.content == "Neither is nearby, sorry."
    assert len(gasbuddy.calls) == 2
    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    error = json.loads(tool_message["content"])["error"]
    assert "Shell" in error
    assert "Petro-Canada" in error
    assert "2" in error


@pytest.mark.asyncio
async def test_brands_combined_with_station_count_caps_the_combined_total():
    page1 = [
        _make_station("Shell-1", brand="Shell", distance_miles=0.3),
        _make_station("Shell-2", brand="Shell", distance_miles=0.5),
        _make_station("Petro-Canada", distance_miles=0.7),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20")})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brands": ["Shell", "Petro-Canada"], "station_count": 2},
                )
            ),
            _FakeGroqResponse(_success_body("Here are 2.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user",
                    content="find 2 Shell or Petro-Canada stations near me",
                )
            ],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert payload["station_count"] == 2
    assert [s["name"] for s in payload["stations"]] == ["Shell-1", "Shell-2"]


@pytest.mark.asyncio
async def test_brands_combined_with_fuel_grade_sorts_across_all_matching_brands():
    page1 = [
        _make_station("Shell", distance_miles=0.3, premium=198.9),
        _make_station("Esso", distance_miles=0.5, premium=150.0),
        _make_station("Petro-Canada", distance_miles=0.7, premium=170.0),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brands": ["Shell", "Petro-Canada"], "fuel_grade": "premium"},
                )
            ),
            _FakeGroqResponse(_success_body("Cheapest is Petro-Canada.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user",
                    content="cheapest premium at Shell or Petro-Canada near me?",
                )
            ],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    # Esso is cheapest but wasn't requested, so it must be excluded
    # entirely, not merely sorted last.
    assert [s["name"] for s in payload["stations"]] == ["Petro-Canada", "Shell"]


@pytest.mark.asyncio
async def test_brand_and_brands_both_given_brands_takes_precedence():
    page1 = [
        _make_station("Shell", distance_miles=0.3),
        _make_station("Petro-Canada", distance_miles=0.5),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20")})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brand": "Shell", "brands": ["Shell", "Petro-Canada"]},
                )
            ),
            _FakeGroqResponse(_success_body("Found both.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user",
                    content="find the nearest Shell and Petro-Canada stations",
                )
            ],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert {s["name"] for s in payload["stations"]} == {"Shell", "Petro-Canada"}


@pytest.mark.asyncio
async def test_invalid_brands_value_is_ignored_rather_than_crashing():
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brands": "Shell"},  # not a list — should be ignored
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            location=(1.0, 2.0),
        )

    assert reply.content == "ok"
    # Falls back to the plain (no-filter) path since "brands" wasn't a
    # valid list.
    assert gasbuddy.calls == [
        {
            "query": None,
            "lat": 1.0,
            "lon": 2.0,
            "limit": GASBUDDY_PAGE_SIZE,
            "cursor": None,
        }
    ]


@pytest.mark.asyncio
async def test_locations_finds_all_requested_places_in_a_single_call():
    gasbuddy = FakeGasBuddyService(
        by_query={
            "Toronto": [_make_station("Centex", price=159.9, distance_miles=1.0)],
            "Mississauga": [
                _make_station("Petro-Canada", price=152.2, distance_miles=0.5)
            ],
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"locations": ["Toronto", "Mississauga"]},
                )
            ),
            _FakeGroqResponse(_success_body("Mississauga is cheaper.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user",
                    content="is gas cheaper in Toronto or Mississauga?",
                )
            ],
            location=(1.0, 2.0),
        )

    assert reply.content == "Mississauga is cheaper."
    assert len(gasbuddy.calls) == 2

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert payload["searched_locations"] == ["Toronto", "Mississauga"]
    assert payload["results_by_location"]["Toronto"]["stations"][0]["name"] == "Centex"
    assert (
        payload["results_by_location"]["Mississauga"]["stations"][0]["name"]
        == "Petro-Canada"
    )
    # No fuel_grade was given, so there's no price basis to average over —
    # neither field should appear.
    assert "average_price" not in payload["results_by_location"]["Toronto"]
    assert "comparison_note" not in payload


@pytest.mark.asyncio
async def test_single_location_with_fuel_grade_has_no_average_price():
    gasbuddy = FakeGasBuddyService(
        by_query={
            "Toronto": [
                _make_station("Centex", distance_miles=1.0, premium=200.0),
                _make_station("Esso", distance_miles=1.5, premium=190.0),
            ],
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"location": "Toronto", "fuel_grade": "premium"},
                )
            ),
            _FakeGroqResponse(_success_body("Esso is cheapest in Toronto.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest premium in Toronto?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    # A single place has nothing to compare against, so average_price
    # (a locations-comparison concept) shouldn't appear on this shape at
    # all — it's a flat station list, not results_by_location.
    assert "results_by_location" not in payload
    assert "average_price" not in payload


@pytest.mark.asyncio
async def test_locations_combined_with_fuel_grade_and_count_caps_per_place():
    gasbuddy = FakeGasBuddyService(
        by_query={
            "Toronto": [
                _make_station("Centex", distance_miles=1.0, premium=200.0),
                _make_station("Esso", distance_miles=1.5, premium=190.0),
            ],
            "Mississauga": [
                _make_station("Petro-Canada", distance_miles=0.5, premium=180.0),
                _make_station("Shell", distance_miles=0.7, premium=175.0),
                _make_station("Husky", distance_miles=0.9, premium=185.0),
            ],
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {
                        "locations": ["Toronto", "Mississauga"],
                        "fuel_grade": "premium",
                        "station_count": 1,
                    },
                )
            ),
            _FakeGroqResponse(_success_body("Mississauga's Shell is cheapest.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user",
                    content="cheapest premium in Toronto vs Mississauga?",
                )
            ],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    # Each place is capped to 1 independently — Mississauga having more
    # cheap options doesn't shrink Toronto's own result.
    toronto = payload["results_by_location"]["Toronto"]
    mississauga = payload["results_by_location"]["Mississauga"]
    assert [s["name"] for s in toronto["stations"]] == ["Esso"]
    assert [s["name"] for s in mississauga["stations"]] == ["Shell"]
    assert payload["filters_applied"]["station_count_per_location"] == 1
    # average_price is computed over ALL matches (Centex+Esso, and
    # Petro-Canada+Shell+Husky) — NOT just the single station_count=1
    # entry each place got capped down to. If it were computed after the
    # cap, Toronto's average would equal Esso's own price (190.0) and
    # Mississauga's would equal Shell's (175.0), rather than these wider
    # averages.
    assert toronto["average_price"] == pytest.approx((200.0 + 190.0) / 2)
    assert mississauga["average_price"] == pytest.approx(
        (180.0 + 175.0 + 185.0) / 3
    )
    assert "comparison_note" in payload


@pytest.mark.asyncio
async def test_locations_with_fuel_grade_and_no_station_count_caps_display_to_default():
    # 8 priced stations in Toronto — no station_count given, so only the
    # cheapest FUEL_GRADE_DISPLAY_CAP (5) should be echoed back,
    # even though the average must still reflect all 8.
    toronto_stations = [
        _make_station(f"Station-{i}", distance_miles=float(i), premium=100.0 + i)
        for i in range(8)
    ]
    gasbuddy = FakeGasBuddyService(by_query={"Toronto": toronto_stations})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"locations": ["Toronto", "Mississauga"], "fuel_grade": "premium"},
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    gasbuddy._by_query["Mississauga"] = [_make_station("Only", premium=150.0)]
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user", content="cheapest premium in Toronto vs Mississauga?"
                )
            ],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    toronto = payload["results_by_location"]["Toronto"]
    assert toronto["station_count"] == chat_client.FUEL_GRADE_DISPLAY_CAP
    assert [s["name"] for s in toronto["stations"]] == [
        "Station-0",
        "Station-1",
        "Station-2",
        "Station-3",
        "Station-4",
    ]
    # The average must still reflect all 8 Toronto stations, not just the
    # 5 displayed — (100+101+...+107)/8.
    assert toronto["average_price"] == pytest.approx(sum(range(100, 108)) / 8)


@pytest.mark.asyncio
async def test_locations_with_fuel_grade_uses_compact_station_fields():
    gasbuddy = FakeGasBuddyService(
        by_query={
            "Toronto": [_make_station("Centex", premium=190.0)],
            "Mississauga": [_make_station("Shell", premium=180.0)],
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"locations": ["Toronto", "Mississauga"], "fuel_grade": "premium"},
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user", content="cheapest premium in Toronto vs Mississauga?"
                )
            ],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    station = payload["results_by_location"]["Toronto"]["stations"][0]
    # Only the requested grade's price, no other grade prices, no
    # star_rating, and no connected_brand since no brand filter was set.
    assert set(station.keys()) == {
        "name",
        "brand",
        "address",
        "distance_miles",
        "premium_price",
    }


@pytest.mark.asyncio
async def test_locations_with_fuel_grade_and_brand_keeps_connected_brand():
    gasbuddy = FakeGasBuddyService(
        by_query={
            "Toronto": [_make_station("Centex", brand="Esso", premium=190.0)],
            "Mississauga": [_make_station("Shell", premium=180.0)],
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {
                        "locations": ["Toronto", "Mississauga"],
                        "fuel_grade": "premium",
                        "brand": "Esso",
                    },
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest Esso premium, Toronto vs Mississauga?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    station = payload["results_by_location"]["Toronto"]["stations"][0]
    assert "connected_brand" in station


@pytest.mark.asyncio
async def test_locations_combined_with_brand_filters_within_each_place():
    gasbuddy = FakeGasBuddyService(
        by_query={
            "Toronto": [
                _make_station("Centex", distance_miles=1.0),
                _make_station("Shell", distance_miles=1.5),
            ],
            "Mississauga": [
                _make_station("Joe's Gas", distance_miles=0.5),
                _make_station("Shell", distance_miles=0.7),
            ],
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"locations": ["Toronto", "Mississauga"], "brand": "Shell"},
                )
            ),
            _FakeGroqResponse(_success_body("Found Shell in both.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user",
                    content="find Shell in Toronto and Mississauga",
                )
            ],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    toronto = payload["results_by_location"]["Toronto"]["stations"]
    mississauga = payload["results_by_location"]["Mississauga"]["stations"]
    assert [s["name"] for s in toronto] == ["Shell"]
    assert [s["name"] for s in mississauga] == ["Shell"]


@pytest.mark.asyncio
async def test_locations_reports_a_per_place_error_for_an_unresolvable_place():
    gasbuddy = FakeGasBuddyService(
        by_query={
            "Toronto": [_make_station("Centex", distance_miles=1.0)],
            "Notarealplacexyz": GeocodingError("Could not find that place."),
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"locations": ["Toronto", "Notarealplacexyz"]},
                )
            ),
            _FakeGroqResponse(_success_body("Found Toronto, not the other place.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service(gasbuddy).send(
            [
                ChatMessage(
                    role="user",
                    content="compare gas in Toronto and Notarealplacexyz",
                )
            ],
            location=(1.0, 2.0),
        )

    assert reply.content == "Found Toronto, not the other place."
    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    # Toronto still comes back fine even though the other place failed.
    assert payload["results_by_location"]["Toronto"]["stations"][0]["name"] == "Centex"
    assert "error" in payload["results_by_location"]["Notarealplacexyz"]


@pytest.mark.asyncio
async def test_location_and_locations_both_given_locations_takes_precedence():
    gasbuddy = FakeGasBuddyService(
        by_query={
            "Toronto": [_make_station("Centex", distance_miles=1.0)],
            "Mississauga": [_make_station("Petro-Canada", distance_miles=0.5)],
        }
    )
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {
                        "location": "Toronto",
                        "locations": ["Toronto", "Mississauga"],
                    },
                )
            ),
            _FakeGroqResponse(_success_body("Compared both.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="compare Toronto and Mississauga")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert set(payload["results_by_location"].keys()) == {"Toronto", "Mississauga"}


@pytest.mark.asyncio
async def test_invalid_locations_value_is_ignored_rather_than_crashing():
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"locations": "Toronto"},  # not a list — should be ignored
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            location=(1.0, 2.0),
        )

    assert reply.content == "ok"
    # Falls back to the device-location path since "locations" wasn't a
    # valid list and no single "location" was given either.
    assert gasbuddy.calls == [
        {
            "query": None,
            "lat": 1.0,
            "lon": 2.0,
            "limit": GASBUDDY_PAGE_SIZE,
            "cursor": None,
        }
    ]


@pytest.mark.asyncio
async def test_single_item_locations_list_behaves_like_a_single_location():
    gasbuddy = FakeGasBuddyService(by_query={"Toronto": [_make_station("Centex")]})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"locations": ["Toronto"]}
                )
            ),
            _FakeGroqResponse(_success_body("Found it in Toronto.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas in Toronto")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    # A single-item list takes the same shape as a plain `location` —
    # not the results_by_location multi-place shape.
    assert "results_by_location" not in payload
    assert payload["stations"][0]["name"] == "Centex"


@pytest.mark.asyncio
async def test_distance_filter_precedence_stops_after_page_one_even_without_a_brand_match():
    # Page 1's farthest station already exceeds the requested distance,
    # and the brand isn't found either — distance governs, so no second
    # page is fetched even though the brand hasn't been found yet.
    page1 = [
        _make_station("Esso", distance_miles=0.3),
        _make_station("Petro-Canada", distance_miles=3.0),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20")})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brand": "Shell", "max_distance_miles": 2},
                )
            ),
            _FakeGroqResponse(_success_body("No Shell within 2 miles.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="Shell within 2 miles?")],
            location=(1.0, 2.0),
        )

    assert reply.content == "No Shell within 2 miles."
    assert len(gasbuddy.calls) == 1
    sleep_mock.assert_not_called()


@pytest.mark.asyncio
async def test_distance_filter_fetches_page_two_even_after_finding_the_brand_if_still_within_radius():
    # Brand IS found in page 1, but page 1 hasn't yet reached the
    # requested distance boundary — distance still governs, so page 2 is
    # fetched anyway (the user-confirmed precedence rule).
    page1 = [_make_station("Shell", distance_miles=0.5)]
    page2 = [_make_station("Shell", price=155.0, distance_miles=1.8)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brand": "Shell", "max_distance_miles": 2},
                )
            ),
            _FakeGroqResponse(_success_body("Found two Shell stations within 2 miles.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="Shell within 2 miles?")],
            location=(1.0, 2.0),
        )

    assert reply.content == "Found two Shell stations within 2 miles."
    assert len(gasbuddy.calls) == 2
    sleep_mock.assert_awaited_once()

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert payload["station_count"] == 2


@pytest.mark.asyncio
async def test_distance_only_stops_after_page_one_when_it_already_exceeds_the_radius():
    page1 = [
        _make_station("Esso", distance_miles=0.3),
        _make_station("Petro-Canada", distance_miles=3.0),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20")})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"max_distance_miles": 2}
                )
            ),
            _FakeGroqResponse(_success_body("Only Esso is within 2 miles.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="stations within 2 miles?")],
            location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 1
    sleep_mock.assert_not_called()


@pytest.mark.asyncio
async def test_distance_only_fetches_page_two_when_page_one_doesnt_reach_the_radius():
    page1 = [_make_station("Esso", distance_miles=0.3)]
    page2 = [_make_station("Petro-Canada", distance_miles=1.5)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"max_distance_miles": 2}
                )
            ),
            _FakeGroqResponse(_success_body("Two stations within 2 miles.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="stations within 2 miles?")],
            location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 2
    sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_standalone_station_count_is_ignored_and_returns_the_full_page():
    # A standalone station_count (no brand, no distance) — whether the
    # user actually asked for a number or the model picked one on its own
    # — no longer caps anything: the tool always returns its full fetched
    # page so a "cheapest"/"best" style question has real data to answer
    # from, rather than an arbitrarily small slice.
    page1 = [_make_station(f"Station{i}", distance_miles=0.1 * i) for i in range(5)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20")})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body("find_nearby_gas_stations", {"station_count": 3})
            ),
            _FakeGroqResponse(_success_body("Here are the stations.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="show me 3 stations")],
            location=(1.0, 2.0),
        )

    # A standalone count never escalates to a second page either — it's
    # not treated as a filter at all, so it routes through the same plain,
    # single-page path as no arguments.
    assert len(gasbuddy.calls) == 1
    assert gasbuddy.calls[0]["limit"] == GASBUDDY_PAGE_SIZE
    sleep_mock.assert_not_called()

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    # All 5 fetched stations, NOT capped down to the requested 3.
    assert payload["station_count"] == 5
    assert "filters_applied" not in payload


@pytest.mark.asyncio
async def test_count_and_brand_stops_after_page_one_once_enough_matches():
    page1 = [
        _make_station("Shell", distance_miles=0.3),
        _make_station("Shell", distance_miles=0.5),
        _make_station("Esso", distance_miles=0.4),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20")})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brand": "Shell", "station_count": 2},
                )
            ),
            _FakeGroqResponse(_success_body("Two Shell stations.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find 2 Shell stations")],
            location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 1
    sleep_mock.assert_not_called()


@pytest.mark.asyncio
async def test_count_and_brand_fetches_page_two_when_not_enough_matches_yet():
    page1 = [_make_station("Shell", distance_miles=0.3)]
    page2 = [
        _make_station("Shell", distance_miles=1.5),
        _make_station("Esso", distance_miles=1.6),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brand": "Shell", "station_count": 2},
                )
            ),
            _FakeGroqResponse(_success_body("Two Shell stations.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find 2 Shell stations")],
            location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 2
    sleep_mock.assert_awaited_once()

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert payload["station_count"] == 2
    assert all(s["name"] == "Shell" for s in payload["stations"])


@pytest.mark.asyncio
async def test_count_and_brand_returns_fewer_when_not_enough_exist_even_after_two_pages():
    page1 = [_make_station("Shell", distance_miles=0.3)]
    page2 = [_make_station("Esso", distance_miles=1.5)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brand": "Shell", "station_count": 5},
                )
            ),
            _FakeGroqResponse(_success_body("Only 1 Shell station.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find 5 Shell stations")],
            location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 2
    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert payload["station_count"] == 1
    assert "error" not in payload


@pytest.mark.asyncio
async def test_count_and_distance_follows_the_distance_rule_not_an_independent_count_stop():
    # Page 1 already has >= station_count matches within the distance, but
    # page 1's farthest station hasn't yet exceeded the radius — distance
    # alone governs, so page 2 is still fetched (count never independently
    # short-circuits).
    page1 = [
        _make_station("A", distance_miles=0.3),
        _make_station("B", distance_miles=0.5),
    ]
    page2 = [_make_station("C", distance_miles=1.5)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"max_distance_miles": 2, "station_count": 2},
                )
            ),
            _FakeGroqResponse(_success_body("Two stations within 2 miles.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find 2 stations within 2 miles")],
            location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 2
    sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_brand_distance_count_all_three_together():
    page1 = [
        _make_station("Shell", distance_miles=0.3),
        _make_station("Esso", distance_miles=0.4),
    ]
    page2 = [_make_station("Shell", distance_miles=1.5)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {
                        "brand": "Shell",
                        "max_distance_miles": 2,
                        "station_count": 2,
                    },
                )
            ),
            _FakeGroqResponse(_success_body("Two Shell stations within 2 miles.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find 2 Shell within 2 miles")],
            location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 2
    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert payload["station_count"] == 2
    assert all(s["name"] == "Shell" for s in payload["stations"])


@pytest.mark.asyncio
async def test_no_stations_within_distance_reports_a_clear_message():
    page1 = [_make_station("Esso", distance_miles=3.0)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"max_distance_miles": 1}
                )
            ),
            _FakeGroqResponse(_success_body("Nothing within 1 mile.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="anything within 1 mile?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    error = json.loads(tool_message["content"])["error"]
    assert "1" in error and "mile" in error.lower()


@pytest.mark.asyncio
async def test_no_stations_near_location_at_all_reports_a_distinct_message():
    gasbuddy = FakeGasBuddyService(pages={None: ([], None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body("find_nearby_gas_stations", {"brand": "Shell"})
            ),
            _FakeGroqResponse(_success_body("No stations found at all.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="find a Shell")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    error = json.loads(tool_message["content"])["error"]
    assert error == "No gas stations were found near that location at all."


@pytest.mark.asyncio
async def test_invalid_filter_values_are_ignored_rather_than_crashing():
    gasbuddy = FakeGasBuddyService(stations=[_make_station()])
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"station_count": 0, "max_distance_miles": -5},
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            location=(1.0, 2.0),
        )

    assert reply.content == "ok"
    # Falls back to the plain (no-filter) path since every filter value
    # given was invalid.
    assert gasbuddy.calls == [
        {
            "query": None,
            "lat": 1.0,
            "lon": 2.0,
            "limit": GASBUDDY_PAGE_SIZE,
            "cursor": None,
        }
    ]


# --- fuel_grade (deterministic price sorting) --------------------------


@pytest.mark.asyncio
async def test_fuel_grade_single_location_includes_explicit_cheapest_field():
    page1 = [
        _make_station("A", distance_miles=0.3, premium=205.0),
        _make_station("B", distance_miles=0.5, premium=195.0),
        _make_station("C", distance_miles=0.7, premium=199.0),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"fuel_grade": "premium"}
                )
            ),
            _FakeGroqResponse(_success_body("B is cheapest.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest premium near me?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    # The code identifies the cheapest explicitly, not just via list order.
    assert payload["cheapest"]["name"] == "B"
    assert payload["cheapest"]["premium_price"] == "195.0¢"
    assert "cheapest_note" in payload


@pytest.mark.asyncio
async def test_fuel_grade_single_location_caps_display_when_no_station_count():
    # 8 priced stations, no station_count given — only FUEL_GRADE_DISPLAY_CAP
    # (5) should be echoed back, cheapest-first, but the explicit `cheapest`
    # field must still correctly name the true cheapest of all 8.
    page1 = [
        _make_station(f"Station-{i}", distance_miles=float(i), premium=100.0 + i)
        for i in range(8)
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"fuel_grade": "premium"}
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest premium near me?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert payload["station_count"] == chat_client.FUEL_GRADE_DISPLAY_CAP
    assert payload["cheapest"]["name"] == "Station-0"


@pytest.mark.asyncio
async def test_fuel_grade_single_location_uses_compact_station_fields():
    page1 = [_make_station("A", premium=190.0)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"fuel_grade": "premium"}
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest premium near me?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    station = payload["stations"][0]
    assert set(station.keys()) == {
        "name",
        "brand",
        "address",
        "distance_miles",
        "premium_price",
    }
    assert set(payload["cheapest"].keys()) == set(station.keys())


@pytest.mark.asyncio
async def test_fuel_grade_single_location_with_explicit_count_not_further_capped():
    page1 = [
        _make_station("A", distance_miles=0.3, premium=205.0),
        _make_station("B", distance_miles=0.5, premium=195.0),
        _make_station("C", distance_miles=0.7, premium=199.0),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"fuel_grade": "premium", "station_count": 2},
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="2 cheapest premium near me?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    # Explicit count of 2 is respected exactly — not shrunk further, nor
    # expanded up to FUEL_GRADE_DISPLAY_CAP (5).
    assert [s["name"] for s in payload["stations"]] == ["B", "C"]
    assert payload["cheapest"]["name"] == "B"


@pytest.mark.asyncio
async def test_fuel_grade_sorts_stations_by_that_grades_price_ascending():
    # Deliberately fetched/returned in a non-price order (GasBuddy's own
    # nearest-first order), to prove the tool re-sorts by premium price
    # rather than relaying GasBuddy's order.
    page1 = [
        _make_station("A", distance_miles=0.3, premium=205.0),
        _make_station("B", distance_miles=0.5, premium=195.0),
        _make_station("C", distance_miles=0.7, premium=199.0),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"fuel_grade": "premium"}
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest premium near me?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert [s["name"] for s in payload["stations"]] == ["B", "C", "A"]
    assert "sorted_by" in payload
    assert payload["filters_applied"]["fuel_grade"] == "premium"


@pytest.mark.asyncio
async def test_fuel_grade_drops_stations_missing_that_grades_price():
    page1 = [
        _make_station("HasPremium", premium=199.0),
        _make_station("NoPremium", premium=None),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"fuel_grade": "premium"}
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest premium near me?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert [s["name"] for s in payload["stations"]] == ["HasPremium"]


@pytest.mark.asyncio
async def test_fuel_grade_reports_a_clear_message_when_none_have_that_price():
    page1 = [_make_station("A", premium=None), _make_station("B", premium=None)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"fuel_grade": "premium"}
                )
            ),
            _FakeGroqResponse(_success_body("No premium prices reported.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        reply = await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest premium near me?")],
            location=(1.0, 2.0),
        )

    assert reply.content == "No premium prices reported."
    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    error = json.loads(tool_message["content"])["error"]
    assert "premium" in error


@pytest.mark.asyncio
async def test_fuel_grade_and_count_caps_after_sorting_not_before():
    # Reproduces the exact reported bug: nearest-first order would put a
    # more-expensive station ahead of a cheaper one that's simply farther
    # away. A naive "take the first N, then sort" would drop the genuinely
    # cheaper station; capping AFTER sorting must not.
    page1 = [
        _make_station("Esso", distance_miles=0.5, premium=198.9),
        _make_station("Pioneer", distance_miles=1.9, premium=195.9),
        _make_station("Petro-Canada-1", distance_miles=2.0, premium=197.9),
        _make_station("Petro-Canada-2", distance_miles=2.1, premium=198.7),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"fuel_grade": "premium", "station_count": 3},
                )
            ),
            _FakeGroqResponse(_success_body("Top 3 cheapest premium.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="top 3 cheapest premium near me?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    # Pioneer (195.9), Petro-Canada-1 (197.9), Petro-Canada-2 (198.7) —
    # NOT Esso (198.9), which is more expensive than Petro-Canada-2.
    assert [s["name"] for s in payload["stations"]] == [
        "Pioneer",
        "Petro-Canada-1",
        "Petro-Canada-2",
    ]


@pytest.mark.asyncio
async def test_fuel_grade_combined_with_brand_sorts_within_the_matching_brand_only():
    page1 = [
        _make_station("Shell", distance_miles=0.3, premium=210.0),
        _make_station("Esso", distance_miles=0.4, premium=190.0),
        _make_station("Shell", distance_miles=0.6, premium=200.0),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {"brand": "Shell", "fuel_grade": "premium"},
                )
            ),
            _FakeGroqResponse(_success_body("Cheapest Shell premium.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="cheapest Shell premium near me?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    # Only the two Shells, sorted cheapest-first — Esso excluded by brand.
    assert [s["name"] for s in payload["stations"]] == ["Shell", "Shell"]
    assert [s["premium_price"] for s in payload["stations"]] == ["200.0¢", "210.0¢"]


@pytest.mark.asyncio
async def test_fuel_grade_still_fetches_page_two_to_gather_enough_brand_matches_before_sorting():
    # station_count's role in the early-stop decision (via
    # _needs_second_page) must still use the real requested count, even
    # though the final cap is deferred until after sorting — otherwise a
    # cheaper matching-brand station on page 2 could be missed entirely.
    page1 = [_make_station("Shell", distance_miles=0.3, premium=210.0)]
    page2 = [_make_station("Shell", distance_miles=1.5, premium=190.0)]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, "20"), "20": (page2, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations",
                    {
                        "brand": "Shell",
                        "fuel_grade": "premium",
                        "station_count": 2,
                    },
                )
            ),
            _FakeGroqResponse(_success_body("Two cheapest Shell premium.")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ) as sleep_mock:
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="2 cheapest Shell premium near me?")],
            location=(1.0, 2.0),
        )

    assert len(gasbuddy.calls) == 2
    sleep_mock.assert_awaited_once()
    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    assert [s["premium_price"] for s in payload["stations"]] == ["190.0¢", "210.0¢"]


@pytest.mark.asyncio
async def test_invalid_fuel_grade_value_is_ignored():
    page1 = [
        _make_station("A", distance_miles=0.3, premium=210.0),
        _make_station("B", distance_miles=0.1, premium=190.0),
    ]
    gasbuddy = FakeGasBuddyService(pages={None: (page1, None)})
    fake_post = AsyncMock(
        side_effect=[
            _FakeGroqResponse(
                _tool_call_body(
                    "find_nearby_gas_stations", {"fuel_grade": "cheapest"}
                )
            ),
            _FakeGroqResponse(_success_body("ok")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post), patch(
        "app.services.chat_client.asyncio.sleep", new=AsyncMock()
    ):
        await _configured_service(gasbuddy).send(
            [ChatMessage(role="user", content="gas near me?")],
            location=(1.0, 2.0),
        )

    second_call_messages = fake_post.call_args_list[1].kwargs["json"]["messages"]
    tool_message = next(m for m in second_call_messages if m["role"] == "tool")
    payload = json.loads(tool_message["content"])
    # Falls back to unsorted (GasBuddy's own nearest-first) order, not an
    # error — an invalid grade string is treated as if unset.
    assert [s["name"] for s in payload["stations"]] == ["A", "B"]
    assert "sorted_by" not in payload
