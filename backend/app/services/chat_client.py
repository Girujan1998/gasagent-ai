import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Depends
from py_gasbuddy import APIError, CloudflareBlocked, LibraryError, MissingSearchData

from app.config import get_settings
from app.models.schemas import ChatMessage, GasStation
from app.services.gasbuddy_client import (
    GASBUDDY_PAGE_SIZE,
    GasBuddyService,
    format_price_like,
    get_gasbuddy_service,
)
from app.services.geocoding import GeocodingError

# OpenAI-compatible — Groq implements the same Chat Completions shape, so
# there's no Groq-specific SDK or request/response format here.
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

FIND_STATIONS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "find_nearby_gas_stations",
        "description": (
            "Look up real, current gas stations and their live fuel prices "
            "near a location (or several locations to compare at once), "
            "using the app's own GasBuddy integration. Supports optional "
            "filters — a specific brand or several brands at once, a "
            "brand recognition tier (major-chain vs. independent), a "
            "maximum distance in miles, a fuel grade to sort by price, "
            "and/or a specific number of stations to return — pass only "
            "the ones the user actually asked for. Call this whenever the "
            "user asks about nearby gas stations, gas prices, or the "
            "cheapest gas around — never answer such questions from "
            "general knowledge or invent station names, addresses, or "
            "prices; never sort or rank stations by price yourself "
            "(always pass fuel_grade instead); never judge yourself "
            "whether a brand counts as a 'big name' or not (always pass "
            "brand_tier instead); and never call this tool more than once "
            "per turn just to check multiple brands or multiple places "
            "one at a time (always pass brands and/or locations with all "
            "of them together instead) — the tool does that filtering, "
            "sorting, and per-place grouping for you. Not for EV charging."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    # Confirmed live: the model sometimes passes JSON `null`
                    # for an omitted optional argument rather than leaving
                    # the key out entirely, which Groq's own tool-call
                    # schema validation rejects for a plain "string" type —
                    # ["string", "null"] accepts both forms. Same pattern
                    # applied to every optional param below.
                    "type": ["string", "null"],
                    "description": (
                        "A specific place to search near — a city, "
                        "neighborhood, postal code, or address — ONLY when "
                        "the user named exactly ONE explicitly (e.g. "
                        "'Toronto', 'near 90210'). Leave this unset (or "
                        "null) when the user means their own current "
                        "location ('near me', 'nearby', 'around here', or "
                        "no place mentioned at all) — the backend already "
                        "knows the user's current location and will use it "
                        "automatically. Don't combine with locations — use "
                        "locations instead when the user named two or more "
                        "places to compare."
                    ),
                },
                "locations": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": (
                        "Two or more specific places to search and compare "
                        "in ONE lookup — e.g. ['Toronto', 'Mississauga'] — "
                        "ONLY when the user asked to compare gas prices or "
                        "stations across multiple named places in the same "
                        "request ('is gas cheaper in Toronto or "
                        "Mississauga', 'compare prices in Kitchener and "
                        "Waterloo'). Always pass every named place here "
                        "together in a single call rather than calling "
                        "this tool once per place. Results come back "
                        "grouped by place so you can compare them. If "
                        "station_count is also set, it caps the result PER "
                        "place (so each place gets its own comparable "
                        "sample), not a combined total. Use `location` "
                        "instead for a single place, and don't set both "
                        "location and locations at once. Leave unset (or "
                        "null) otherwise — this doesn't apply to a plain "
                        "'near me' search, which has no named place at all."
                    ),
                },
                "brand": {
                    "type": ["string", "null"],
                    "description": (
                        "A specific gas brand or chain to filter for — "
                        "e.g. 'Shell', 'Esso', 'Costco', 'Chevron' — ONLY "
                        "when the user asked for exactly ONE particular "
                        "brand ('find a Shell near me', 'is there a Costco "
                        "gas station nearby'). Pass just the brand name "
                        "itself, not a full phrase (e.g. 'Shell', not 'a "
                        "Shell gas station'). Leave unset (or null) when "
                        "the user didn't name a brand. Don't combine with "
                        "brand_tier or brands — use exactly one of "
                        "brand/brands/brand_tier, and use `brands` "
                        "instead when the user named two or more brands."
                    ),
                },
                "brands": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": (
                        "Two or more specific gas brands or chains to "
                        "search for together in ONE lookup — e.g. "
                        "['Shell', 'Petro-Canada'] — ONLY when the user "
                        "named multiple specific brands in the same "
                        "request ('find the nearest Shell and Petro-"
                        "Canada stations', 'is there an Esso or a Chevron "
                        "nearby'). A station matching ANY of the listed "
                        "brands is included. Always pass every named "
                        "brand here together in a single call — never "
                        "call this tool once per brand instead. If "
                        "station_count is also set, it caps the combined "
                        "total across all listed brands, not a separate "
                        "count per brand. Use `brand` instead when only "
                        "one specific brand was named, and don't set both "
                        "brand and brands at once. Leave unset (or null) "
                        "otherwise."
                    ),
                },
                "brand_tier": {
                    "type": ["string", "null"],
                    "description": (
                        "One of 'major' or 'lesser_known'. Pass 'major' "
                        "when the user asks for a 'big name', 'major', "
                        "'well-known', or 'name-brand' station without "
                        "naming one specifically. Pass 'lesser_known' "
                        "when the user asks for an independent, local, "
                        "non-chain, or 'lesser-known' station instead. "
                        "The tool checks each station against its own "
                        "list of recognized major chains — you don't need "
                        "to judge or recall which brands count yourself, "
                        "and shouldn't guess. Leave unset (or null) for a "
                        "plain search with no brand-tier preference, and "
                        "use `brand` instead when the user names one "
                        "specific brand."
                    ),
                },
                "max_distance_miles": {
                    "type": ["number", "null"],
                    "description": (
                        "Only include stations within this many miles of "
                        "the searched location — ONLY when the user gave "
                        "an explicit distance or radius ('within 5 "
                        "miles', 'closer than 2 miles'). Leave unset (or "
                        "null) when no distance was mentioned; omitting "
                        "this returns the nearest stations regardless of "
                        "how far they are."
                    ),
                },
                "station_count": {
                    "type": ["integer", "null"],
                    "description": (
                        "How many stations to return, ONLY when the user "
                        "asked for a specific number ('show me 3 gas "
                        "stations', 'find the top 5 cheapest'). Only "
                        "meaningful together with brand, brands, "
                        "brand_tier, max_distance_miles, and/or "
                        "fuel_grade. On its "
                        "own, with none of those given, this is ignored "
                        "— the tool always returns its full nearby sample "
                        "so you have enough real options to compare "
                        "rather than an arbitrarily small slice."
                    ),
                },
                "fuel_grade": {
                    "type": ["string", "null"],
                    "description": (
                        "One of 'regular', 'midgrade', 'premium', 'diesel' "
                        "— pass this whenever the user asks about the "
                        "cheapest/lowest-priced gas, wants stations ranked "
                        "by price, or names a specific grade's price "
                        "('cheapest premium near me', 'top 3 cheapest "
                        "gas', 'which has the lowest diesel'). For a plain "
                        "'cheapest gas' with no grade named, use "
                        "'regular'. Setting this makes the tool sort the "
                        "returned stations by that grade's price, cheapest "
                        "first, and drop any station that doesn't report a "
                        "price for it — always relay the stations in the "
                        "exact order given; never re-sort, re-rank, or "
                        "recompute which is cheapest yourself. Leave unset "
                        "(or null) when the user isn't asking about price "
                        "ranking at all."
                    ),
                },
            },
            "required": [],
        },
    },
}
TOOLS = [FIND_STATIONS_TOOL]

