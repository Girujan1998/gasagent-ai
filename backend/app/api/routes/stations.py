import asyncio
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from py_gasbuddy import APIError, CloudflareBlocked, LibraryError, MissingSearchData

from app.config import Settings, get_settings
from app.models.schemas import FlareSolverrWarmupResponse, StationSearchResponse
from app.services.gasbuddy_client import GasBuddyService, get_gasbuddy_service
from app.services.geocoding import GeocodingError

router = APIRouter(prefix="/stations", tags=["stations"])

# A restart clears whatever's accumulated in FlareSolverr's long-running
# Chrome process (confirmed live: a manual restart-then-search succeeded
# where an already-awake container kept failing) — but the new container
# takes real time to come back up and get past its own next Cloudflare
# challenge, so only wait this long when a restart was actually
# triggered. When it wasn't (not configured, or the restart call itself
# failed) there's nothing new to wait for — a single ping is enough,
# same as before this feature existed.
RESTART_POLL_BUDGET_SECONDS = 25.0
RESTART_POLL_INTERVAL_SECONDS = 3.0


@router.get("/search", response_model=StationSearchResponse)
async def search_stations(
    query: str | None = Query(
        None, description="City name or postal code to search near"
    ),
    lat: float | None = Query(None, description="Latitude of the current location"),
    lon: float | None = Query(None, description="Longitude of the current location"),
    limit: int = Query(10, ge=1, le=20),
    cursor: str | None = Query(
        None,
        description=(
            "Pagination cursor from a previous response's next_cursor. "
            "When set, `lat`/`lon` (from that same response) must be passed "
            "instead of `query`, so paging doesn't depend on re-geocoding."
        ),
    ),
    service: GasBuddyService = Depends(get_gasbuddy_service),
) -> StationSearchResponse:
    """Return the nearest gas stations for a city, postal code, or GPS location."""
    if not query and (lat is None or lon is None):
        raise HTTPException(
            status_code=400,
            detail="Provide either `query` (city or postal code) or both `lat` and `lon`.",
        )

    try:
        result = await service.search_nearest_stations(
            query=query, lat=lat, lon=lon, limit=limit, cursor=cursor
        )
    except GeocodingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingSearchData as exc:
        raise HTTPException(
            status_code=400, detail="Missing search parameters."
        ) from exc
    except CloudflareBlocked as exc:
        raise HTTPException(
            status_code=502,
            detail="GasBuddy is temporarily blocking automated requests. Try again shortly.",
        ) from exc
    except (LibraryError, APIError) as exc:
        raise HTTPException(
            status_code=502, detail=f"GasBuddy lookup failed: {exc}"
        ) from exc

    return StationSearchResponse(
        results=result.stations,
        next_cursor=result.next_cursor,
        lat=result.lat,
        lon=result.lon,
    )


async def _restart_flaresolverr_service(settings: Settings) -> bool:
    """Best-effort triggers a restart of FlareSolverr's own Render service
    (not a rebuild — reapplies the same deploy, just with a fresh
    process). Returns whether the restart was actually accepted, so the
    caller knows whether it's worth waiting for a new container to come
    back up versus just pinging the one that's already running.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"https://api.render.com/v1/services/{settings.flaresolverr_service_id}/restart",
                headers={"Authorization": f"Bearer {settings.render_api_key}"},
            )
        # print rather than `logging` — see gemini_client.py's own
        # comment on why; this call is otherwise silent (best-effort by
        # design), so without this there's no way to tell a bad
        # key/service ID or a Render-side rejection apart from the
        # restart simply not helping.
        print(
            f"[flaresolverr] restart request -> {response.status_code} "
            f"{response.text[:200]!r}"
        )
        return response.status_code == 200
    except httpx.HTTPError as exc:
        print(f"[flaresolverr] restart request failed: {exc!r}")
        return False


async def _wait_for_flaresolverr(base_url: str, poll_budget_seconds: float) -> bool:
    deadline = time.monotonic() + poll_budget_seconds
    async with httpx.AsyncClient(timeout=20.0) as client:
        while True:
            try:
                response = await client.get(base_url)
                if response.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(RESTART_POLL_INTERVAL_SECONDS)


@router.post("/warmup-container", response_model=FlareSolverrWarmupResponse)
async def warmup_flaresolverr_container(
    settings: Settings = Depends(get_settings),
) -> FlareSolverrWarmupResponse:
    """Wakes FlareSolverr's own container (Render free tier sleeps it
    after 15 min idle) without calling GasBuddy at all.

    Deliberately does NOT run a real gas search to prime a CSRF token —
    an earlier version of this endpoint did exactly that, but it fired
    unconditionally on every app launch regardless of whether the user
    ever searched for gas that session, adding real load against
    GasBuddy's own request-rate limit for zero benefit on EV/Chat-only
    sessions. This only removes the container's cold-start delay; the
    user's first real gas search still pays for the actual Cloudflare
    challenge-solve itself, since that step can only happen by actually
    contacting GasBuddy.

    When `render_api_key`/`flaresolverr_service_id` are configured, also
    triggers a restart of FlareSolverr's own Render service on every
    launch — confirmed live that a fresh restart (not just an
    already-awake container) can succeed where the same container kept
    failing, plausibly because its browser-automation process
    accumulates memory/process cruft across many solves. Falls back to
    a single lightweight ping when unconfigured, matching this
    endpoint's original behavior.

    Never raises — an unreachable/still-sleeping container is an
    expected, retryable state during startup, not an error.
    """
    solver_url = settings.gasbuddy_solver_url
    if not solver_url:
        # No solver configured on this deploy (e.g. local dev) — nothing
        # to wake, so there's nothing blocking a gas search either.
        return FlareSolverrWarmupResponse(awake=True)

    base_url = solver_url.removesuffix("/v1").removesuffix("/v1/")

    restarted = False
    if settings.render_api_key and settings.flaresolverr_service_id:
        restarted = await _restart_flaresolverr_service(settings)

    poll_budget = RESTART_POLL_BUDGET_SECONDS if restarted else 0.0
    awake = await _wait_for_flaresolverr(base_url, poll_budget)
    return FlareSolverrWarmupResponse(awake=awake)
