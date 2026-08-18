import time

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

# Nominatim's usage policy requires a real identifying User-Agent (a
# generic/browser-like one risks getting blocked) and asks callers to
# cache aggressively rather than re-querying the same area repeatedly —
# see https://operations.osmfoundation.org/policies/nominatim/.
USER_AGENT = "GasAgentAI/1.0 (gas price forecast; contact: app support)"

# Coarse on purpose — which *country* a point falls in almost never
# changes within a ~20km cell, and a coarser grid means far fewer requests
# against Nominatim's shared, rate-limited (1 req/sec) public instance.
# The one real risk is a cell that straddles the US/Canada border getting
# tagged by whichever side its rounded center happens to land on — an
# accepted imprecision for a secondary trend signal, not the headline price.
CACHE_GRID_DEGREES = 0.2
CACHE_TTL_SECONDS = 86400  # a day — country isn't going to change sooner.


class CountryLookupError(Exception):
    """Raised when reverse geocoding to a country fails."""


def _cache_key(lat: float, lon: float) -> tuple[float, float]:
    return (
        round(lat / CACHE_GRID_DEGREES) * CACHE_GRID_DEGREES,
        round(lon / CACHE_GRID_DEGREES) * CACHE_GRID_DEGREES,
    )


# Module-level, not per-instance — mirrors ocm_client.py's cache (see that
# file's comment for why): get_country_lookup_service() below hands out a
# fresh instance per request.
_cache: dict[tuple[float, float], tuple[float, str | None]] = {}


class CountryLookupService:
    async def resolve_country_code(self, lat: float, lon: float) -> str | None:
        """Returns a lowercase ISO country code (e.g. "us", "ca"), or None
        if it can't be resolved."""
        key = _cache_key(lat, lon)
        cached = _cache.get(key)
        if cached is not None:
            cached_at, country_code = cached
            if time.monotonic() - cached_at < CACHE_TTL_SECONDS:
                return country_code

        grid_lat, grid_lon = key
        params = {
            "lat": grid_lat,
            "lon": grid_lon,
            "format": "json",
            # Country-level detail only — the coarsest zoom Nominatim
            # supports, and all this ever needs.
            "zoom": 3,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    NOMINATIM_URL,
                    params=params,
                    headers={"User-Agent": USER_AGENT},
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CountryLookupError(f"Reverse geocoding failed: {exc}") from exc

        country_code = (data.get("address") or {}).get("country_code")
        country_code = country_code.lower() if country_code else None
        _cache[key] = (time.monotonic(), country_code)
        return country_code


def get_country_lookup_service() -> CountryLookupService:
    return CountryLookupService()
