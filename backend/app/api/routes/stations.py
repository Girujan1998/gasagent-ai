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

# A fresh redeploy clears whatever's accumulated in FlareSolverr's
# long-running Chrome process AND gets a new container from scratch
# (plausibly a new egress IP, matching this session's IP-reputation
# theory) — confirmed live that this succeeds where a same-container
# *restart* (tried first, see git history) did not. Only worth waiting
# this long when a redeploy was actually triggered; when it wasn't (not
# configured, or the trigger call itself failed) there's nothing new
# coming up, so a single ping is enough — same as before this feature
# existed.
REDEPLOY_POLL_BUDGET_SECONDS = 45.0
REDEPLOY_POLL_INTERVAL_SECONDS = 3.0


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


async def _redeploy_flaresolverr_service(settings: Settings) -> bool:
    """Best-effort triggers a fresh redeploy of FlareSolverr's own Render
    service (repulls/restarts the container from scratch — confirmed
    live that this succeeds where a same-container *restart* alone did
    not). Returns whether the deploy was actually accepted, so the
    caller knows whether it's worth waiting for a new container to come
    up versus just pinging the one that's already running.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"https://api.render.com/v1/services/{settings.flaresolverr_service_id}/deploys",
                headers={
                    "Authorization": f"Bearer {settings.render_api_key}",
                    "Content-Type": "application/json",
                },
                json={},
            )
        # print rather than `logging` — see gemini_client.py's own
        # comment on why; this call is otherwise silent (best-effort by
        # design), so without this there's no way to tell a bad
        # key/service ID or a Render-side rejection apart from the
        # redeploy simply not helping.
        print(
            f"[flaresolverr] deploy trigger -> {response.status_code} "
            f"{response.text[:200]!r}"
        )
        return response.status_code in (201, 202)
    except httpx.HTTPError as exc:
        print(f"[flaresolverr] deploy trigger failed: {exc!r}")
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
            await asyncio.sleep(REDEPLOY_POLL_INTERVAL_SECONDS)


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
    triggers a fresh redeploy of FlareSolverr's own Render service on
    every launch — confirmed live that a same-container *restart* alone
    was NOT enough, but a full redeploy (fresh container, plausibly a
    new egress IP) succeeded where the same long-running container kept
    failing. Falls back to a single lightweight ping when unconfigured,
    matching this endpoint's original behavior.

    Never raises — an unreachable/still-sleeping container is an
    expected, retryable state during startup, not an error.
    """
    solver_url = settings.gasbuddy_solver_url
    if not solver_url:
        # No solver configured on this deploy (e.g. local dev) — nothing
        # to wake, so there's nothing blocking a gas search either.
        return FlareSolverrWarmupResponse(awake=True)

    base_url = solver_url.removesuffix("/v1").removesuffix("/v1/")

    redeployed = False
    if settings.render_api_key and settings.flaresolverr_service_id:
        redeployed = await _redeploy_flaresolverr_service(settings)

    poll_budget = REDEPLOY_POLL_BUDGET_SECONDS if redeployed else 0.0
    awake = await _wait_for_flaresolverr(base_url, poll_budget)
    return FlareSolverrWarmupResponse(awake=awake)
