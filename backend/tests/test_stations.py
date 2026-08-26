from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from py_gasbuddy import CloudflareBlocked, LibraryError

import app.api.routes.stations as stations_module
from app.api.routes.stations import get_gasbuddy_service
from app.config import Settings, get_settings
from app.main import app
from app.models.schemas import FuelPrice, GasStation
from app.services.gasbuddy_client import StationSearchResult

client = TestClient(app)


def reset_flaresolverr_redeploy_cooldown():
    # The cooldown is process-global (deliberately — see its own module
    # comment), so tests that trigger it must reset it, or an earlier
    # test's trigger would suppress a later test's expected trigger.
    stations_module._last_flaresolverr_redeploy_trigger = 0.0


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


class FailingGasBuddyService:
    """Always raises, on every call — for cases where the retry is
    expected to fail too, or isn't expected to happen at all."""

    def __init__(self, exc: Exception):
        self._exc = exc
        self.call_count = 0

    async def search_nearest_stations(self, **_kwargs):
        self.call_count += 1
        raise self._exc


class FailingThenSucceedingGasBuddyService:
    """Raises on the first call, succeeds on every call after — models a
    search that gets blocked, then works once FlareSolverr has been
    redeployed."""

    def __init__(self, exc: Exception):
        self._exc = exc
        self.call_count = 0

    async def search_nearest_stations(self, *, lat=None, lon=None, **_kwargs):
        self.call_count += 1
        if self.call_count == 1:
            raise self._exc
        return StationSearchResult(
            stations=[make_station("123")],
            next_cursor=None,
            lat=lat if lat is not None else 41.85,
            lon=lon if lon is not None else -87.65,
        )


# --- FlareSolverr redeploy triggered reactively by a blocked search -------
#
# An earlier version of this eagerly redeployed FlareSolverr on every app
# launch instead (see git history) — moved here so it only happens when
# actually needed. A later version returned the block error immediately
# after firing off the redeploy (see git history again) — now it instead
# waits for the redeploy and retries once inline, so the caller only
# ever sees the original block as extra loading time unless the retry
# also fails.


def test_search_retries_once_and_succeeds_after_a_flaresolverr_redeploy():
    reset_flaresolverr_redeploy_cooldown()
    fake_service = FailingThenSucceedingGasBuddyService(CloudflareBlocked("Missing Token"))
    app.dependency_overrides[get_gasbuddy_service] = lambda: fake_service
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
            response = client.get("/api/v1/stations/search", params={"query": "60614"})
    finally:
        app.dependency_overrides.clear()

    # A successful retry looks exactly like an ordinary successful
    # search to the caller — no trace of the block in between.
    assert response.status_code == 200
    assert len(response.json()["results"]) == 1
    assert fake_service.call_count == 2
    fake_post.assert_called_once_with(
        "https://api.render.com/v1/services/srv-abc123/deploys",
        headers={
            "Authorization": "Bearer rnd_test_key",
            "Content-Type": "application/json",
        },
        json={},
    )
    fake_get.assert_called()


def test_search_shows_the_generic_blocked_message_when_redeploy_is_not_configured():
    reset_flaresolverr_redeploy_cooldown()
    fake_service = FailingGasBuddyService(CloudflareBlocked("Missing Token"))
    app.dependency_overrides[get_gasbuddy_service] = lambda: fake_service
    app.dependency_overrides[get_settings] = lambda: Settings()
    fake_post = AsyncMock()
    try:
        with patch("httpx.AsyncClient.post", new=fake_post):
            response = client.get("/api/v1/stations/search", params={"query": "60614"})
    finally:
        app.dependency_overrides.clear()

    # Nothing configured to redeploy means no retry is attempted either
    # — same single-call, immediate-error behavior as before this
    # feature existed.
    assert response.status_code == 502
    assert (
        response.json()["detail"]
        == "GasBuddy is temporarily blocking automated requests. Try again shortly."
    )
    assert fake_service.call_count == 1
    fake_post.assert_not_called()


def test_search_reports_failed_to_obtain_results_when_the_retry_is_also_blocked():
    reset_flaresolverr_redeploy_cooldown()
    fake_service = FailingGasBuddyService(CloudflareBlocked("Missing Token"))
    app.dependency_overrides[get_gasbuddy_service] = lambda: fake_service
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
            response = client.get("/api/v1/stations/search", params={"query": "60614"})
    finally:
        app.dependency_overrides.clear()

    # Exactly one redeploy + one retry, never a loop — a still-failing
    # retry gets its own distinct message, not the original block error.
    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to obtain gas results."
    assert fake_service.call_count == 2
    fake_post.assert_called_once()


def test_search_does_not_retrigger_a_redeploy_within_the_cooldown_window():
    # A burst of failing requests while a redeploy is already in flight
    # must not each fire their own redeploy — but each still waits and
    # retries once on its own.
    reset_flaresolverr_redeploy_cooldown()
    app.dependency_overrides[get_gasbuddy_service] = lambda: FailingGasBuddyService(
        CloudflareBlocked("Missing Token")
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        render_api_key="rnd_test_key", flaresolverr_service_id="srv-abc123"
    )
    fake_post = AsyncMock(return_value=_FakeFlareSolverrResponse(201))
    try:
        with patch("httpx.AsyncClient.post", new=fake_post):
            client.get("/api/v1/stations/search", params={"query": "60614"})
            client.get("/api/v1/stations/search", params={"query": "60614"})
    finally:
        app.dependency_overrides.clear()

    fake_post.assert_called_once()


def test_search_reports_failed_to_obtain_results_when_the_redeploy_trigger_itself_fails():
    reset_flaresolverr_redeploy_cooldown()
    app.dependency_overrides[get_gasbuddy_service] = lambda: FailingGasBuddyService(
        CloudflareBlocked("Missing Token")
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        render_api_key="rnd_test_key", flaresolverr_service_id="srv-abc123"
    )
    try:
        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            response = client.get("/api/v1/stations/search", params={"query": "60614"})
    finally:
        app.dependency_overrides.clear()

    # The redeploy trigger failing is still best-effort — the retry
    # still happens (against the same, presumably-still-blocked
    # container), so this still ends in the "retry also failed" message
    # rather than raising an unhandled error.
    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to obtain gas results."


def test_search_does_not_trigger_a_redeploy_for_a_non_cloudflare_error():
    reset_flaresolverr_redeploy_cooldown()
    fake_service = FailingGasBuddyService(LibraryError("something else went wrong"))
    app.dependency_overrides[get_gasbuddy_service] = lambda: fake_service
    app.dependency_overrides[get_settings] = lambda: Settings(
        render_api_key="rnd_test_key", flaresolverr_service_id="srv-abc123"
    )
    fake_post = AsyncMock()
    try:
        with patch("httpx.AsyncClient.post", new=fake_post):
            response = client.get("/api/v1/stations/search", params={"query": "60614"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert fake_service.call_count == 1
    fake_post.assert_not_called()


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


def test_warmup_container_never_triggers_a_render_redeploy_even_when_configured():
    # Redeploying takes real time (45s+ for the new container to come
    # up) — that cost is only worth paying reactively, when a real
    # search actually gets blocked (see the redeploy tests above), never
    # unconditionally on every app launch.
    app.dependency_overrides[get_settings] = lambda: Settings(
        gasbuddy_solver_url="https://flaresolverr-example.onrender.com/v1",
        render_api_key="rnd_test_key",
        flaresolverr_service_id="srv-abc123",
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
