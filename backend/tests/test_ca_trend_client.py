from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services import ca_trend_client
from app.services.ca_trend_client import CaTrendService


@pytest.fixture(autouse=True)
def _clear_ca_trend_cache():
    # Module-level cache (see ca_trend_client.py's own comment) — reset
    # between tests so one test's fetch doesn't leak into the next.
    ca_trend_client._cache = None
    yield
    ca_trend_client._cache = None


class _FakeCaTrendResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _payload(previous_value, latest_value, previous_period, latest_period):
    return [
        {
            "status": "SUCCESS",
            "object": {
                "vectorDataPoint": [
                    {"refPer": previous_period, "value": previous_value},
                    {"refPer": latest_period, "value": latest_value},
                ]
            },
        }
    ]


@pytest.mark.asyncio
async def test_computes_the_trend_from_the_two_latest_data_points():
    fake_response = _FakeCaTrendResponse(
        _payload(169.4, 175.5, "2026-06-01", "2026-07-01")
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        trend = await CaTrendService().latest_trend()

    assert trend is not None
    assert trend.previous_value == 169.4
    assert trend.latest_value == 175.5
    assert trend.latest_period == "2026-07-01"
    assert trend.period_days == 30


@pytest.mark.asyncio
async def test_sends_the_confirmed_gasoline_vector_id():
    fake_response = _FakeCaTrendResponse(
        _payload(169.4, 175.5, "2026-06-01", "2026-07-01")
    )
    fake_post = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.post", new=fake_post):
        await CaTrendService().latest_trend()

    _, kwargs = fake_post.call_args
    assert kwargs["json"] == [
        {"vectorId": ca_trend_client.GASOLINE_VECTOR_ID, "latestN": 2}
    ]


@pytest.mark.asyncio
async def test_returns_none_when_fewer_than_two_points_are_returned():
    fake_response = _FakeCaTrendResponse(
        [{"status": "SUCCESS", "object": {"vectorDataPoint": [{"refPer": "2026-07-01", "value": 175.5}]}}]
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        trend = await CaTrendService().latest_trend()

    assert trend is None


@pytest.mark.asyncio
async def test_returns_none_on_a_malformed_response():
    fake_response = _FakeCaTrendResponse({"unexpected": "shape"})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        trend = await CaTrendService().latest_trend()

    assert trend is None


@pytest.mark.asyncio
async def test_returns_none_when_the_request_fails():
    fake_post = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.AsyncClient.post", new=fake_post):
        trend = await CaTrendService().latest_trend()

    assert trend is None


@pytest.mark.asyncio
async def test_reuses_the_cached_trend_without_a_second_request():
    fake_response = _FakeCaTrendResponse(
        _payload(169.4, 175.5, "2026-06-01", "2026-07-01")
    )
    fake_post = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.post", new=fake_post):
        service = CaTrendService()
        await service.latest_trend()
        await service.latest_trend()

    assert fake_post.call_count == 1


@pytest.mark.asyncio
async def test_retries_on_the_next_call_after_a_failure_instead_of_caching_it():
    # A transient failure must not get cached for the full
    # CACHE_TTL_SECONDS window — every Canadian forecast would otherwise
    # silently see "no trend" for hours after one bad request, with no
    # way for it to recover on its own before the cache expired.
    fake_post = AsyncMock(
        side_effect=[
            httpx.ConnectError("boom"),
            _FakeCaTrendResponse(_payload(169.4, 175.5, "2026-06-01", "2026-07-01")),
        ]
    )
    with patch("httpx.AsyncClient.post", new=fake_post):
        service = CaTrendService()
        first = await service.latest_trend()
        second = await service.latest_trend()

    assert first is None
    assert second is not None
    assert fake_post.call_count == 2
