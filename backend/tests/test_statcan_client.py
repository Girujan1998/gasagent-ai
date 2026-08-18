from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services import statcan_client
from app.services.statcan_client import StatCanService


@pytest.fixture(autouse=True)
def _clear_statcan_cache():
    # Module-level cache (see statcan_client.py's own comment) — reset
    # between tests so one test's fetch doesn't leak into the next.
    statcan_client._cache = None
    yield
    statcan_client._cache = None


class _FakeStatCanResponse:
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
    fake_response = _FakeStatCanResponse(
        _payload(169.4, 175.5, "2026-06-01", "2026-07-01")
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        trend = await StatCanService().latest_trend()

    assert trend is not None
    assert trend.previous_value == 169.4
    assert trend.latest_value == 175.5
    assert trend.latest_period == "2026-07-01"
    assert trend.period_days == 30


@pytest.mark.asyncio
async def test_sends_the_confirmed_gasoline_vector_id():
    fake_response = _FakeStatCanResponse(
        _payload(169.4, 175.5, "2026-06-01", "2026-07-01")
    )
    fake_post = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.post", new=fake_post):
        await StatCanService().latest_trend()

    _, kwargs = fake_post.call_args
    assert kwargs["json"] == [
        {"vectorId": statcan_client.GASOLINE_VECTOR_ID, "latestN": 2}
    ]


@pytest.mark.asyncio
async def test_returns_none_when_fewer_than_two_points_are_returned():
    fake_response = _FakeStatCanResponse(
        [{"status": "SUCCESS", "object": {"vectorDataPoint": [{"refPer": "2026-07-01", "value": 175.5}]}}]
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        trend = await StatCanService().latest_trend()

    assert trend is None


@pytest.mark.asyncio
async def test_returns_none_on_a_malformed_response():
    fake_response = _FakeStatCanResponse({"unexpected": "shape"})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=fake_response)):
        trend = await StatCanService().latest_trend()

    assert trend is None


@pytest.mark.asyncio
async def test_returns_none_when_the_request_fails():
    fake_post = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.AsyncClient.post", new=fake_post):
        trend = await StatCanService().latest_trend()

    assert trend is None


@pytest.mark.asyncio
async def test_reuses_the_cached_trend_without_a_second_request():
    fake_response = _FakeStatCanResponse(
        _payload(169.4, 175.5, "2026-06-01", "2026-07-01")
    )
    fake_post = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.post", new=fake_post):
        service = StatCanService()
        await service.latest_trend()
        await service.latest_trend()

    assert fake_post.call_count == 1
