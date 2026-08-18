from fastapi import APIRouter, Depends, HTTPException, Query
from py_gasbuddy import APIError, CloudflareBlocked, LibraryError, MissingSearchData

from app.models.schemas import GasPriceForecast
from app.services.forecast import ForecastService, get_forecast_service

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("", response_model=GasPriceForecast)
async def get_gas_price_forecast(
    lat: float = Query(..., description="Latitude of the area to forecast"),
    lon: float = Query(..., description="Longitude of the area to forecast"),
    service: ForecastService = Depends(get_forecast_service),
) -> GasPriceForecast:
    """Forecast tomorrow's average regular gas price for stations near a
    location, from today's live GasBuddy average adjusted by a national
    trend (Statistics Canada for Canadian locations, US EIA for American
    ones, when configured)."""
    try:
        return await service.forecast(lat, lon)
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