# The pause before fetching a second page of stations (brand/distance/count
# lookups only) — the first pause-between-calls pattern in this codebase.
# py-gasbuddy is an unofficial scraper of GasBuddy's internal API (it
# already has CloudflareBlocked handling for exactly this reason); two
# rapid-fire requests in the same tool call look more like a scripted burst
# than a second page ever does on its own. Only ever awaited immediately
# before a genuinely-needed second-page fetch (see _needs_second_page),
# never speculatively.
SECOND_PAGE_PAUSE_SECONDS = 1.0

# Bounds worst-case GasBuddy calls per user turn (py-gasbuddy is an
# unofficial scraper — see gasbuddy_client.py — so every extra round is an
# extra live request against it). Rounds 1-2 offer the tool; round 3
# deliberately omits `tools` from the payload entirely, which (confirmed
# live against Groq) makes it structurally impossible for the model to
# return another tool_calls response on that round — so there's no
# separate "cap exceeded" error path to handle, the final round is
# guaranteed to be plain text.
MAX_TOOL_ROUNDS = 3

# The default number of stations shown whenever fuel_grade is set and the
# model didn't ask for a specific station_count — for a single place (in
# _stations_tool_payload) and per place in a locations comparison (in
# _execute_multi_location_lookup) alike. Applied only to the DISPLAYED
# list, after the cheapest station / average_price has already been
# computed from the full scanned sample, so this can't skew either one or
# reintroduce the old "capped before sorting" bug. It exists purely to
# stop an uncapped fuel_grade search from echoing back a full ~20-station
# page (as many fields each) that round 2 then has to re-read in full
# just to answer a "what's the cheapest" or comparison question.
FUEL_GRADE_DISPLAY_CAP = 5

NO_LOCATION_MESSAGE = (
    "No location is available for this user right now — the app hasn't "
    "shared a current location, and no place was named. Ask the user to "
    "share their location or name a city, postal code, or address."
)

# Shown as a normal assistant reply (not an error banner) when Groq itself
# reports a rate limit (HTTP 429) — this is routine under the free/on-demand
# tier's tight per-minute/per-day token caps, not a real failure, so the
# user gets an actionable suggestion in the chat instead of a scary error.
RATE_LIMIT_MESSAGE = (
    "You have hit the model limit with this request, please breakdown "
    "the request into 2 or more parts."
)

# Matches the GasStation attribute names for each grade's FuelPrice field,
# so a validated fuel_grade string can be used directly with getattr().
VALID_FUEL_GRADES = {"regular", "midgrade", "premium", "diesel"}

VALID_BRAND_TIERS = {"major", "lesser_known"}

# Mirrors mobile/src/utils/brandFilter.ts's WELL_KNOWN_BRANDS — the same
# recognized-chain list the Gas tab's own brand filter uses. Used by
# _is_major_brand to classify a station for the brand_tier filter in
# code, rather than embedding this list in SYSTEM_PROMPT and asking the
# model to judge membership itself (which didn't reliably recognize
# regional chains like Pioneer or Ultramar as "major"). Keep in sync with
# the mobile list.
WELL_KNOWN_BRANDS = [
    "Shell",
    "Esso",
    "Exxon",
    "Mobil",
    "Chevron",
    "BP",
    "Costco",
    "Circle K",
    "Sunoco",
    "Marathon",
    "Valero",
    "Speedway",
    "7-Eleven",
    "Petro-Canada",
    "Canadian Tire",
    "Husky",
    "Ultramar",
    "Pioneer",
]

