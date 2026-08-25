from fastapi import APIRouter, Depends, HTTPException, Query
from py_gasbuddy import APIError, CloudflareBlocked, LibraryError, MissingSearchData

from app.models.schemas import StationSearchResponse, WarmupResponse
from app.services.gasbuddy_client import GasBuddyService, get_gasbuddy_service
from app.services.geocoding import GeocodingError

router = APIRouter(prefix="/stations", tags=["stations"])

# A fixed, arbitrary real location (Cambridge, ON) — warmup doesn't care
# about the result, only about exercising the exact same GasBuddy call a
# real search makes, so FlareSolverr's container wakes up and py-gasbuddy's
# CSRF token gets cached before the user's own first search needs it.
WARMUP_LAT = 43.3601
WARMUP_LON = -80.31269


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


@router.post("/warmup", response_model=WarmupResponse)
async def warmup_gas_search(
    service: GasBuddyService = Depends(get_gasbuddy_service),
) -> WarmupResponse:
    """Runs a throwaway search so a client can wake FlareSolverr and prime
    py-gasbuddy's cached CSRF token ahead of the user's own first search,
    rather than paying that cost mid-request. Never raises — the caller
    decides whether/how long to keep polling on `ready: false`."""
    try:
        await service.search_nearest_stations(lat=WARMUP_LAT, lon=WARMUP_LON, limit=1)
    except CloudflareBlocked as exc:
        return WarmupResponse(ready=False, detail=str(exc))
    except (LibraryError, APIError) as exc:
        return WarmupResponse(ready=False, detail=str(exc))
    return WarmupResponse(ready=True)
