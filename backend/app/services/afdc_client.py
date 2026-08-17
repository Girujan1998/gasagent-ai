from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.models.schemas import EvStation
from app.services.geocoding import geocode

# NREL's developer portal moved from developer.nrel.gov to developer.nlr.gov
# (the old host's DNS delegation is gone entirely as of 2026-08) — this is
# the same AFDC API, same api_key, just a renamed host.
NREL_URL = "https://developer.nlr.gov/api/alt-fuel-stations/v1/nearest.json"

# Unlike GasBuddy's gas-price lookup (nearest N stations, no distance
# bound), NREL's search requires a radius. This is generous on purpose —
# wide enough that `limit` is almost always the thing that actually caps
# the result count, keeping the "nearest N regardless of exact distance"
# feel the gas search already has.
SEARCH_RADIUS_MILES = 50

KM_TO_MILES = 0.621371

# NREL's own hard ceiling — confirmed via its own validation error
# ("Limit cannot exceed 200"). There's no further pagination beyond this on
# their end, so 200 is the practical "no maximum" a caller can ask for.
MAX_LIMIT = 200


class AfdcError(Exception):
    """Raised when the NREL AFDC API request fails."""


@dataclass
class EvStationSearchResult:
    stations: list[EvStation]
    total_results: int
    lat: float
    lon: float


def _build_address(raw: dict[str, Any]) -> str | None:
    # AFDC reports the street, city, and state as separate fields — combined
    # here into one line (e.g. "55 Dickson Street, Cambridge, ON") to match
    # how GasStation.address is already a full address, not just a street.
    parts = [raw.get("street_address"), raw.get("city"), raw.get("state")]
    joined = ", ".join(part for part in parts if part)
    return joined or None


def _to_ev_station(raw: dict[str, Any]) -> EvStation:
    return EvStation(
        station_id=str(raw["id"]),
        name=raw.get("station_name") or "",
        network=raw.get("ev_network"),
        network_web=raw.get("ev_network_web"),
        address=_build_address(raw),
        latitude=raw.get("latitude"),
        longitude=raw.get("longitude"),
        distance_miles=raw.get("distance"),
        phone=raw.get("station_phone"),
        access_hours=raw.get("access_days_time"),
        access_code=raw.get("access_code"),
        status_code=raw.get("status_code"),
        level1_count=raw.get("ev_level1_evse_num"),
        level2_count=raw.get("ev_level2_evse_num"),
        dc_fast_count=raw.get("ev_dc_fast_num"),
        connector_types=raw.get("ev_connector_types") or [],
        date_last_confirmed=raw.get("date_last_confirmed"),
    )


class AfdcService:
    def __init__(self) -> None:
        self._api_key = get_settings().nrel_api_key

    async def search_nearest_ev_stations(
        self,
        *,
        query: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        limit: int = 20,
        radius_km: float | None = None,
    ) -> EvStationSearchResult:
        if lat is None or lon is None:
            assert query is not None  # enforced by the route before this is called
            lat, lon = await geocode(query)

        radius_miles = (
            radius_km * KM_TO_MILES if radius_km is not None else SEARCH_RADIUS_MILES
        )
        params = {
            "api_key": self._api_key,
            "latitude": lat,
            "longitude": lon,
            "radius": radius_miles,
            "fuel_type": "ELEC",
            "status": "E",
            "access": "public",
            # Without this, NREL defaults to US-only and silently returns
            # zero results for a Canadian location — matches the app's own
            # US/CA scope (see geocoding.py's AUTOCOMPLETE_COUNTRY_CODES).
            "country": "US,CA",
            "limit": limit,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(NREL_URL, params=params)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AfdcError(f"NREL AFDC lookup failed: {exc}") from exc

        data = response.json()
        raw_stations = data.get("fuel_stations") or []
        stations = [_to_ev_station(s) for s in raw_stations]
        return EvStationSearchResult(
            stations=stations,
            # Falls back to the count actually returned if the response
            # doesn't include a total — worst case, "load more" just stops
            # being offered a page early rather than looping forever.
            total_results=data.get("total_results", len(stations)),
            lat=lat,
            lon=lon,
        )


def get_afdc_service() -> AfdcService:
    return AfdcService()