SYSTEM_PROMPT = (
    "You are the in-app assistant for GasAgent.ai, a mobile app for "
    "finding nearby gas prices and EV charging stations. Be concise and "
    "friendly.\n\n"
    "Your replies are shown as plain text in a mobile chat bubble with no "
    "markdown rendering — never use markdown tables, headers, or "
    "asterisks for bold/italic. Write in short plain sentences or a "
    "simple list with line breaks and dashes; when listing stations, one "
    "per line (e.g. 'Shell (0.7 mi) — $1.60/L') rather than a table.\n\n"
    "You have a tool, find_nearby_gas_stations, that returns real, "
    "current gas stations and live fuel prices from the app's own "
    "GasBuddy integration, optionally filtered by brand, brand tier, "
    "distance, fuel grade, and/or a specific count. Call it whenever the "
    "user asks about nearby gas stations, gas prices, or the cheapest "
    "gas around.\n\n"
    "The tool does all filtering, brand-recognition, and price-sorting "
    "itself — you only choose which arguments to pass, you never "
    "perform this work yourself:\n"
    "- Cheapest/lowest/best-priced gas, for any grade, or a 'top N "
    "cheapest' ranking: pass fuel_grade (default to 'regular' if no "
    "grade is named). You are not reliable at comparing many prices by "
    "eye, especially when they're close together, so never rank or "
    "compare stations by price yourself. For a single place, the "
    "response includes an explicit cheapest field — use that directly "
    "for a 'what's the cheapest' question rather than reading down the "
    "stations list to find it yourself.\n"
    "- 'Big name'/'major'/'well-known' brand, without naming one "
    "specifically: pass brand_tier: 'major'. 'Independent'/'local'/"
    "'non-chain'/'lesser-known' stations: pass brand_tier: "
    "'lesser_known'. You don't reliably know which brands count as "
    "major, so never judge or guess this yourself — the tool checks "
    "each station against its own recognized-chain list.\n"
    "- Two or more specific brands named in the same request (e.g. "
    "'Shell and Petro-Canada near me'): pass them together in brands "
    "as a list in one call — never call the tool once per brand.\n"
    "- Comparing gas prices/stations across two or more named places "
    "(e.g. 'is gas cheaper in Toronto or Mississauga'): pass them "
    "together in locations as a list in one call — never call the "
    "tool once per place. The result comes back grouped by place, "
    "along with fuel_grade; when judging which place is cheaper "
    "overall, use each place's average_price, not the single cheapest "
    "or priciest station in the list — an outlier station shouldn't "
    "decide the comparison, and you're not reliable at judging that by "
    "eye anyway.\n"
    "In both cases, when the tool's response includes a sorted_by "
    "field, or was filtered by brand_tier, treat its stations list as "
    "already correct — relay it in the order given, don't reorder, "
    "re-filter, or second-guess it.\n\n"
    "After the tool responds, base your answer strictly on the stations "
    "it returned — mention only those exact stations, with their real "
    "prices and distances, and never add, guess at, or invent any "
    "others, even if the user seems to expect more results. A station "
    "can have a connected_brand — e.g. an Esso-branded pump at a Circle "
    "K storefront — which counts as a match if the user asked for that "
    "connected brand; when it does, say so explicitly (e.g. 'Esso "
    "(Circle K) at 0.7 mi') so the user understands why it matched. If "
    "the tool reports no location is available, say so plainly and ask the user "
    "to share their location or name a place. If the tool reports that "
    "no stations matched (e.g. none of a requested brand or brand tier, "
    "none within a requested distance, or none reporting a price for "
    "the requested fuel grade), say so plainly and suggest trying a "
    "different brand, a wider distance, a different grade, or no filter "
    "at all, rather than guessing or inventing a match. If the tool "
    "reports an error, apologize briefly and suggest trying again "
    "shortly, without "
    "exposing technical details.\n\n"
    "For anything unrelated to real-time station data, answer from "
    "general knowledge as usual, or say so if you can't help."
)


class ChatError(Exception):
    """Raised when the chat completion request fails."""


class RateLimitError(ChatError):
    """Raised specifically when Groq reports its own rate limit was hit
    (HTTP 429) — handled distinctly in send() so the user gets a normal
    chat reply (RATE_LIMIT_MESSAGE) instead of the generic error banner
    every other ChatError produces via the /chat route."""


@dataclass
class _StationLookupOutcome:
    stations: list[GasStation]
    lat: float
    lon: float
    # Total raw stations fetched (across 1 or 2 pages) before filtering —
    # surfaced in a "no matches" message so it's clear how wide a net was
    # actually cast, not just that nothing matched.
    scanned_count: int
    # False only if GasBuddy returned zero raw stations at all (distinct
    # from "some stations exist nearby, just none matched the filter").
    any_nearby: bool


def _extract_error_message(response: httpx.Response) -> str | None:
    try:
        return response.json()["error"]["message"]
    except (KeyError, TypeError, ValueError):
        return None


def _normalize_brand_text(value: str) -> str:
    return re.sub(r"[-\s]+", " ", value.strip().lower())


def _brand_matches(station: GasStation, brand_query: str) -> bool:
    query = _normalize_brand_text(brand_query)
    if not query:
        return False
    for candidate in (station.brand, station.name, station.connected_brand):
        if not candidate:
            continue
        normalized = _normalize_brand_text(candidate)
        if query in normalized or normalized in query:
            return True
    return False


def _matches_any_brand(station: GasStation, brands: list[str]) -> bool:
    return any(_brand_matches(station, b) for b in brands)


