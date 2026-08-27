from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services import country_lookup
from app.services.country_lookup import CountryLookupError, CountryLookupService


@pytest.fixture(autouse=True)
def _clear_country_cache():
    # Module-level cache (see country_lookup.py's own comment on why) — has
    # to be reset between tests or one test's lookup would leak into the
    # next as a false cache hit.
    country_lookup._cache.clear()
    yield
    country_lookup._cache.clear()


class _FakeReverseGeocodeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


@pytest.mark.asyncio
async def test_resolves_a_lowercase_country_code():
    fake_response = _FakeReverseGeocodeResponse(
        {"address": {"country": "Canada", "country_code": "ca"}}
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        code = await CountryLookupService().resolve_country_code(43.36, -80.31)

    assert code == "ca"


@pytest.mark.asyncio
async def test_uppercases_are_normalized_to_lowercase():
    fake_response = _FakeReverseGeocodeResponse(
        {"address": {"country": "United States", "country_code": "US"}}
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        code = await CountryLookupService().resolve_country_code(41.85, -87.65)

    assert code == "us"


@pytest.mark.asyncio
async def test_returns_none_when_the_response_has_no_country():
    fake_response = _FakeReverseGeocodeResponse({"address": {}})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        code = await CountryLookupService().resolve_country_code(0, 0)

    assert code is None


@pytest.mark.asyncio
async def test_sends_a_real_identifying_user_agent():
    # This reverse-geocoding service's usage policy requires this — a missing/generic one risks
    # the shared public instance blocking requests entirely.
    fake_response = _FakeReverseGeocodeResponse(
        {"address": {"country_code": "ca"}}
    )
    fake_get = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.get", new=fake_get):
        await CountryLookupService().resolve_country_code(43.36, -80.31)

    _, kwargs = fake_get.call_args
    assert "GasAgentAI" in kwargs["headers"]["User-Agent"]


@pytest.mark.asyncio
async def test_reuses_the_cached_result_for_a_nearby_point_without_a_second_request():
    fake_response = _FakeReverseGeocodeResponse({"address": {"country_code": "ca"}})
    fake_get = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.get", new=fake_get):
        service = CountryLookupService()
        await service.resolve_country_code(43.36, -80.31)
        # A different point, but within the same coarse grid cell.
        await service.resolve_country_code(43.37, -80.32)

    assert fake_get.call_count == 1


@pytest.mark.asyncio
async def test_a_failed_request_raises_country_lookup_error():
    fake_get = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(CountryLookupError):
            await CountryLookupService().resolve_country_code(43.36, -80.31)
