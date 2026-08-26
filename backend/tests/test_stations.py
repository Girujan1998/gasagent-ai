from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app.api.routes.stations import get_gasbuddy_service
from app.config import Settings, get_settings
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


class _FakeFlareSolverrResponse:
    """Stands in for httpx.Response — status_code and (for the Render
    restart call's own diagnostic logging) text are read by
    warmup_flaresolverr_container."""

    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_warmup_container_reports_awake_with_no_solver_configured_and_makes_no_call():
    app.dependency_overrides[get_settings] = lambda: Settings(gasbuddy_solver_url="")
    fake_get = AsyncMock()
    try:
        with patch("httpx.AsyncClient.get", new=fake_get):
            response = client.post("/api/v1/stations/warmup-container")
    finally:
        app.dependency_overrides.clear()

    # Nothing configured means nothing to wake — and critically, no
    # network call at all, so this never adds load against GasBuddy.
    assert response.status_code == 200
    assert response.json() == {"awake": True}
    fake_get.assert_not_called()


def test_warmup_container_strips_the_v1_suffix_and_reports_awake_on_200():
    app.dependency_overrides[get_settings] = lambda: Settings(
        gasbuddy_solver_url="https://flaresolverr-example.onrender.com/v1"
    )
    fake_get = AsyncMock(return_value=_FakeFlareSolverrResponse(200))
    try:
        with patch("httpx.AsyncClient.get", new=fake_get):
            response = client.post("/api/v1/stations/warmup-container")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"awake": True}
    # Pings FlareSolverr's own lightweight health check, not the /v1
    # solve endpoint — this must never resemble a real GasBuddy request.
    fake_get.assert_called_once_with("https://flaresolverr-example.onrender.com")


def test_warmup_container_reports_not_awake_on_a_non_200_response():
    app.dependency_overrides[get_settings] = lambda: Settings(
        gasbuddy_solver_url="https://flaresolverr-example.onrender.com/v1"
    )
    try:
        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(return_value=_FakeFlareSolverrResponse(503)),
        ):
            response = client.post("/api/v1/stations/warmup-container")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"awake": False}


def test_warmup_container_reports_not_awake_without_raising_when_unreachable():
    app.dependency_overrides[get_settings] = lambda: Settings(
        gasbuddy_solver_url="https://flaresolverr-example.onrender.com/v1"
    )
    try:
        with patch(
            "httpx.AsyncClient.get",
            new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            response = client.post("/api/v1/stations/warmup-container")
    finally:
        app.dependency_overrides.clear()

    # A still-sleeping/unreachable container is expected and retryable,
    # never surfaced as an HTTP error.
    assert response.status_code == 200
    assert response.json() == {"awake": False}


# --- Render redeploy-on-launch (optional, requires both settings) --------


def test_warmup_container_does_not_call_render_when_credentials_are_unset():
    app.dependency_overrides[get_settings] = lambda: Settings(
        gasbuddy_solver_url="https://flaresolverr-example.onrender.com/v1"
    )
    fake_post = AsyncMock()
    try:
        with (
            patch("httpx.AsyncClient.post", new=fake_post),
            patch(
                "httpx.AsyncClient.get",
                new=AsyncMock(return_value=_FakeFlareSolverrResponse(200)),
            ),
        ):
            response = client.post("/api/v1/stations/warmup-container")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"awake": True}
    fake_post.assert_not_called()


def test_warmup_container_redeploys_the_render_service_when_configured():
    app.dependency_overrides[get_settings] = lambda: Settings(
        gasbuddy_solver_url="https://flaresolverr-example.onrender.com/v1",
        render_api_key="rnd_test_key",
        flaresolverr_service_id="srv-abc123",
    )
    fake_post = AsyncMock(return_value=_FakeFlareSolverrResponse(201))
    fake_get = AsyncMock(return_value=_FakeFlareSolverrResponse(200))
    try:
        with (
            patch("httpx.AsyncClient.post", new=fake_post),
            patch("httpx.AsyncClient.get", new=fake_get),
        ):
            response = client.post("/api/v1/stations/warmup-container")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"awake": True}
    fake_post.assert_called_once_with(
        "https://api.render.com/v1/services/srv-abc123/deploys",
        headers={
            "Authorization": "Bearer rnd_test_key",
            "Content-Type": "application/json",
        },
        json={},
    )
    # Confirms it's a redeploy, not a same-container restart — a bare
    # restart was tried first (see git history) and confirmed live NOT
    # to be enough, unlike a fresh redeploy.
    assert "deploys" in fake_post.call_args.args[0]


def test_warmup_container_falls_back_to_a_single_ping_when_render_deploy_trigger_fails():
    # The deploy-trigger call itself failing (bad key, wrong service ID,
    # Render rate-limiting) means nothing new is coming up — waiting the
    # long post-redeploy poll budget would only slow down every app
    # launch for no benefit, so this must behave exactly like the
    # unconfigured case.
    app.dependency_overrides[get_settings] = lambda: Settings(
        gasbuddy_solver_url="https://flaresolverr-example.onrender.com/v1",
        render_api_key="rnd_test_key",
        flaresolverr_service_id="srv-abc123",
    )
    fake_post = AsyncMock(return_value=_FakeFlareSolverrResponse(401))
    fake_get = AsyncMock(return_value=_FakeFlareSolverrResponse(200))
    try:
        with (
            patch("httpx.AsyncClient.post", new=fake_post),
            patch("httpx.AsyncClient.get", new=fake_get),
        ):
            response = client.post("/api/v1/stations/warmup-container")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"awake": True}
    fake_get.assert_called_once()


def test_warmup_container_polls_after_a_successful_redeploy_until_the_new_container_answers():
    # A freshly redeployed container isn't back up instantly — this must
    # keep polling (not give up after one failed attempt) within its
    # post-redeploy budget. asyncio.sleep is patched to a no-op so the
    # test doesn't actually wait out the real poll interval.
    app.dependency_overrides[get_settings] = lambda: Settings(
        gasbuddy_solver_url="https://flaresolverr-example.onrender.com/v1",
        render_api_key="rnd_test_key",
        flaresolverr_service_id="srv-abc123",
    )
    fake_post = AsyncMock(return_value=_FakeFlareSolverrResponse(202))
    fake_get = AsyncMock(
        side_effect=[_FakeFlareSolverrResponse(503), _FakeFlareSolverrResponse(200)]
    )
    try:
        with (
            patch("httpx.AsyncClient.post", new=fake_post),
            patch("httpx.AsyncClient.get", new=fake_get),
            patch("app.api.routes.stations.asyncio.sleep", new=AsyncMock()),
        ):
            response = client.post("/api/v1/stations/warmup-container")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"awake": True}
    assert fake_get.call_count == 2


def test_warmup_container_reports_awake_without_raising_when_render_deploy_trigger_errors():
    app.dependency_overrides[get_settings] = lambda: Settings(
        gasbuddy_solver_url="https://flaresolverr-example.onrender.com/v1",
        render_api_key="rnd_test_key",
        flaresolverr_service_id="srv-abc123",
    )
    fake_post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    fake_get = AsyncMock(return_value=_FakeFlareSolverrResponse(200))
    try:
        with (
            patch("httpx.AsyncClient.post", new=fake_post),
            patch("httpx.AsyncClient.get", new=fake_get),
        ):
            response = client.post("/api/v1/stations/warmup-container")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"awake": True}