def _is_major_brand(station: GasStation) -> bool:
    """The code-side replacement for asking the model to judge which
    brands count as "big name" — reuses the same matching logic as an
    explicit `brand` filter, just checked against every entry in
    WELL_KNOWN_BRANDS instead of one specific name."""
    return any(_brand_matches(station, known) for known in WELL_KNOWN_BRANDS)


def _matches_brand_tier(station: GasStation, brand_tier: str) -> bool:
    is_major = _is_major_brand(station)
    return is_major if brand_tier == "major" else not is_major


def _filter_stations(
    stations: list[GasStation],
    brands: list[str] | None,
    max_distance_miles: float | None,
    brand_tier: str | None = None,
) -> list[GasStation]:
    filtered = stations
    if brands:
        filtered = [s for s in filtered if _matches_any_brand(s, brands)]
    if brand_tier:
        filtered = [s for s in filtered if _matches_brand_tier(s, brand_tier)]
    if max_distance_miles is not None:
        filtered = [
            s
            for s in filtered
            if s.distance_miles is not None and s.distance_miles <= max_distance_miles
        ]
    return filtered


def _page1_exceeds_distance(
    stations: list[GasStation], max_distance_miles: float
) -> bool:
    if not stations:
        return False
    farthest = stations[-1].distance_miles
    # An unexpected missing distance can't confirm full coverage of the
    # requested radius — err toward fetching page 2 rather than risk
    # missing a match.
    if farthest is None:
        return False
    return farthest > max_distance_miles


def _needs_second_page(
    page1_stations: list[GasStation],
    brands: list[str] | None,
    max_distance_miles: float | None,
    station_count: int | None,
    brand_tier: str | None = None,
) -> bool:
    # Distance, when given, is the sole authority — it always decides
    # whether a second page is fetched, regardless of brand/brand_tier/
    # count. This is what makes "nearest brand within distance" fetch a
    # second page even after the brand was already found in page 1, if
    # page 1 hasn't yet covered the requested radius.
    if max_distance_miles is not None:
        return not _page1_exceeds_distance(page1_stations, max_distance_miles)
    if brands or brand_tier:
        matches = [
            s
            for s in page1_stations
            if (not brands or _matches_any_brand(s, brands))
            and (not brand_tier or _matches_brand_tier(s, brand_tier))
        ]
        if station_count is not None:
            return len(matches) < station_count
        if brands and len(brands) > 1:
            # No count given: with several distinct brands requested,
            # keep fetching until EVERY one of them has at least one
            # match — otherwise "Shell and Petro-Canada" could stop as
            # soon as Shell alone was found on page 1.
            return not all(
                any(_brand_matches(s, b) for s in page1_stations) for b in brands
            )
        return len(matches) < 1
    # Unreachable in practice: this function is only called when brand,
    # brand_tier, and/or max_distance_miles is set (see
    # _execute_tool_call), so one of the two branches above always
    # applies.
    return False


def _brand_descriptor(brands: list[str] | None, brand_tier: str | None) -> str | None:
    if brands:
        if len(brands) == 1:
            return brands[0]
        if len(brands) == 2:
            return f"{brands[0]} or {brands[1]}"
        return f"{', '.join(brands[:-1])}, or {brands[-1]}"
    if brand_tier == "major":
        return "major-brand"
    if brand_tier == "lesser_known":
        return "independent/lesser-known"
    return None


def _no_match_message(
    brands: list[str] | None,
    max_distance_miles: float | None,
    any_nearby: bool,
    scanned_count: int,
    brand_tier: str | None = None,
) -> str:
    if not any_nearby:
        return "No gas stations were found near that location at all."
    descriptor = _brand_descriptor(brands, brand_tier)
    if descriptor and max_distance_miles is not None:
        return (
            f"No {descriptor} stations were found within "
            f"{max_distance_miles} miles, among the {scanned_count} "
            "nearest stations checked."
        )
    if descriptor:
        return (
            f"No {descriptor} stations were found among the "
            f"{scanned_count} nearest stations checked."
        )
    if max_distance_miles is not None:
        return (
            f"No stations were found within {max_distance_miles} miles of "
            f"that location (checked the {scanned_count} nearest stations)."
        )
    return "No stations matched the requested filters."


def _no_fuel_grade_message(fuel_grade: str, scanned_count: int) -> str:
    return (
        f"None of the {scanned_count} nearby stations checked report a "
        f"{fuel_grade} price right now."
    )


def _sort_by_fuel_grade(
    stations: list[GasStation], fuel_grade: str
) -> list[GasStation]:
    """Sorts stations by a given grade's price, cheapest first — the
    deterministic replacement for asking the model to compare prices by
    eye, which is unreliable over more than a couple of closely-priced
    options. A station with no price for this grade can't be ranked, so
    it's dropped entirely rather than sorted to one end — a "cheapest
    premium" answer should never surface a station that doesn't report a
    premium price at all."""
    priced = [
        s
        for s in stations
        if getattr(s, fuel_grade) is not None
        and getattr(s, fuel_grade).price is not None
    ]
    return sorted(priced, key=lambda s: getattr(s, fuel_grade).price)


def _average_fuel_price(
    priced_stations: list[GasStation], fuel_grade: str
) -> tuple[float, str | None] | None:
    """The average price for a grade across a set of stations that all
    already report it (i.e. the output of _sort_by_fuel_grade, BEFORE any
    station_count cap is applied) — the deterministic basis for judging
    which of several places is cheaper overall, rather than the model
    comparing individual stations by eye, where a single unusually cheap
    or expensive outlier can make one place look cheaper/pricier than it
    typically is. Returns (raw_average, formatted_average), or None for
    an empty list."""
    if not priced_stations:
        return None
    prices = [getattr(s, fuel_grade).price for s in priced_stations]
    average = sum(prices) / len(prices)
    sample_format = next(
        (
            getattr(s, fuel_grade).formatted_price
            for s in priced_stations
            if getattr(s, fuel_grade).formatted_price
        ),
        None,
    )
    return average, format_price_like(sample_format, average)


