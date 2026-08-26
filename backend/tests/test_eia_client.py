from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services import eia_client
from app.services.eia_client import EiaService


@pytest.fixture(autouse=True)
def _clear_eia_cache():
    eia_client._cache = None
    yield
    eia_client._cache = None


class _FakeEiaResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self._status_code = status_code

    def raise_for_status(self):
        if self._status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=httpx.Request("GET", eia_client.EIA_URL), response=self  # type: ignore[arg-type]
            )

    def json(self):
        return self._body


def _payload(latest_value, previous_value, latest_period, previous_period):
    # Requested sorted descending by period, so the latest point comes first.
    return {
        "response": {
            "data": [
                {"period": latest_period, "value": latest_value},
                {"period": previous_period, "value": previous_value},
            ]
        }
    }


@pytest.mark.asyncio
async def test_computes_the_trend_from_the_two_latest_weekly_points():
    fake_response = _FakeEiaResponse(
        _payload(3.85, 3.79, "2026-08-11", "2026-08-04")
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        trend = await EiaService().latest_trend()

    assert trend is not None
    assert trend.latest_value == 3.85
    assert trend.previous_value == 3.79
    assert trend.latest_period == "2026-08-11"
    assert trend.period_days == 7


@pytest.mark.asyncio
async def test_sends_the_confirmed_route_and_facets():
    fake_response = _FakeEiaResponse(
        _payload(3.85, 3.79, "2026-08-11", "2026-08-04")
    )
    fake_get = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.get", new=fake_get):
        await EiaService().latest_trend()

    args, kwargs = fake_get.call_args
    assert args[0] == eia_client.EIA_URL
    params = kwargs["params"]
    assert params["facets[duoarea][]"] == "NUS"
    assert params["facets[product][]"] == "EPMR"
    assert params["frequency"] == "weekly"


@pytest.mark.asyncio
async def test_returns_none_when_eia_rejects_the_request():
    # Covers both a missing and an invalid API key — EIA responds with 403
    # either way (confirmed live for the missing-key case), and both
    # should degrade to "no trend available" rather than raise.
    fake_response = _FakeEiaResponse({}, status_code=403)
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        trend = await EiaService().latest_trend()

    assert trend is None


@pytest.mark.asyncio
async def test_returns_none_on_a_malformed_response():
    fake_response = _FakeEiaResponse({"response": {"data": []}})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        trend = await EiaService().latest_trend()

    assert trend is None


@pytest.mark.asyncio
async def test_returns_none_when_the_request_fails():
    fake_get = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.AsyncClient.get", new=fake_get):
        trend = await EiaService().latest_trend()

    assert trend is None


@pytest.mark.asyncio
async def test_reuses_the_cached_trend_without_a_second_request():
    fake_response = _FakeEiaResponse(
        _payload(3.85, 3.79, "2026-08-11", "2026-08-04")
    )
    fake_get = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.get", new=fake_get):
        service = EiaService()
        await service.latest_trend()
        await service.latest_trend()

    assert fake_get.call_count == 1


@pytest.mark.asyncio
async def test_retries_on_the_next_call_after_a_failure_instead_of_caching_it():
    # A transient failure must not get cached for the full
    # CACHE_TTL_SECONDS window — every US forecast would otherwise
    # silently see "no trend" for hours after one bad request, with no
    # way for it to recover on its own before the cache expired.
    fake_get = AsyncMock(
        side_effect=[
            httpx.ConnectError("boom"),
            _FakeEiaResponse(_payload(3.85, 3.79, "2026-08-11", "2026-08-04")),
        ]
    )
    with patch("httpx.AsyncClient.get", new=fake_get):
        service = EiaService()
        first = await service.latest_trend()
        second = await service.latest_trend()

    assert first is None
    assert second is not None
    assert fake_get.call_count == 2
