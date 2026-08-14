import re

import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
ZIPPOPOTAM_CA_URL = "https://api.zippopotam.us/CA/{fsa}"

# Canada Post postal code format: letter-digit-letter digit-letter-digit,
# excluding D, F, I, O, Q, U (and W, Z) from the first letter position.
# Only the first 3 characters (the FSA, e.g. "M5V") are geocodable via the
# free lookup below — Zippopotam doesn't resolve to full 6-character
# precision, so this is neighborhood-level, not exact-address-level.
CA_POSTAL_CODE_PATTERN = re.compile(
    r"^([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z])\s?\d[ABCEGHJ-NPRSTV-Z]\d$",
    re.IGNORECASE,
)


class GeocodingError(Exception):
    """Raised when a free-text location query can't be resolved to coordinates."""


def _extract_ca_fsa(query: str) -> str | None:
    match = CA_POSTAL_CODE_PATTERN.match(query.strip())
    return match.group(1).upper() if match else None


async def _geocode_ca_postal_code(query: str, fsa: str) -> tuple[float, float]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(ZIPPOPOTAM_CA_URL.format(fsa=fsa))

    if response.status_code == 404:
        raise GeocodingError(f"No location found for postal code '{query}'.")
    response.raise_for_status()

    places = response.json().get("places") or []
    if not places:
        raise GeocodingError(f"No location found for postal code '{query}'.")

    place = places[0]
    return float(place["latitude"]), float(place["longitude"])


async def _geocode_open_meteo(query: str) -> tuple[float, float]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            GEOCODING_URL, params={"name": query, "count": 1}
        )
        response.raise_for_status()
        data = response.json()

    results = data.get("results") or []
    if not results:
        raise GeocodingError(f"No location found for '{query}'.")

    top = results[0]
    return top["latitude"], top["longitude"]


async def geocode(query: str) -> tuple[float, float]:
    """Resolve a city name or postal code to (lat, lon).

    py-gasbuddy's location search only accepts US zip codes or raw
    coordinates — this fills the gap for city names, Canadian postal
    codes, and other postal code formats.
    """
    fsa = _extract_ca_fsa(query)
    if fsa:
        return await _geocode_ca_postal_code(query, fsa)

    return await _geocode_open_meteo(query)