def _coerce_positive_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value > 0 and value.is_integer():
        return int(value)
    return None


def _coerce_fuel_grade(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in VALID_FUEL_GRADES else None


def _coerce_brand_tier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in VALID_BRAND_TIERS else None


def _coerce_brand_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    names = [v.strip() for v in value if isinstance(v, str) and v.strip()]
    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        key = _normalize_brand_text(name)
        if key not in seen:
            seen.add(key)
            deduped.append(name)
    return deduped or None


def _coerce_location_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    seen: set[str] = set()
    places: list[str] = []
    for v in value:
        if not isinstance(v, str):
            continue
        stripped = v.strip()
        if not stripped:
            continue
        key = stripped.lower()
        if key in seen:
            continue
        seen.add(key)
        places.append(stripped)
    return places or None


def _station_summary(s: GasStation) -> dict[str, Any]:
    return {
        "name": s.name,
        "brand": s.brand,
        # GasBuddy often lists a second brand for the same station (e.g.
        # an Esso-branded pump at a Circle K storefront) — surfaced so the
        # model can actually explain *why* a station matched a brand
        # filter that only hit on this field, rather than the match being
        # invisible to it.
        "connected_brand": s.connected_brand,
        "address": s.address,
        "distance_miles": s.distance_miles,
        "regular_price": s.regular.formatted_price if s.regular else None,
        "midgrade_price": s.midgrade.formatted_price if s.midgrade else None,
        "premium_price": s.premium.formatted_price if s.premium else None,
        "diesel_price": s.diesel.formatted_price if s.diesel else None,
        "star_rating": s.star_rating,
    }


def _compact_station_summary(
    s: GasStation, fuel_grade: str, include_connected_brand: bool
) -> dict[str, Any]:
    """A smaller alternative to _station_summary — used only in a
    locations comparison when fuel_grade already narrows the question
    down to one specific price, so the other three grade prices and
    star_rating (irrelevant to that question) aren't repeated for every
    station across every place, which is what was inflating the final
    round's prompt. connected_brand is kept only when a brand/brand_tier
    filter is also active, since that's the only case where it explains
    why a station matched at all (see _station_summary's own comment)."""
    grade_price = getattr(s, fuel_grade)
    summary: dict[str, Any] = {
        "name": s.name,
        "brand": s.brand,
        "address": s.address,
        "distance_miles": s.distance_miles,
        f"{fuel_grade}_price": grade_price.formatted_price if grade_price else None,
    }
    if include_connected_brand:
        summary["connected_brand"] = s.connected_brand
    return summary


def _stations_tool_payload(
    stations: list[GasStation],
    lat: float,
    lon: float,
    *,
    brands: list[str] | None = None,
    brand_tier: str | None = None,
    max_distance_miles: float | None = None,
    station_count: int | None = None,
    fuel_grade: str | None = None,
) -> dict[str, Any]:
    display_stations = stations
    cheapest: dict[str, Any] | None = None
    include_connected_brand = bool(brands) or brand_tier is not None

    if fuel_grade and stations:
        # stations is already sorted cheapest-first for this grade (see
        # _sort_by_fuel_grade) — the code identifies the actual cheapest
        # station explicitly here, rather than relying on the model to
        # notice the list is sorted and correctly relay entry #1 itself.
        cheapest = _compact_station_summary(
            stations[0], fuel_grade, include_connected_brand
        )
        if station_count is None:
            # No explicit count was requested — the model no longer
            # needs the full scanned sample just to find the cheapest
            # one now that it's given directly above, so only a small
            # supporting list of alternatives is included.
            display_stations = stations[:FUEL_GRADE_DISPLAY_CAP]

    if fuel_grade:
        station_dicts = [
            _compact_station_summary(s, fuel_grade, include_connected_brand)
            for s in display_stations
        ]
    else:
        station_dicts = [_station_summary(s) for s in display_stations]

    payload: dict[str, Any] = {
        "searched_lat": lat,
        "searched_lon": lon,
        "station_count": len(display_stations),
        "stations": station_dicts,
    }
    if fuel_grade:
        # An explicit instruction, not just data — the model is unreliable
        # at comparing many prices itself (see SYSTEM_PROMPT), so this
        # spells out that the order below is already correct.
        payload["sorted_by"] = (
            f"{fuel_grade}_price ascending (cheapest first) — the list "
            "below is already in this exact order; relay it as-is, do "
            "not re-sort or recompute the ranking"
        )
    if cheapest is not None:
        payload["cheapest"] = cheapest
        payload["cheapest_note"] = (
            f"This IS the cheapest {fuel_grade} station found — for a "
            "'cheapest'/'lowest price' question, answer directly from "
            "this field rather than scanning the stations list yourself "
            "to find it, and don't second-guess it."
        )
    filters_applied: dict[str, Any] = {}
    if brands:
        filters_applied["brands"] = brands
    if brand_tier:
        filters_applied["brand_tier"] = brand_tier
    if max_distance_miles is not None:
        filters_applied["max_distance_miles"] = max_distance_miles
    if station_count is not None:
        filters_applied["station_count"] = station_count
    if fuel_grade:
        filters_applied["fuel_grade"] = fuel_grade
    if filters_applied:
        payload["filters_applied"] = filters_applied
    return payload


class ChatService:
    def __init__(self, gasbuddy: GasBuddyService) -> None:
        settings = get_settings()
        self._api_key = settings.groq_api_key
        self._model = settings.groq_model
        self._gasbuddy = gasbuddy

    async def send(
        self,
        messages: list[ChatMessage],
        location: tuple[float, float] | None = None,
    ) -> ChatMessage:
        """Send the conversation so far to Groq and return the agent's final
        reply, running its station-lookup tool as many times as it asks to
        (bounded by MAX_TOOL_ROUNDS).

        Raises ChatError on any failure. An *invalid* key is left for Groq
        itself to reject (confirmed live: a 401) rather than this doing its
        own validation — but a *missing* key needs its own check first,
        since an empty key produces an "Authorization: Bearer " header that
        httpx's own http.client rejects locally (confirmed live) with a
        confusing low-level error, before any request is even sent.
        """
        if not self._api_key:
            raise ChatError(
                "Chat isn't configured: set GROQ_API_KEY in backend/.env."
            )

        conversation: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *({"role": m.role, "content": m.content} for m in messages),
        ]

        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            include_tools = round_num < MAX_TOOL_ROUNDS
            try:
                message = await self._call_groq(
                    conversation, tools=TOOLS if include_tools else None
                )
            except RateLimitError:
                # Routine under the free/on-demand tier's tight caps, not
                # a real failure — a normal chat reply reads far better
                # than the generic error banner every other ChatError
                # produces via the /chat route.
                return ChatMessage(role="assistant", content=RATE_LIMIT_MESSAGE)

            tool_calls = message.get("tool_calls")
            if not tool_calls:
                content = message.get("content")
                if not content:
                    raise ChatError("Groq returned an unexpected response shape.")
                return ChatMessage(role="assistant", content=content)

            assistant_entry: dict[str, Any] = {
                "role": "assistant",
                "tool_calls": tool_calls,
            }
            if message.get("content"):
                assistant_entry["content"] = message["content"]
            conversation.append(assistant_entry)

            for tool_call in tool_calls:
                conversation.append(
                    await self._execute_tool_call(tool_call, location)
                )

        # Unreachable: the final round never includes `tools`, so Groq
        # cannot return tool_calls on it — the loop above always returns
        # before falling off the end.
        raise ChatError("Groq returned an unexpected response shape.")

    async def _call_groq(
        self, conversation: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self._model, "messages": conversation}
        if tools:
            payload["tools"] = tools
        headers = {"Authorization": f"Bearer {self._api_key}"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(GROQ_URL, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = _extract_error_message(exc.response) or (
                f"Groq request failed with status {exc.response.status_code}."
            )
            if exc.response.status_code == 429:
                raise RateLimitError(detail) from exc
            raise ChatError(detail) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ChatError(f"Groq request failed: {exc}") from exc

        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ChatError("Groq returned an unexpected response shape.") from exc

    async def _fetch_and_filter_stations(
        self,
        *,
        query: str | None,
        lat: float | None,
        lon: float | None,
        brands: list[str] | None,
        max_distance_miles: float | None,
        station_count: int | None,
        brand_tier: str | None = None,
        cap_by_count: bool = True,
    ) -> _StationLookupOutcome:
        # Callers only route here when brands, brand_tier, and/or
        # max_distance_miles is set (see _execute_tool_call) — a
        # standalone station_count/fuel_grade with none of those never
        # reaches this method at all, so there's no count-only
        # single-page short-circuit to handle here.
        page1 = await self._gasbuddy.search_nearest_stations(
            query=query, lat=lat, lon=lon, limit=GASBUDDY_PAGE_SIZE
        )
        if not page1.stations:
            return _StationLookupOutcome(
                stations=[],
                lat=page1.lat,
                lon=page1.lon,
                scanned_count=0,
                any_nearby=False,
            )

        all_stations = list(page1.stations)
        if page1.next_cursor is not None and _needs_second_page(
            page1.stations, brands, max_distance_miles, station_count, brand_tier
        ):
            await asyncio.sleep(SECOND_PAGE_PAUSE_SECONDS)
            page2 = await self._gasbuddy.search_nearest_stations(
                lat=page1.lat,
                lon=page1.lon,
                limit=GASBUDDY_PAGE_SIZE,
                cursor=page1.next_cursor,
            )
            all_stations.extend(page2.stations)

        filtered = _filter_stations(
            all_stations, brands, max_distance_miles, brand_tier
        )
        # When a fuel_grade sort is also being applied, the caller passes
        # cap_by_count=False so the count is applied AFTER sorting by
        # price, not before — station_count is still used above to decide
        # whether a second page was worth fetching, just not to truncate
        # this list yet.
        if cap_by_count and station_count is not None:
            filtered = filtered[:station_count]
        return _StationLookupOutcome(
            stations=filtered,
            lat=page1.lat,
            lon=page1.lon,
            scanned_count=len(all_stations),
            any_nearby=True,
        )

    async def _lookup_stations(
        self,
        *,
        query: str | None,
        lat: float | None,
        lon: float | None,
        brands: list[str] | None,
        brand_tier: str | None,
        max_distance_miles: float | None,
        station_count: int | None,
        fuel_grade: str | None,
    ) -> tuple[
        list[GasStation],
        float | None,
        float | None,
        str | None,
        tuple[float, str | None] | None,
    ]:
        """The fetch+filter+sort+cap pipeline for ONE place — shared by
        both the single-place path and the per-place loop in
        _execute_multi_location_lookup, so a multi-location comparison
        gets exactly the same behavior per place as a single-location
        lookup would. Returns (stations, lat, lon, error_message,
        average_price_info); error_message is set (stations empty) when
        nothing matched this place specifically. average_price_info is
        (raw_average, formatted_average) computed across every priced
        match BEFORE any station_count cap (so a "top N cheapest" cap
        can't bias it toward the cheap end) when fuel_grade is set, else
        None. Doesn't catch GeocodingError/CloudflareBlocked/etc. itself
        — those propagate to the caller."""
        has_filters = (
            bool(brands) or brand_tier is not None or max_distance_miles is not None
        )
        if has_filters:
            outcome = await self._fetch_and_filter_stations(
                query=query,
                lat=lat,
                lon=lon,
                brands=brands,
                max_distance_miles=max_distance_miles,
                station_count=station_count,
                brand_tier=brand_tier,
                # A fuel_grade sort must cap by count AFTER sorting by
                # price (below), not before — otherwise station_count
                # could cut off a genuinely cheaper station that just
                # wasn't first in GasBuddy's own distance-based order.
                cap_by_count=fuel_grade is None,
            )
            stations = outcome.stations
            average_price_info = None
            if fuel_grade and stations:
                stations = _sort_by_fuel_grade(stations, fuel_grade)
                average_price_info = _average_fuel_price(stations, fuel_grade)
                if station_count is not None:
                    stations = stations[:station_count]

            if not stations:
                if outcome.stations and fuel_grade:
                    # Real brand/distance matches existed; none of them
                    # reported this specific fuel grade's price.
                    return (
                        [],
                        outcome.lat,
                        outcome.lon,
                        _no_fuel_grade_message(fuel_grade, len(outcome.stations)),
                        None,
                    )
                return (
                    [],
                    outcome.lat,
                    outcome.lon,
                    _no_match_message(
                        brands,
                        max_distance_miles,
                        outcome.any_nearby,
                        outcome.scanned_count,
                        brand_tier,
                    ),
                    None,
                )
            return stations, outcome.lat, outcome.lon, None, average_price_info

        # No brand/brand_tier/distance filter (station_count and/or
        # fuel_grade alone, or no arguments at all) — always fetch the
        # full single-page sample rather than a smaller slice, so there's
        # real, complete data to sort/answer from instead of only
        # whatever a fixed default or a self-chosen count let the model
        # see.
        result = await self._gasbuddy.search_nearest_stations(
            query=query, lat=lat, lon=lon, limit=GASBUDDY_PAGE_SIZE
        )
        stations = result.stations
        average_price_info = None
        if fuel_grade:
            stations = _sort_by_fuel_grade(stations, fuel_grade)
            average_price_info = _average_fuel_price(stations, fuel_grade)
            if station_count is not None:
                stations = stations[:station_count]

        if fuel_grade and not stations:
            return (
                [],
                result.lat,
                result.lon,
                _no_fuel_grade_message(fuel_grade, len(result.stations)),
                None,
            )
        return stations, result.lat, result.lon, None, average_price_info

    async def _execute_multi_location_lookup(
        self,
        places: list[str],
        brands: list[str] | None,
        brand_tier: str | None,
        max_distance_miles: float | None,
        station_count: int | None,
        fuel_grade: str | None,
    ) -> dict[str, Any]:
        """Runs _lookup_stations independently per named place and merges
        the results, grouped by place, so the model can compare across
        them in one round-trip instead of one tool call per place. An
        unresolvable place name only fails that one place — the rest
        still come back — but any other failure (GasBuddy itself down,
        etc.) propagates to _execute_tool_call's own exception handling,
        same as the single-location path."""
        results_by_location: dict[str, Any] = {}
        for place in places:
            try:
                (
                    stations,
                    res_lat,
                    res_lon,
                    error,
                    average_price_info,
                ) = await self._lookup_stations(
                    query=place,
                    lat=None,
                    lon=None,
                    brands=brands,
                    brand_tier=brand_tier,
                    max_distance_miles=max_distance_miles,
                    station_count=station_count,
                    fuel_grade=fuel_grade,
                )
            except GeocodingError as exc:
                results_by_location[place] = {"error": str(exc)}
                continue
            if error:
                results_by_location[place] = {"error": error}
            else:
                display_stations = stations
                if fuel_grade and station_count is None:
                    # The model didn't ask for a specific count — cap what
                    # gets echoed back rather than the full scanned page.
                    # Safe to do here, after the fact: average_price (set
                    # below) was already computed from the full sample
                    # inside _lookup_stations, so this can't skew it, and
                    # `stations` is already cheapest-first for this grade,
                    # so the cap keeps the most relevant ones anyway.
                    display_stations = stations[:FUEL_GRADE_DISPLAY_CAP]

                if fuel_grade:
                    include_connected_brand = (
                        bool(brands) or brand_tier is not None
                    )
                    station_dicts = [
                        _compact_station_summary(
                            s, fuel_grade, include_connected_brand
                        )
                        for s in display_stations
                    ]
                else:
                    station_dicts = [_station_summary(s) for s in display_stations]

                place_result: dict[str, Any] = {
                    "station_count": len(display_stations),
                    "stations": station_dicts,
                }
                if average_price_info is not None:
                    average, average_formatted = average_price_info
                    place_result["average_price"] = average
                    place_result["average_price_formatted"] = average_formatted
                results_by_location[place] = place_result

        content: dict[str, Any] = {
            "searched_locations": places,
            "results_by_location": results_by_location,
        }
        if fuel_grade:
            content["sorted_by"] = (
                f"{fuel_grade}_price ascending (cheapest first) WITHIN "
                "each place's own list — already sorted; relay as-is, do "
                "not re-sort or recompute the ranking"
            )
            content["comparison_note"] = (
                "Each place's average_price (for this fuel grade, across "
                "every matching station found there) is the correct basis "
                "for judging which place is cheaper OVERALL — a single "
                "unusually cheap or expensive station in one place "
                "shouldn't decide that comparison. Only use the individual "
                "stations list to recommend one specific station, never "
                "to judge which place is cheaper by eyeballing entries."
            )
        filters_applied: dict[str, Any] = {}
        if brands:
            filters_applied["brands"] = brands
        if brand_tier:
            filters_applied["brand_tier"] = brand_tier
        if max_distance_miles is not None:
            filters_applied["max_distance_miles"] = max_distance_miles
        if station_count is not None:
            filters_applied["station_count_per_location"] = station_count
        if fuel_grade:
            filters_applied["fuel_grade"] = fuel_grade
        if filters_applied:
            content["filters_applied"] = filters_applied
        return content

    async def _execute_tool_call(
        self, tool_call: dict[str, Any], location: tuple[float, float] | None
    ) -> dict[str, Any]:
        """Runs one tool call and returns the `role: tool` message to feed
        back to Groq. Never raises — any failure becomes an error message
        for the model to relay, so one bad tool call can't crash the whole
        chat request."""
        call_id = tool_call["id"]
        name = tool_call["function"]["name"]

        if name != "find_nearby_gas_stations":
            return self._tool_message(
                call_id, name, {"error": f"Unknown tool '{name}'."}
            )

        try:
            args = json.loads(tool_call["function"].get("arguments") or "{}")
        except ValueError:
            return self._tool_message(
                call_id, name, {"error": "Could not parse tool arguments."}
            )

        place = args.get("location") or None
        places = _coerce_location_list(args.get("locations"))
        # `locations` wins if the model sets both (against the schema's
        # own instructions) — same precedence rule as brand/brands.
        resolved_places = places or ([place] if place else None)
        brand = args.get("brand") or None
        # `brands` wins if the model sets both (against the schema's own
        # instructions) — the plural, more-specific intent takes
        # precedence rather than silently dropping it.
        brand_list = _coerce_brand_list(args.get("brands")) or (
            [brand] if brand else None
        )
        brand_tier = _coerce_brand_tier(args.get("brand_tier"))
        max_distance_miles = _coerce_positive_number(args.get("max_distance_miles"))
        station_count = _coerce_positive_int(args.get("station_count"))
        fuel_grade = _coerce_fuel_grade(args.get("fuel_grade"))
        # station_count deliberately does NOT count as a "filter" on its
        # own — a standalone count (whether the user actually asked for
        # one, or the model picked one unprompted) no longer caps the
        # result; only brand(s)/brand_tier/distance route into the
        # narrower, capped _fetch_and_filter_stations path. fuel_grade
        # likewise doesn't affect how many pages get fetched, only how
        # the result is sorted/trimmed afterward (see below) — this keeps
        # a "cheapest"/"best" style question answered from the tool's
        # full nearby sample rather than an arbitrarily small slice.
        has_filters = (
            bool(brand_list)
            or brand_tier is not None
            or max_distance_miles is not None
        )

        content: dict[str, Any]
        try:
            if resolved_places and len(resolved_places) > 1:
                content = await self._execute_multi_location_lookup(
                    resolved_places,
                    brand_list,
                    brand_tier,
                    max_distance_miles,
                    station_count,
                    fuel_grade,
                )
            else:
                single_place = resolved_places[0] if resolved_places else None
                if single_place:
                    query, lat, lon = single_place, None, None
                elif location is not None:
                    query, lat, lon = None, location[0], location[1]
                else:
                    return self._tool_message(
                        call_id, name, {"error": NO_LOCATION_MESSAGE}
                    )

                # The 5th value (average_price_info) only matters for
                # comparing across several places — see
                # _execute_multi_location_lookup, which is what actually
                # uses it; a single place has nothing to compare against.
                stations, res_lat, res_lon, error, _ = await self._lookup_stations(
                    query=query,
                    lat=lat,
                    lon=lon,
                    brands=brand_list,
                    brand_tier=brand_tier,
                    max_distance_miles=max_distance_miles,
                    station_count=station_count,
                    fuel_grade=fuel_grade,
                )
                if error:
                    content = {"error": error}
                else:
                    # station_count only appears in filters_applied when
                    # it actually did something — a standalone count with
                    # no brand/tier/distance/fuel_grade is silently
                    # ignored (see _lookup_stations), same as before.
                    payload_station_count = (
                        station_count if (has_filters or fuel_grade) else None
                    )
                    content = _stations_tool_payload(
                        stations,
                        res_lat,
                        res_lon,
                        brands=brand_list,
                        brand_tier=brand_tier,
                        max_distance_miles=max_distance_miles,
                        station_count=payload_station_count,
                        fuel_grade=fuel_grade,
                    )
        except GeocodingError as exc:
            content = {"error": str(exc)}
        except MissingSearchData:
            content = {"error": "Missing search parameters for that location."}
        except CloudflareBlocked:
            content = {
                "error": (
                    "GasBuddy is temporarily blocking automated requests. "
                    "Try again shortly."
                )
            }
        except (LibraryError, APIError) as exc:
            content = {"error": f"GasBuddy lookup failed: {exc}"}
        except Exception as exc:  # a tool call must never crash the whole request
            content = {"error": f"Station lookup failed unexpectedly: {exc}"}

        return self._tool_message(call_id, name, content)

    def _tool_message(
        self, call_id: str, name: str, content: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": json.dumps(content),
        }


def get_chat_service(
    gasbuddy: GasBuddyService = Depends(get_gasbuddy_service),
) -> ChatService:
    return ChatService(gasbuddy)
