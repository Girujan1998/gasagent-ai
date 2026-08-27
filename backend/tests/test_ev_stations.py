from fastapi.testclient import TestClient

from app.api.routes.ev_stations import get_ev_search_service
from app.main import app
from app.models.schemas import EvStation
from app.services.ev_search import EvStationSearchResult

client = TestClient(app)


def make_ev_station(station_id: str) -> EvStation:
    return EvStation(
        station_id=station_id,
        name="Test Charging Station",
        network="ChargePoint Network",
        network_web="https://www.chargepoint.com",
        address="1 Main St, Springfield, IL",
        latitude=41.85,
        longitude=-87.65,
        distance_miles=1.2,
        phone="888-758-4389",
        access_hours="24 hours daily",
        access_code="public",
        status_code="E",
        level1_count=None,
        level2_count=2,
        dc_fast_count=None,
        connector_types=["J1772"],
        date_last_confirmed="2026-08-16T00:00:00.000Z",
    )


class FakeEvSearchService:
    def __init__(self, total_results: int = 1):
        self._total_results = total_results
        self.last_call_kwargs: dict | None = None

    async def search_nearest_ev_stations(
        self, *, query=None, lat=None, lon=None, limit=20, radius_km=None
    ):
        self.last_call_kwargs = {
            "query": query,
            "lat": lat,
            "lon": lon,
            "limit": limit,
            "radius_km": radius_km,
        }
        return EvStationSearchResult(
            stations=[make_ev_station("123")],
            total_results=self._total_results,
            lat=lat if lat is not None else 41.85,
            lon=lon if lon is not None else -87.65,
        )


def test_search_requires_query_or_coordinates():
    response = client.get("/api/v1/ev-stations/search")
    assert response.status_code == 400


def test_search_returns_ev_stations():
    app.dependency_overrides[get_ev_search_service] = lambda: FakeEvSearchService()
    try:
        response = client.get("/api/v1/ev-stations/search", params={"query": "60614"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    results = body["results"]
    assert len(results) == 1

    station = results[0]
    assert station["network"] == "ChargePoint Network"
    assert station["network_web"] == "https://www.chargepoint.com"
    assert station["latitude"] == 41.85
    assert station["longitude"] == -87.65
    assert station["distance_miles"] == 1.2
    assert station["phone"] == "888-758-4389"
    assert station["access_hours"] == "24 hours daily"
    assert station["access_code"] == "public"
    assert station["level2_count"] == 2
    assert station["connector_types"] == ["J1772"]
    assert body["total_results"] == 1
    assert body["lat"] == 41.85
    assert body["lon"] == -87.65


def test_search_reports_total_results_separately_from_returned_results():
    # Signals to the client that "load more" would actually fetch more —
    # 5 total exist even though this page only returned 1.
    app.dependency_overrides[get_ev_search_service] = lambda: FakeEvSearchService(
        total_results=5
    )
    try:
        response = client.get("/api/v1/ev-stations/search", params={"query": "60614"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["total_results"] == 5


def test_search_forwards_coordinates_and_limit():
    fake_service = FakeEvSearchService()
    app.dependency_overrides[get_ev_search_service] = lambda: fake_service
    try:
        response = client.get(
            "/api/v1/ev-stations/search",
            params={"lat": 41.85, "lon": -87.65, "limit": 30},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake_service.last_call_kwargs == {
        "query": None,
        "lat": 41.85,
        "lon": -87.65,
        "limit": 30,
        "radius_km": None,
    }


def test_search_forwards_radius_km():
    fake_service = FakeEvSearchService()
    app.dependency_overrides[get_ev_search_service] = lambda: fake_service
    try:
        response = client.get(
            "/api/v1/ev-stations/search",
            params={"lat": 41.85, "lon": -87.65, "limit": 200, "radius_km": 30},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake_service.last_call_kwargs["radius_km"] == 30
    assert fake_service.last_call_kwargs["limit"] == 200


def test_search_rejects_a_limit_above_the_directory_sources_own_maximum():
    response = client.get(
        "/api/v1/ev-stations/search",
        params={"lat": 41.85, "lon": -87.65, "limit": 201},
    )
    assert response.status_code == 422


def test_search_rejects_a_negative_or_zero_radius():
    response = client.get(
        "/api/v1/ev-stations/search",
        params={"lat": 41.85, "lon": -87.65, "radius_km": 0},
    )
    assert response.status_code == 422
