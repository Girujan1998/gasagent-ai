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

# Redeploying FlareSolverr (not just restarting it — confirmed live a
# same-container restart alone wasn't enough) gets it a genuinely fresh
# container, plausibly a new egress IP, clearing whatever Cloudflare-
# facing state a stale container had accumulated. Triggered reactively,
# only when a real gas search actually hits CloudflareBlocked — an
# earlier version of this eagerly redeployed on every app launch
# instead, adding a 45s+ poll wait to every cold open regardless of
# whether the user ever searched for gas that session. This cooldown
# stops a burst of failing requests, while one redeploy is already in
# flight, from queuing up repeat redeploys behind it. The poll budget
# below is how long a *blocked search* itself waits for the new
# container to answer before retrying — the container coming up is
# quick (~20s observed live); the retry's own Cloudflare challenge-solve
# is the slower, unbounded part, governed separately by
# `gasbuddy_timeout_ms`.
FLARESOLVERR_REDEPLOY_COOLDOWN_SECONDS = 90.0
REDEPLOY_POLL_BUDGET_SECONDS = 45.0
REDEPLOY_POLL_INTERVAL_SECONDS = 3.0

_last_flaresolverr_redeploy_trigger = 0.0


async def _trigger_flaresolverr_redeploy(settings: Settings) -> None:
    """Best-effort triggers a fresh redeploy of FlareSolverr's own Render
    service (not a same-container restart — confirmed live that a
    restart alone doesn't help).
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
    except httpx.HTTPError as exc:
        print(f"[flaresolverr] deploy trigger failed: {exc!r}")


async def _redeploy_flaresolverr_if_not_recently_triggered(settings: Settings) -> None:
    global _last_flaresolverr_redeploy_trigger
    if not (settings.render_api_key and settings.flaresolverr_service_id):
        return

    now = time.monotonic()
    if now - _last_flaresolverr_redeploy_trigger < FLARESOLVERR_REDEPLOY_COOLDOWN_SECONDS:
        return
    # Set before awaiting the network call so concurrent failing
    # requests arriving in the same moment don't all slip past this
    # check and each trigger their own redeploy.
    _last_flaresolverr_redeploy_trigger = now

    await _trigger_flaresolverr_redeploy(settings)


async def _wait_for_flaresolverr(base_url: str, poll_budget_seconds: float) -> None:
    """Polls FlareSolverr's own lightweight health check until it
    answers (or the budget runs out) — just enough to give the
    redeployed container's new process time to come up before the
    retry, not to wait for anything GasBuddy-specific (that's a
    separate cost paid by the retry's own request).
    """
    deadline = time.monotonic() + poll_budget_seconds
    async with httpx.AsyncClient(timeout=20.0) as client:
        while True:
            try:
                response = await client.get(base_url)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                return
            await asyncio.sleep(REDEPLOY_POLL_INTERVAL_SECONDS)


async def _retry_search_after_flaresolverr_redeploy(
    service: GasBuddyService, settings: Settings, search_kwargs: dict
):
    """Called the first time a search hits CloudflareBlocked. Triggers a
    FlareSolverr redeploy, waits for the new container to come back up,
    then retries the search exactly once — the caller only ever sees
    this as extra loading time, never the original block error, unless
    the retry also fails (or nothing's configured to redeploy at all).

    Raises HTTPException in both of those cases; only returns normally
    on a successful retry.
    """
    if not (settings.render_api_key and settings.flaresolverr_service_id):
        raise HTTPException(
            status_code=502,
            detail="GasBuddy is temporarily blocking automated requests. Try again shortly.",
        )

    await _redeploy_flaresolverr_if_not_recently_triggered(settings)

    solver_url = settings.gasbuddy_solver_url
    if solver_url:
        base_url = solver_url.removesuffix("/v1").removesuffix("/v1/")
        await _wait_for_flaresolverr(base_url, REDEPLOY_POLL_BUDGET_SECONDS)

    try:
        return await service.search_nearest_stations(**search_kwargs)
    except (CloudflareBlocked, LibraryError, APIError) as exc:
        raise HTTPException(
            status_code=502, detail="Failed to obtain gas results."
        ) from exc


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
    settings: Settings = Depends(get_settings),
) -> StationSearchResponse:
    """Return the nearest gas stations for a city, postal code, or GPS location."""
    if not query and (lat is None or lon is None):
        raise HTTPException(
            status_code=400,
            detail="Provide either `query` (city or postal code) or both `lat` and `lon`.",
        )

    search_kwargs = {
        "query": query,
        "lat": lat,
        "lon": lon,
        "limit": limit,
        "cursor": cursor,
    }

    try:
        result = await service.search_nearest_stations(**search_kwargs)
    except GeocodingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingSearchData as exc:
        raise HTTPException(
            status_code=400, detail="Missing search parameters."
        ) from exc
    except CloudflareBlocked:
        # Deliberately not re-raised with `from exc` here — the caller
        # sees either a successful retry or one of two clean error
        # messages, never this original exception's own detail.
        result = await _retry_search_after_flaresolverr_redeploy(
            service, settings, search_kwargs
        )
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

    Deliberately does NOT trigger a FlareSolverr redeploy either — an
    earlier version of this did that unconditionally on every launch,
    but that adds real latency (a 45s+ wait for the new container) to
    every cold app open regardless of whether the user ever hits a
    Cloudflare block that session. See `search_stations`'s handling of
    `CloudflareBlocked` (`_retry_search_after_flaresolverr_redeploy`)
    for where that's triggered instead, only when actually needed.

    Never raises — an unreachable/still-sleeping container is an
    expected, retryable state during startup, not an error.
    """
    solver_url = settings.gasbuddy_solver_url
    if not solver_url:
        # No solver configured on this deploy (e.g. local dev) — nothing
        # to wake, so there's nothing blocking a gas search either.
        return FlareSolverrWarmupResponse(awake=True)

    base_url = solver_url.removesuffix("/v1").removesuffix("/v1/")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(base_url)
        return FlareSolverrWarmupResponse(awake=response.status_code == 200)
    except httpx.HTTPError:
        return FlareSolverrWarmupResponse(awake=False)
