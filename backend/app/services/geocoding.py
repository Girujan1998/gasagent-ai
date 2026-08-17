import re
from dataclasses import dataclass

import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
ZIPPOPOTAM_CA_URL = "https://api.zippopotam.us/CA/{fsa}"

# Open-Meteo's geocoding API has no server-side country filter (a
# `countryCode`/`country_code` param is silently ignored), so autocomplete
# results are restricted to the US and Canada here instead, after fetching.
AUTOCOMPLETE_COUNTRY_CODES = {"US", "CA"}

# Canada Post postal code format: letter-digit-letter digit-letter-digit,
# excluding D, F, I, O, Q, U (and W, Z) from the first letter position.
# Only the first 3 characters (the FSA, e.g. "M5V") are geocodable via the
# free lookup below — Zippopotam doesn't resolve to full 6-character
# precision, so this is neighborhood-level, not exact-address-level.
CA_POSTAL_CODE_PATTERN = re.compile(
    r"^([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z])\s?\d[ABCEGHJ-NPRSTV-Z]\d$",
    re.IGNORECASE,
)
# Just the FSA half, standalone — lets a bare "N1T" search work on its own
# (same neighborhood-level precision as the full code above, since the
# lookup only ever used the FSA anyway) and lets autocomplete recognize a
# postal code is being typed as soon as its first 3 characters land.
CA_FSA_PATTERN = re.compile(r"^[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]$", re.IGNORECASE)


class GeocodingError(Exception):
    """Raised when a free-text location query can't be resolved to coordinates."""


@dataclass
class LocationSuggestion:
    label: str
    value: str


def _extract_ca_fsa(query: str) -> str | None:
    stripped = query.strip()
    full_match = CA_POSTAL_CODE_PATTERN.match(stripped)
    if full_match:
        return full_match.group(1).upper()
    fsa_match = CA_FSA_PATTERN.match(stripped)
    return fsa_match.group(0).upper() if fsa_match else None


def _looks_like_ca_postal_code(query: str) -> bool:
    prefix = query.strip().replace(" ", "")[:3]
    return len(prefix) == 3 and bool(CA_FSA_PATTERN.match(prefix))


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


async def _autocomplete_ca_postal_code(query: str) -> list[LocationSuggestion]:
    fsa = query.strip().replace(" ", "")[:3].upper()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(ZIPPOPOTAM_CA_URL.format(fsa=fsa))
    except httpx.HTTPError:
        return []

    if response.status_code != 200:
        return []

    places = response.json().get("places") or []
    if not places:
        return []

    place = places[0]
    return [
        LocationSuggestion(
            label=f"{fsa} · {place['place name']}, {place['state abbreviation']}",
            value=fsa,
        )
    ]


async def _autocomplete_city(query: str) -> list[LocationSuggestion]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Fetch a wider pool than we need (5) before filtering down to
            # the US/CA subset below — a name like "Paris" or "London" is
            # dominated by its non-US/CA match, so asking for only 8 and
            # then filtering could easily leave nothing left.
            response = await client.get(
                GEOCODING_URL, params={"name": query, "count": 20}
            )
            response.raise_for_status()
    except httpx.HTTPError:
        return []

    results = response.json().get("results") or []
    results = [
        r for r in results if r.get("country_code") in AUTOCOMPLETE_COUNTRY_CODES
    ]
    # Open-Meteo's short-prefix matches skew toward tiny, obscure places —
    # favor recognizable ones so a query like "Tor" surfaces Toronto over a
    # hamlet nobody's searching for.
    results.sort(key=lambda r: r.get("population") or 0, reverse=True)

    suggestions: list[LocationSuggestion] = []
    seen_labels: set[str] = set()
    for result in results:
        name = result.get("name")
        if not name:
            continue
        parts = [name]
        if result.get("admin1"):
            parts.append(result["admin1"])
        if result.get("country"):
            parts.append(result["country"])
        label = ", ".join(parts)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        suggestions.append(LocationSuggestion(label=label, value=label))
        if len(suggestions) == 5:
            break

    return suggestions


async def autocomplete_locations(query: str) -> list[LocationSuggestion]:
    """Suggest cities or postal codes matching a partial query.

    Deliberately excludes street-level addresses — a postal-code-looking
    prefix goes through the FSA lookup, everything else through the city
    geocoder, neither of which resolves to individual addresses.
    """
    stripped = query.strip()
    if len(stripped) < 3:
        return []

    if _looks_like_ca_postal_code(stripped):
        return await _autocomplete_ca_postal_code(stripped)

    return await _autocomplete_city(stripped)
