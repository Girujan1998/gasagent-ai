from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from py_gasbuddy import GasBuddy

from app.config import get_settings
from app.models.schemas import FuelPrice, GasStation
from app.services.geocoding import geocode

# GasBuddy's own fixed page size — confirmed live that requesting a larger
# `limit` in a single call doesn't return more results (the GraphQL query
# behind price_lookup_service has no server-side page-size variable at
# all; `limit` is purely a client-side slice of one fixed-size page). A
# caller that wants more must follow `next_cursor` across multiple calls.
GASBUDDY_PAGE_SIZE = 20


def format_price_like(sample: str | None, value: float) -> str | None:
    """Formats `value` using whichever regional convention `sample`
    (a real formatted_price from one of the sampled stations) used —
    "$3.19"-style in the US, "167.7¢"-style in Canada — since the raw
    float alone doesn't say which, and GasBuddy already picked one for
    real stations in this exact average. Shared by forecast.py (today's
    average/lowest/highest price) and chat_client.py (a location's
    average price for a fuel grade).
    """
    if sample is None:
        return None
    stripped = sample.strip()
    if stripped.startswith("$"):
        return f"${value:.2f}"
    if stripped.endswith("¢"):
        return f"{value:.1f}¢"
    return f"{value:.2f}"


@dataclass
class StationSearchResult:
    stations: list[GasStation]
    next_cursor: str | None
    lat: float
    lon: float


def _to_fuel_price(node: dict[str, Any] | None) -> FuelPrice | None:
    if not node:
        return None
    return FuelPrice(
        price=node.get("price"),
        formatted_price=node.get("formatted_price"),
        last_updated=node.get("last_updated"),
    )


def _amenity_names(amenities: list[dict[str, Any]]) -> list[str]:
    return [a["name"] for a in amenities if isinstance(a, dict) and a.get("name")]


def _select_brands(
    brands: list[dict[str, Any]], station_name: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Pick the primary brand and, if present, one *distinct* connected brand.

    GasBuddy can list multiple brands for a single station — e.g. a Circle
    K-branded store selling Esso fuel. The station's own `name` field is
    what identifies the primary brand; any other entry is a connected
    brand, not a co-equal primary. Falls back to the first listed brand if
    none match `name` (e.g. the name is a street address or generic label).

    GasBuddy's data sometimes lists the same brand twice (identical name,
    logo, everything) rather than a genuine second brand — that's treated
    as if there were no connected brand at all, not shown as one.
    """
    if not brands:
        return None, None

    primary = next(
        (b for b in brands if (b.get("name") or "").lower() == station_name.lower()),
        brands[0],
    )
    primary_name = (primary.get("name") or "").lower()
    secondary = next(
        (b for b in brands if (b.get("name") or "").lower() != primary_name),
        None,
    )
    return primary, secondary


def _to_gas_station(raw: dict[str, Any]) -> GasStation:
    address = raw.get("address") or {}
    address_parts = [
        address.get("line1"),
        address.get("locality"),
        address.get("region"),
    ]
    address_line = ", ".join(part for part in address_parts if part) or None

    brands = raw.get("brands") or []
    primary_brand, connected_brand = _select_brands(brands, raw.get("name") or "")
    brand_name = primary_brand.get("name") if primary_brand else None
    brand_logo_url = primary_brand.get("imageUrl") if primary_brand else None
    connected_brand_name = connected_brand.get("name") if connected_brand else None
    connected_brand_logo_url = (
        connected_brand.get("imageUrl") if connected_brand else None
    )

    return GasStation(
        station_id=str(raw["station_id"]),
        name=raw.get("name") or "",
        brand=brand_name,
        brand_logo_url=brand_logo_url,
        connected_brand=connected_brand_name,
        connected_brand_logo_url=connected_brand_logo_url,
        address=address_line,
        latitude=raw.get("latitude"),
        longitude=raw.get("longitude"),
        distance_miles=raw.get("distance"),
        regular=_to_fuel_price(raw.get("regular_gas")),
        midgrade=_to_fuel_price(raw.get("midgrade_gas")),
        premium=_to_fuel_price(raw.get("premium_gas")),
        diesel=_to_fuel_price(raw.get("diesel")),
        star_rating=raw.get("star_rating"),
        ratings_count=raw.get("ratings_count"),
        amenities=_amenity_names(raw.get("amenities") or []),
    )


class GasBuddyService:
    """Wraps py-gasbuddy to find the nearest stations for a search.

    Always resolves to lat/lon before calling GasBuddy — passing a zip code
    straight through to py-gasbuddy's `zipcode` param works, but GasBuddy
    doesn't return a `distance` for that path, and distance is a required
    field for every result here. Geocoding first (via Open-Meteo) keeps
    distance populated consistently for city, postal code, and GPS search.
    """

    def __init__(self, solver_url: str | None = None) -> None:
        self._client = GasBuddy(solver_url=solver_url)

    async def search_nearest_stations(
        self,
        *,
        query: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        limit: int = 10,
        cursor: str | None = None,
    ) -> StationSearchResult:
        if lat is None or lon is None:
            if not query:
                lat = lon = None
            else:
                lat, lon = await geocode(query)

        result = await self._client.price_lookup_service(
            lat=lat, lon=lon, limit=limit, cursor=cursor
        )
        stations = [_to_gas_station(s) for s in result["results"]]
        return StationSearchResult(
            stations=stations,
            next_cursor=result.get("next_cursor"),
            lat=lat,
            lon=lon,
        )


@lru_cache
def get_gasbuddy_service() -> GasBuddyService:
    # A real singleton, not just cheap-to-construct — py-gasbuddy's own
    # CSRF-token refresh lock (and its cached token) lives on the
    # underlying GasBuddy instance. A fresh instance per request (the
    # previous behavior here) meant that lock never actually applied
    # across requests: every concurrent request during a cold start
    # independently decided it had no cached token and kicked off its
    # own FlareSolverr solve, several at once competing for the same
    # RAM-constrained container. Sharing one instance means concurrent
    # requests queue on the same lock and share the same cached token,
    # the way py-gasbuddy's own locking was actually designed to work.
    return GasBuddyService(solver_url=get_settings().gasbuddy_solver_url or None)
