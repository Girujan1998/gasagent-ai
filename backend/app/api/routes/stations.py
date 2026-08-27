import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from py_gasbuddy import APIError, CloudflareBlocked, LibraryError, MissingSearchData

from app.config import Settings, get_settings
from app.models.schemas import ContainerWarmupResponse, StationSearchResponse
from app.services.gas_price_client import GasPriceService, get_gas_price_service
from app.services.geocoding import GeocodingError

router = APIRouter(prefix="/stations", tags=["stations"])

# Redeploying the anti-bot solver service (not just restarting it —
# confirmed live a same-container restart alone wasn't enough) gets it a
# genuinely fresh container, plausibly a new egress IP, clearing
# whatever anti-bot-facing state a stale container had accumulated.
# Triggered reactively, only when a real gas search actually hits
# CloudflareBlocked — an earlier version of this eagerly redeployed on
# every app launch instead, adding a 45s+ poll wait to every cold open
# regardless of whether the user ever searched for gas that session.
# Fire-and-forget: the blocked search still returns its usual error
# right away rather than waiting on the redeploy and retrying inline —
# a version of this that waited and retried once was tried (see git
# history) but meant a single search could take minutes in the worst
# case, risking a raw client-side network timeout instead of a clean
# error message. This cooldown stops a burst of failing requests, while
# one redeploy is already in flight, from queuing up repeat redeploys
# behind it.
SOLVER_REDEPLOY_COOLDOWN_SECONDS = 90.0

_last_solver_redeploy_trigger = 0.0


async def _trigger_solver_redeploy(settings: Settings) -> None:
    """Best-effort triggers a fresh redeploy of the anti-bot solver's own
    hosted service (not a same-container restart — confirmed live that
    a restart alone doesn't help).
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
        # print rather than `logging` — see chat_agent_client.py's own
        # comment on why; this call is otherwise silent (best-effort by
        # design), so without this there's no way to tell a bad
        # key/service ID or a host-side rejection apart from the
        # redeploy simply not helping.
        print(
            f"[solver] deploy trigger -> {response.status_code} "
            f"{response.text[:200]!r}"
        )
    except httpx.HTTPError as exc:
        print(f"[solver] deploy trigger failed: {exc!r}")


async def _redeploy_solver_if_not_recently_triggered(settings: Settings) -> None:
    global _last_solver_redeploy_trigger
    if not (settings.render_api_key and settings.flaresolverr_service_id):
        return

    now = time.monotonic()
    if now - _last_solver_redeploy_trigger < SOLVER_REDEPLOY_COOLDOWN_SECONDS:
        return
    # Set before awaiting the network call so concurrent failing
    # requests arriving in the same moment don't all slip past this
    # check and each trigger their own redeploy.
    _last_solver_redeploy_trigger = now

    await _trigger_solver_redeploy(settings)


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
    service: GasPriceService = Depends(get_gas_price_service),
    settings: Settings = Depends(get_settings),
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
        await _redeploy_solver_if_not_recently_triggered(settings)
        raise HTTPException(
            status_code=502,
            detail="The gas price service is temporarily blocking automated requests. Try again shortly.",
        ) from exc
    except (LibraryError, APIError) as exc:
        raise HTTPException(
            status_code=502, detail=f"Gas price lookup failed: {exc}"
        ) from exc

    return StationSearchResponse(
        results=result.stations,
        next_cursor=result.next_cursor,
        lat=result.lat,
        lon=result.lon,
    )


@router.post("/warmup-container", response_model=ContainerWarmupResponse)
async def warmup_solver_container(
    settings: Settings = Depends(get_settings),
) -> ContainerWarmupResponse:
    """Wakes the anti-bot solver's own container (the free hosting tier
    sleeps it after 15 min idle) without calling the gas-price lookup at
    all.

    Deliberately does NOT run a real gas search to prime a session
    token — an earlier version of this endpoint did exactly that, but
    it fired unconditionally on every app launch regardless of whether
    the user ever searched for gas that session, adding real load
    against the gas-price lookup's own request-rate limit for zero
    benefit on EV/Chat-only sessions. This only removes the container's
    cold-start delay; the user's first real gas search still pays for
    the actual anti-bot challenge-solve itself, since that step can
    only happen by actually contacting the gas-price lookup.

    Deliberately does NOT trigger a solver redeploy either — an earlier
    version of this did that unconditionally on every launch, but that
    adds real latency (a 45s+ wait for the new container) to every cold
    app open regardless of whether the user ever hits an anti-bot block
    that session. See `search_stations`'s `CloudflareBlocked` handler
    for where that's triggered instead, only when actually needed.

    Never raises — an unreachable/still-sleeping container is an
    expected, retryable state during startup, not an error.
    """
    solver_url = settings.gasbuddy_solver_url
    if not solver_url:
        # No solver configured on this deploy (e.g. local dev) — nothing
        # to wake, so there's nothing blocking a gas search either.
        return ContainerWarmupResponse(awake=True)

    base_url = solver_url.removesuffix("/v1").removesuffix("/v1/")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(base_url)
        return ContainerWarmupResponse(awake=response.status_code == 200)
    except httpx.HTTPError:
        return ContainerWarmupResponse(awake=False)
