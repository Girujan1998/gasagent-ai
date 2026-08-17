from unittest.mock import AsyncMock, patch

import pytest

from app.services.afdc_client import KM_TO_MILES, AfdcService, SEARCH_RADIUS_MILES


class _FakeAfdcResponse:
    """Stands in for httpx.Response — just enough of its interface for
    AfdcService.search_nearest_ev_stations, without a real network call."""

    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _raw_station(**overrides):
    raw = {
        "id": 12345,
        "station_name": "Downtown Charging Hub",
        "ev_network": "ChargePoint Network",
        "ev_network_web": "https://www.chargepoint.com",
        "street_address": "1 Main St",
        "city": "Springfield",
        "state": "IL",
        "latitude": 41.85,
        "longitude": -87.65,
        "distance": 1.2,
        "station_phone": "888-758-4389",
        "access_days_time": "24 hours daily",
        "access_code": "public",
        "status_code": "E",
        "ev_level1_evse_num": None,
        "ev_level2_evse_num": 2,
        "ev_dc_fast_num": None,
        "ev_connector_types": ["J1772"],
        "date_last_confirmed": "2026-08-16",
    }
    raw.update(overrides)
    return raw


@pytest.mark.asyncio
async def test_search_maps_afdc_fields_onto_ev_station():
    fake_response = _FakeAfdcResponse(
        {"fuel_stations": [_raw_station()], "total_results": 1}
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        result = await AfdcService().search_nearest_ev_stations(
            lat=41.85, lon=-87.65
        )

    assert result.total_results == 1
    assert result.lat == 41.85
    assert result.lon == -87.65
    assert len(result.stations) == 1

    station = result.stations[0]
    assert station.station_id == "12345"
    assert station.name == "Downtown Charging Hub"
    assert station.network == "ChargePoint Network"
    assert station.network_web == "https://www.chargepoint.com"
    assert station.address == "1 Main St, Springfield, IL"
    assert station.distance_miles == 1.2
    assert station.phone == "888-758-4389"
    assert station.access_hours == "24 hours daily"
    assert station.access_code == "public"
    assert station.status_code == "E"
    assert station.level1_count is None
    assert station.level2_count == 2
    assert station.dc_fast_count is None
    assert station.connector_types == ["J1772"]
    assert station.date_last_confirmed == "2026-08-16"


@pytest.mark.asyncio
async def test_search_combines_street_city_and_state_into_one_address_line():
    fake_response = _FakeAfdcResponse(
        {
            "fuel_stations": [
                _raw_station(street_address="55 Dickson Street", city="Cambridge", state="ON")
            ],
            "total_results": 1,
        }
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        result = await AfdcService().search_nearest_ev_stations(
            lat=43.3601, lon=-80.31269
        )

    assert result.stations[0].address == "55 Dickson Street, Cambridge, ON"


@pytest.mark.asyncio
async def test_search_omits_missing_address_parts_instead_of_leaving_blank_commas():
    fake_response = _FakeAfdcResponse(
        {
            "fuel_stations": [
                _raw_station(street_address="55 Dickson Street", city=None, state="ON")
            ],
            "total_results": 1,
        }
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        result = await AfdcService().search_nearest_ev_stations(
            lat=43.3601, lon=-80.31269
        )

    assert result.stations[0].address == "55 Dickson Street, ON"


@pytest.mark.asyncio
async def test_search_leaves_address_null_when_no_address_parts_are_reported():
    fake_response = _FakeAfdcResponse(
        {
            "fuel_stations": [
                _raw_station(street_address=None, city=None, state=None)
            ],
            "total_results": 1,
        }
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        result = await AfdcService().search_nearest_ev_stations(
            lat=43.3601, lon=-80.31269
        )

    assert result.stations[0].address is None


@pytest.mark.asyncio
async def test_search_falls_back_to_returned_count_when_total_results_missing():
    # Some AFDC responses may omit total_results outright — falling back to
    # len(stations) keeps "load more" from looping forever on a bad signal.
    fake_response = _FakeAfdcResponse({"fuel_stations": [_raw_station()]})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        result = await AfdcService().search_nearest_ev_stations(
            lat=41.85, lon=-87.65
        )

    assert result.total_results == 1


@pytest.mark.asyncio
async def test_search_handles_no_stations_found():
    fake_response = _FakeAfdcResponse({"fuel_stations": [], "total_results": 0})
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        result = await AfdcService().search_nearest_ev_stations(
            lat=0.0, lon=0.0
        )

    assert result.stations == []
    assert result.total_results == 0


@pytest.mark.asyncio
async def test_search_sends_expected_request_params():
    fake_response = _FakeAfdcResponse({"fuel_stations": [], "total_results": 0})
    fake_get = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.get", new=fake_get):
        await AfdcService().search_nearest_ev_stations(lat=41.85, lon=-87.65, limit=15)

    _, kwargs = fake_get.call_args
    params = kwargs["params"]
    assert params["latitude"] == 41.85
    assert params["longitude"] == -87.65
    assert params["radius"] == SEARCH_RADIUS_MILES
    assert params["fuel_type"] == "ELEC"
    assert params["status"] == "E"
    assert params["access"] == "public"
    assert params["limit"] == 15
    # Without this, NREL defaults to US-only and silently returns zero
    # results for a Canadian search location (e.g. Cambridge, ON) even
    # though the app supports Canadian postal codes elsewhere.
    assert params["country"] == "US,CA"


@pytest.mark.asyncio
async def test_search_uses_default_radius_when_radius_km_is_not_given():
    fake_response = _FakeAfdcResponse({"fuel_stations": [], "total_results": 0})
    fake_get = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.get", new=fake_get):
        await AfdcService().search_nearest_ev_stations(lat=41.85, lon=-87.65)

    _, kwargs = fake_get.call_args
    assert kwargs["params"]["radius"] == SEARCH_RADIUS_MILES


@pytest.mark.asyncio
async def test_search_converts_radius_km_to_miles_for_the_nrel_request():
    # Map view searches a fixed 30km radius — NREL's own `radius` param is
    # in miles, so this must be converted, not passed through as-is.
    fake_response = _FakeAfdcResponse({"fuel_stations": [], "total_results": 0})
    fake_get = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.get", new=fake_get):
        await AfdcService().search_nearest_ev_stations(
            lat=41.85, lon=-87.65, radius_km=30
        )

    _, kwargs = fake_get.call_args
    assert kwargs["params"]["radius"] == pytest.approx(30 * KM_TO_MILES)


@pytest.mark.asyncio
async def test_search_geocodes_when_only_query_is_given():
    fake_results = [{"latitude": 41.85, "longitude": -87.65}]

    class _FakeGeocodeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": fake_results}

    async def fake_get(self, url, params=None):
        if "geocoding" in url:
            return _FakeGeocodeResponse()
        return _FakeAfdcResponse({"fuel_stations": [], "total_results": 0})

    with patch("httpx.AsyncClient.get", new=fake_get):
        result = await AfdcService().search_nearest_ev_stations(query="60614")

    assert result.lat == 41.85
    assert result.lon == -87.65
