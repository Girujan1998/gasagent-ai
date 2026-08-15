from fastapi.testclient import TestClient

from app.api.routes.stations import get_gasbuddy_service
from app.main import app
from app.models.schemas import FuelPrice, GasStation
from app.services.gasbuddy_client import StationSearchResult

client = TestClient(app)


def make_station(station_id: str) -> GasStation:
    return GasStation(
        station_id=station_id,
        name="Test Station",
        brand="Costco",
        brand_logo_url="https://images.gasbuddy.io/b/38.png",
        address="1 Main St, Springfield, IL",
        latitude=41.85,
        longitude=-87.65,
        distance_miles=1.2,
        regular=FuelPrice(
            price=3.19,
            formatted_price="$3.19",
            last_updated="2026-08-14T12:00:00Z",
        ),
        midgrade=FuelPrice(
            price=3.49,
            formatted_price="$3.49",
            last_updated="2026-08-14T12:00:00Z",
        ),
        premium=FuelPrice(
            price=3.79,
            formatted_price="$3.79",
            last_updated="2026-08-14T12:00:00Z",
        ),
        diesel=FuelPrice(
            price=3.99,
            formatted_price="$3.99",
            last_updated="2026-08-14T12:00:00Z",
        ),
        star_rating=4.5,
        ratings_count=120,
    )


class FakeGasBuddyService:
    def __init__(self, next_cursor: str | None = None):
        self._next_cursor = next_cursor
        self.last_call_kwargs: dict | None = None

    async def search_nearest_stations(
        self, *, query=None, lat=None, lon=None, limit=10, cursor=None
    ):
        self.last_call_kwargs = {
            "query": query,
            "lat": lat,
            "lon": lon,
            "limit": limit,
            "cursor": cursor,
        }
        return StationSearchResult(
            stations=[make_station("123")],
            next_cursor=self._next_cursor,
            lat=lat if lat is not None else 41.85,
            lon=lon if lon is not None else -87.65,
        )


def test_search_requires_query_or_coordinates():
    response = client.get("/api/v1/stations/search")
    assert response.status_code == 400


def test_search_returns_stations():
    app.dependency_overrides[get_gasbuddy_service] = lambda: FakeGasBuddyService()
    try:
        response = client.get("/api/v1/stations/search", params={"query": "60614"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    results = body["results"]
    assert len(results) == 1

    station = results[0]
    assert station["brand"] == "Costco"
    assert station["brand_logo_url"] == "https://images.gasbuddy.io/b/38.png"
    assert station["latitude"] == 41.85
    assert station["longitude"] == -87.65
    assert station["distance_miles"] == 1.2
    assert station["regular"]["price"] == 3.19
    assert station["midgrade"]["price"] == 3.49
    assert station["premium"]["price"] == 3.79
    assert station["diesel"]["price"] == 3.99
    assert station["star_rating"] == 4.5
    assert station["ratings_count"] == 120
    assert body["next_cursor"] is None
    assert body["lat"] == 41.85
    assert body["lon"] == -87.65


def test_search_returns_next_cursor_when_more_results_exist():
    app.dependency_overrides[get_gasbuddy_service] = lambda: FakeGasBuddyService(
        next_cursor="20"
    )
    try:
        response = client.get("/api/v1/stations/search", params={"query": "60614"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["next_cursor"] == "20"


def test_search_forwards_cursor_and_coordinates_for_next_page():
    fake_service = FakeGasBuddyService()
    app.dependency_overrides[get_gasbuddy_service] = lambda: fake_service
    try:
        response = client.get(
            "/api/v1/stations/search",
            params={"lat": 41.85, "lon": -87.65, "cursor": "20", "limit": 10},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake_service.last_call_kwargs == {
        "query": None,
        "lat": 41.85,
        "lon": -87.65,
        "limit": 10,
        "cursor": "20",
    }
