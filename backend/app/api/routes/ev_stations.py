from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.schemas import EvStationSearchResponse
from app.services.afdc_client import (
    MAX_LIMIT,
    AfdcError,
    AfdcService,
    get_afdc_service,
)
from app.services.geocoding import GeocodingError

router = APIRouter(prefix="/ev-stations", tags=["ev-stations"])


@router.get("/search", response_model=EvStationSearchResponse)
async def search_ev_stations(
    query: str | None = Query(
        None, description="City name or postal code to search near"
    ),
    lat: float | None = Query(None, description="Latitude of the current location"),
    lon: float | None = Query(None, description="Longitude of the current location"),
    # NREL has no cursor-based pagination — "load more" just re-requests
    # the same location with a larger limit, so this cap is higher than
    # gas's per-page limit rather than a page size. The ceiling is NREL's
    # own hard limit (see afdc_client.MAX_LIMIT), not an extra restriction
    # of ours — map view asks for the full 200 in one shot.
    limit: int = Query(20, ge=1, le=MAX_LIMIT),
    # Map view searches a wide, fixed radius instead of reusing list view's
    # nearest-N results — overrides afdc_client's default 50-mile radius.
    radius_km: float | None = Query(
        None, gt=0, le=200, description="Search radius in kilometers"
    ),
    service: AfdcService = Depends(get_afdc_service),
) -> EvStationSearchResponse:
    """Return the nearest public EV charging stations for a location."""
    if not query and (lat is None or lon is None):
        raise HTTPException(
            status_code=400,
            detail="Provide either `query` (city or postal code) or both `lat` and `lon`.",
        )

    try:
        result = await service.search_nearest_ev_stations(
            query=query, lat=lat, lon=lon, limit=limit, radius_km=radius_km
        )
    except GeocodingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AfdcError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return EvStationSearchResponse(
        results=result.stations,
        total_results=result.total_results,
        lat=result.lat,
        lon=result.lon,
    )
