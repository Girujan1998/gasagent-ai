import asyncio
import re
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

# The classic generateContent REST shape — Google's newer "Interactions
# API" is now GA and recommended for new work, but it's stateful (keeps
# conversation history server-side) and needs the google-genai SDK rather
# than plain HTTP. generateContent stays close to this app's existing
# "resend the whole conversation every time" design and needs no SDK at
# all, just httpx, so it's the starting point for this scaffold.
GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# Started as a single, deliberately minimal tool with just `location`, to
# prove the function-calling round-trip works end to end against
# Gemini's request/response shape. brands/exclude_brands/max_distance_
# miles/fuel_grade below rebuild the filtering/sorting the earlier Groq-
# backed tool had — done in code here too, never left for the model to
# judge by reading a raw station list itself.
FIND_STATIONS_TOOL: dict[str, Any] = {
    "functionDeclarations": [
        {
            "name": "find_nearby_gas_stations",
            "description": (
                "Look up real, current gas stations and their live fuel "
                "prices near a location, using the app's own GasBuddy "
                "integration. Supports optional filters — one or more "
                "brands to include, one or more brands to exclude, a "
                "brand recognition tier (major-chain vs. independent), "
                "a maximum distance in miles, and/or a fuel grade to "
                "sort by price — pass only the ones the user actually "
                "asked for. Call this whenever the user asks about "
                "nearby gas stations or gas prices — never answer such "
                "questions from general knowledge or invent station "
                "names, addresses, or prices; never filter, exclude, "
                "sort, or rank stations yourself, and never judge "
                "yourself whether a brand counts as a 'big name' or not "
                "(always pass brand_tier instead) — the tool does all "
                "of that for you. Not for EV charging."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": (
                            "A specific place to search near — a city, "
                            "neighborhood, postal code, or address — "
                            "ONLY when the user named one explicitly "
                            "(e.g. 'Toronto', 'near 90210'). Omit this "
                            "entirely when the user means their own "
                            "current location ('near me', 'nearby', "
                            "'around here', or no place mentioned at "
                            "all) — the backend already knows the "
                            "user's current location and will use it "
                            "automatically."
                        ),
                    },
                    "brands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "One or more specific gas brands or chains "
                            "to INCLUDE — e.g. ['Shell'] for one brand, "
                            "['Shell', 'Petro-Canada'] for several. "
                            "Always pass this as a list, even for a "
                            "single brand. A station matching ANY listed "
                            "brand is included. Omit entirely when the "
                            "user didn't name a specific brand to look "
                            "for."
                        ),
                    },
                    "exclude_brands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "One or more specific gas brands or chains "
                            "to EXCLUDE — e.g. ['Petro-Canada', 'Shell'] "
                            "for 'gas stations near me that are not "
                            "Petro-Canada or Shell'. A station matching "
                            "ANY listed brand here is removed. Use this "
                            "whenever the user says 'not X', 'excluding "
                            "X', or 'other than X'. Omit entirely when "
                            "the user didn't ask to exclude any brand."
                        ),
                    },
                    "max_distance_miles": {
                        "type": "number",
                        "description": (
                            "Only include stations within this many "
                            "miles of the searched location — ONLY when "
                            "the user gave an explicit distance or "
                            "radius ('within 5 miles', 'closer than 2 "
                            "miles'). Omit entirely when no distance was "
                            "mentioned."
                        ),
                    },
                    "fuel_grade": {
                        "type": "string",
                        "enum": ["regular", "midgrade", "premium", "diesel"],
                        "description": (
                            "Pass this whenever the user asks about the "
                            "cheapest/lowest-priced gas, the average "
                            "price, or names a specific grade's price "
                            "('cheapest gas near me', 'average price of "
                            "Esso nearby', 'lowest premium price'). For "
                            "a plain 'cheapest gas' with no grade named, "
                            "use 'regular'. The tool's response then "
                            "includes an explicit cheapest field (the "
                            "actual cheapest matching station) and an "
                            "average_price field, computed for you — "
                            "answer directly from those fields for a "
                            "'cheapest' or 'average price' question, "
                            "never by comparing prices in the stations "
                            "list yourself. Omit entirely when the user "
                            "isn't asking about price ranking at all."
                        ),
                    },
                    "brand_tier": {
                        "type": "string",
                        "enum": ["major", "lesser_known"],
                        "description": (
                            "Pass 'major' when the user asks for a 'big "
                            "name', 'major', 'well-known', or 'name-"
                            "brand' station without naming one "
                            "specifically. Pass 'lesser_known' when the "
                            "user asks for an independent, local, non-"
                            "chain, or 'lesser-known' station instead. "
                            "The tool checks each station against its "
                            "own list of recognized major chains — you "
                            "don't need to judge or recall which brands "
                            "count yourself, and shouldn't guess. Don't "
                            "combine with brands/exclude_brands — use "
                            "those instead when the user names one or "
                            "more specific brands. Omit entirely for a "
                            "plain search with no brand-tier preference."
                        ),
                    },
                },
                "required": [],
            },
        }
    ]
}
TOOLS = [FIND_STATIONS_TOOL]

# Bounds worst-case GasBuddy calls per user turn the same way as before:
# rounds 1-2 offer the tool; round 3 omits `tools` entirely, which should
# make it structurally impossible for Gemini to return another
# functionCall on that round (confirmed live on Groq/OpenAI-compatible
# APIs for the equivalent case; not yet independently re-confirmed for
# Gemini specifically).
MAX_TOOL_ROUNDS = 3

# The pause before fetching a second page of stations (brands/distance
# lookups only) — py-gasbuddy is an unofficial scraper of GasBuddy's
# internal API, so two rapid-fire requests in the same tool call look
# more like a scripted burst than a second page ever does on its own.
# Only ever awaited immediately before a genuinely-needed second-page
# fetch (see _needs_second_page), never speculatively.
SECOND_PAGE_PAUSE_SECONDS = 1.0

# Matches the GasStation attribute names for each grade's FuelPrice field,
# so a validated fuel_grade string can be used directly with getattr().
VALID_FUEL_GRADES = {"regular", "midgrade", "premium", "diesel"}

VALID_BRAND_TIERS = {"major", "lesser_known"}

# Mirrors mobile/src/utils/brandFilter.ts's WELL_KNOWN_BRANDS — the same
# recognized-chain list the Gas tab's own brand filter uses. Used by
# _is_major_brand to classify a station for the brand_tier filter in
# code, rather than asking the model to judge membership itself (which,
# on the earlier Groq-backed version of this tool, didn't reliably
# recognize regional chains like Pioneer or Canadian Tire as "major"
# until they were added here explicitly). Keep in sync with the mobile
# list.
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

# Confirmed live: Gemini occasionally times out or returns a transient
# 5xx (server overload) even on an otherwise-normal request. A single
# retry (2 attempts total, 30s timeout) still let a 502 through — the
# retry attempt hit a second, back-to-back ReadTimeout — so this allows 2
# retries (3 attempts total) at a longer 60s timeout each, since back-to-
# back timeouts aren't necessarily independent one-off blips and a
# bigger round 2 request (more prompt data, more "thinking") can
# genuinely take longer to complete on its own.
GEMINI_REQUEST_TIMEOUT_SECONDS = 60.0
GEMINI_MAX_ATTEMPTS = 3
GEMINI_RETRY_PAUSE_SECONDS = 1.0

NO_LOCATION_MESSAGE = (
    "No location is available for this user right now — the app hasn't "
    "shared a current location, and no place was named. Ask the user to "
    "share their location or name a city, postal code, or address."
)

# Shown as a normal assistant reply (not an error banner) when the
# provider itself reports a rate limit (HTTP 429) — routine under a free
# tier's tight caps, not a real failure, so the user gets an actionable
# suggestion in the chat instead of a scary error.
RATE_LIMIT_MESSAGE = (
    "You have hit the model limit with this request, please breakdown "
    "the request into 2 or more parts."
)

SYSTEM_PROMPT = (
    "You are the in-app assistant for GasAgent.ai, a mobile app for "
    "finding nearby gas prices and EV charging stations. Be concise and "
    "friendly.\n\n"
    "Your replies are shown as plain text in a mobile chat bubble with no "
    "markdown rendering — never use markdown tables, headers, or "
    "asterisks for bold/italic. Write in short plain sentences or a "
    "simple list with line breaks and dashes; when listing stations, one "
    "per line (e.g. 'Shell (0.7 mi) — 168.9¢/L') rather than a table.\n\n"
    "Always relay every price exactly as the tool gave it to you — same "
    "unit (¢ or $), same number of decimal places, character for "
    "character. Never convert between cents and dollars, and never "
    "round a price for readability: Canadian prices are given in cents "
    "per litre with one decimal place specifically so that close prices "
    "stay distinguishable (e.g. 168.9¢ and 169.9¢ are different prices — "
    "rounding both to $1.69 would make them look identical and could "
    "make you recommend the wrong one as cheapest).\n\n"
    "You have a tool, find_nearby_gas_stations, that returns real, "
    "current gas stations and live fuel prices from the app's own "
    "GasBuddy integration, optionally filtered by brand, excluded "
    "brand, distance, and/or a fuel grade to sort by price. Call it "
    "whenever the user asks about nearby gas stations or gas prices.\n\n"
    "The tool does all filtering, excluding, and price-sorting itself — "
    "you only choose which arguments to pass, you never perform this "
    "work yourself:\n"
    "- A specific brand or brands named ('Shell near me', 'Shell and "
    "Petro-Canada'): pass brands as a list, even for one brand.\n"
    "- 'Not X', 'excluding X', 'other than X': pass exclude_brands as a "
    "list.\n"
    "- 'Big name'/'major'/'well-known' brand, without naming one "
    "specifically: pass brand_tier: 'major'. 'Independent'/'local'/"
    "'non-chain'/'lesser-known' stations: pass brand_tier: "
    "'lesser_known'. You don't reliably know which brands count as "
    "major, so never judge or guess this yourself — the tool checks "
    "each station against its own recognized-chain list.\n"
    "- Cheapest/lowest-priced gas, or an average price: pass fuel_grade "
    "(default to 'regular' if no grade is named), then answer strictly "
    "from the tool's cheapest and average_price fields — you are not "
    "reliable at comparing many prices by eye, so never rank, compare, "
    "or average prices yourself.\n\n"
    "After the tool responds, base your answer strictly on the stations "
    "it returned — mention only those exact stations, with their real "
    "prices and distances, and never add, guess at, or invent any "
    "others, even if the user seems to expect more results. If the tool "
    "reports no location is available, say so plainly and ask the user "
    "to share their location or name a place. If the tool reports that "
    "no stations were found, say so plainly rather than guessing or "
    "inventing a match. If the tool reports an error, apologize briefly "
    "and suggest trying again shortly, without exposing technical "
    "details.\n\n"
    "For anything unrelated to real-time station data, answer from "
    "general knowledge as usual, or say so if you can't help."
)


class ChatError(Exception):
    """Raised when the chat completion request fails."""


class RateLimitError(ChatError):
    """Raised specifically when the provider reports its own rate limit
    was hit (HTTP 429) — handled distinctly in send() so the user gets a
    normal chat reply (RATE_LIMIT_MESSAGE) instead of the generic error
    banner every other ChatError produces via the /chat route."""


def _extract_error_message(response: httpx.Response) -> str | None:
    try:
        return response.json()["error"]["message"]
    except (KeyError, TypeError, ValueError):
        return None


def _station_summary(s: GasStation) -> dict[str, Any]:
    return {
        "name": s.name,
        "brand": s.brand,
        "address": s.address,
        "distance_miles": s.distance_miles,
        "regular_price": s.regular.formatted_price if s.regular else None,
        "midgrade_price": s.midgrade.formatted_price if s.midgrade else None,
        "premium_price": s.premium.formatted_price if s.premium else None,
        "diesel_price": s.diesel.formatted_price if s.diesel else None,
    }


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
    explicit brand filter, just checked against every entry in
    WELL_KNOWN_BRANDS instead of one specific name."""
    return any(_brand_matches(station, known) for known in WELL_KNOWN_BRANDS)


def _matches_brand_tier(station: GasStation, brand_tier: str) -> bool:
    is_major = _is_major_brand(station)
    return is_major if brand_tier == "major" else not is_major


def _filter_stations(
    stations: list[GasStation],
    brands: list[str] | None,
    exclude_brands: list[str] | None,
    max_distance_miles: float | None,
    brand_tier: str | None = None,
) -> list[GasStation]:
    filtered = stations
    if brands:
        filtered = [s for s in filtered if _matches_any_brand(s, brands)]
    if exclude_brands:
        filtered = [s for s in filtered if not _matches_any_brand(s, exclude_brands)]
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
    brand_tier: str | None = None,
) -> bool:
    # Distance, when given, is the sole authority — GasBuddy returns
    # nearest-first, so once page 1's farthest station already exceeds
    # the radius, nothing on page 2 could be closer. exclude_brands and
    # fuel_grade never reach this function at all — they only filter/
    # sort whatever was already fetched, there's no target count or
    # coverage they need more data to satisfy.
    if max_distance_miles is not None:
        return not _page1_exceeds_distance(page1_stations, max_distance_miles)
    if brands:
        # Keep fetching until EVERY requested brand has at least one
        # match — otherwise "Shell and Petro-Canada" could stop as soon
        # as Shell alone was found on page 1.
        return not all(
            any(_brand_matches(s, b) for s in page1_stations) for b in brands
        )
    if brand_tier:
        return not any(_matches_brand_tier(s, brand_tier) for s in page1_stations)
    # Unreachable in practice: only called when brands, brand_tier,
    # and/or max_distance_miles is set (see _execute_tool_call).
    return False


def _brand_descriptor(brands: list[str] | None, brand_tier: str | None = None) -> str | None:
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
    exclude_brands: list[str] | None,
    max_distance_miles: float | None,
    any_nearby: bool,
    scanned_count: int,
    brand_tier: str | None = None,
) -> str:
    if not any_nearby:
        return "No gas stations were found near that location at all."
    descriptor = _brand_descriptor(brands, brand_tier)
    bits: list[str] = []
    if descriptor:
        bits.append(f"matching {descriptor}")
    if exclude_brands:
        bits.append(f"excluding {_brand_descriptor(exclude_brands)}")
    if max_distance_miles is not None:
        bits.append(f"within {max_distance_miles} miles")
    if not bits:
        return "No stations matched the requested filters."
    return (
        f"No stations {' and '.join(bits)} were found, among the "
        f"{scanned_count} nearest stations checked."
    )


def _no_fuel_grade_message(fuel_grade: str, scanned_count: int) -> str:
    return (
        f"None of the {scanned_count} matching stations checked report a "
        f"{fuel_grade} price right now."
    )


def _sort_by_fuel_grade(
    stations: list[GasStation], fuel_grade: str
) -> list[GasStation]:
    """Sorts stations by a given grade's price, cheapest first — the
    deterministic replacement for asking the model to compare prices by
    eye. A station with no price for this grade can't be ranked, so it's
    dropped entirely rather than sorted to one end."""
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
    already report it (i.e. the output of _sort_by_fuel_grade) — the
    deterministic basis for a 'what's the average price' question,
    computed once from the full matching set rather than the model
    estimating it from the list. Returns (raw_average, formatted_average),
    or None for an empty list."""
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


def _coerce_brand_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    seen: set[str] = set()
    names: list[str] = []
    for v in value:
        if not isinstance(v, str):
            continue
        stripped = v.strip()
        if not stripped:
            continue
        key = _normalize_brand_text(stripped)
        if key in seen:
            continue
        seen.add(key)
        names.append(stripped)
    return names or None


def _coerce_positive_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
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


def _to_gemini_content(message: ChatMessage) -> dict[str, Any]:
    # Gemini has no "assistant" role — its equivalent turn is "model".
    role = "model" if message.role == "assistant" else "user"
    return {"role": role, "parts": [{"text": message.content}]}


class ChatService:
    def __init__(self, gasbuddy: GasBuddyService) -> None:
        settings = get_settings()
        self._api_key = settings.gemini_api_key
        self._model = settings.gemini_model
        self._gasbuddy = gasbuddy

    async def send(
        self,
        messages: list[ChatMessage],
        location: tuple[float, float] | None = None,
    ) -> ChatMessage:
        """Send the conversation so far to Gemini and return the agent's
        final reply, running its station-lookup tool as many times as it
        asks to (bounded by MAX_TOOL_ROUNDS).

        Raises ChatError on any failure. A *missing* key is checked here
        directly (rather than letting Gemini reject an empty one) since
        Gemini takes the key as a query parameter — an empty key would
        just produce a confusing 400 from Gemini itself rather than a
        clear local error.
        """
        if not self._api_key:
            raise ChatError(
                "Chat isn't configured: set GEMINI_API_KEY in backend/.env."
            )

        contents: list[dict[str, Any]] = [_to_gemini_content(m) for m in messages]
        # Summed across every _call_gemini round for this one turn (a
        # single user message and everything it takes to answer it),
        # printed alongside each round's own usage so the per-turn cost
        # is visible without adding the per-call lines up by hand.
        turn_total_tokens = 0

        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            include_tools = round_num < MAX_TOOL_ROUNDS
            try:
                content, call_tokens = await self._call_gemini(
                    contents, tools=TOOLS if include_tools else None, round_num=round_num
                )
            except RateLimitError:
                print(
                    f"[gemini] turn total: {turn_total_tokens} tokens across "
                    f"{round_num - 1} call(s) — rate-limited on call {round_num}"
                )
                return ChatMessage(role="assistant", content=RATE_LIMIT_MESSAGE)
            turn_total_tokens += call_tokens

            parts = content.get("parts") or []
            function_calls = [p["functionCall"] for p in parts if "functionCall" in p]

            if not function_calls:
                text = "".join(p.get("text", "") for p in parts)
                if not text:
                    raise ChatError("Gemini returned an unexpected response shape.")
                print(
                    f"[gemini] turn total: {turn_total_tokens} tokens across "
                    f"{round_num} call(s)"
                )
                return ChatMessage(role="assistant", content=text)

            contents.append({"role": "model", "parts": parts})

            for call in function_calls:
                response = await self._execute_tool_call(call, location)
                contents.append(
                    # Confirmed live: this Gemini model's role enum
                    # rejects "function" (a valid role in some other
                    # Gemini API versions/docs) — "user" is what actually
                    # works for feeding a functionResponse part back.
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": call.get("name"),
                                    "response": response,
                                }
                            }
                        ],
                    }
                )

        # Unreachable: the final round never includes `tools`, so Gemini
        # cannot return a functionCall on it — the loop above always
        # returns before falling off the end.
        print(
            f"[gemini] turn total: {turn_total_tokens} tokens across "
            f"{MAX_TOOL_ROUNDS} call(s) — forced stop at the round cap"
        )
        raise ChatError("Gemini returned an unexpected response shape.")

    async def _call_gemini(
        self,
        contents: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        round_num: int,
    ) -> tuple[dict[str, Any], int]:
        url = GEMINI_URL_TEMPLATE.format(model=self._model)
        payload: dict[str, Any] = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        }
        if tools:
            payload["tools"] = tools

        data: dict[str, Any] | None = None
        for attempt in range(1, GEMINI_MAX_ATTEMPTS + 1):
            is_last_attempt = attempt == GEMINI_MAX_ATTEMPTS
            try:
                async with httpx.AsyncClient(
                    timeout=GEMINI_REQUEST_TIMEOUT_SECONDS
                ) as client:
                    response = await client.post(
                        url, json=payload, params={"key": self._api_key}
                    )
                    response.raise_for_status()
                    data = response.json()
                break
            except httpx.HTTPStatusError as exc:
                detail = _extract_error_message(exc.response) or (
                    f"Gemini request failed with status {exc.response.status_code}."
                )
                if exc.response.status_code == 429:
                    raise RateLimitError(detail) from exc
                # 5xx from Gemini itself is usually transient overload
                # (confirmed live: a 503 "currently experiencing high
                # demand") — worth one retry before giving up.
                if exc.response.status_code >= 500 and not is_last_attempt:
                    print(
                        f"[gemini] call {round_num}/{MAX_TOOL_ROUNDS} got "
                        f"{exc.response.status_code}, retrying..."
                    )
                    await asyncio.sleep(GEMINI_RETRY_PAUSE_SECONDS)
                    continue
                raise ChatError(detail) from exc
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                # Confirmed live: this happens intermittently even on an
                # otherwise-normal request — a single retry absorbs a
                # momentary network blip instead of surfacing a 502 to
                # the app for something that would have succeeded a
                # second later.
                if not is_last_attempt:
                    print(
                        f"[gemini] call {round_num}/{MAX_TOOL_ROUNDS} network "
                        f"error ({exc!r}), retrying..."
                    )
                    await asyncio.sleep(GEMINI_RETRY_PAUSE_SECONDS)
                    continue
                raise ChatError(f"Gemini request failed: {exc}") from exc
            except (httpx.HTTPError, ValueError) as exc:
                raise ChatError(f"Gemini request failed: {exc}") from exc

        # print rather than `logging` — guarantees this shows up in
        # whatever plain stdout redirect the backend is run with (e.g.
        # `> backend.log`), with no dependency on uvicorn's own logging
        # config/level being set up to pass through an app-level logger.
        usage = data.get("usageMetadata", {})
        print(
            f"[gemini] call {round_num}/{MAX_TOOL_ROUNDS} model={self._model} "
            f"prompt_tokens={usage.get('promptTokenCount')} "
            f"candidates_tokens={usage.get('candidatesTokenCount')} "
            f"total_tokens={usage.get('totalTokenCount')}"
        )

        try:
            return data["candidates"][0]["content"], usage.get("totalTokenCount") or 0
        except (KeyError, IndexError, TypeError) as exc:
            raise ChatError("Gemini returned an unexpected response shape.") from exc

    async def _fetch_and_filter_stations(
        self,
        *,
        query: str | None,
        lat: float | None,
        lon: float | None,
        brands: list[str] | None,
        max_distance_miles: float | None,
        brand_tier: str | None = None,
    ) -> tuple[list[GasStation], float, float, int, bool]:
        """Fetches page 1 (up to GASBUDDY_PAGE_SIZE stations) and, only if
        page 1 doesn't already satisfy brands/brand_tier/max_distance_
        miles, a second page (up to GASBUDDY_PAGE_SIZE more — 40 stations
        total across at most 2 calls), pausing SECOND_PAGE_PAUSE_SECONDS
        first so two rapid GasBuddy calls in one tool call don't look
        like a scripted burst. Returns (all_stations, lat, lon,
        scanned_count, any_nearby) — exclude_brands/fuel_grade never
        affect how many pages get fetched, only how the already-fetched
        set is filtered/sorted afterward (see _execute_tool_call)."""
        page1 = await self._gasbuddy.search_nearest_stations(
            query=query, lat=lat, lon=lon, limit=GASBUDDY_PAGE_SIZE
        )
        if not page1.stations:
            return [], page1.lat, page1.lon, 0, False

        all_stations = list(page1.stations)
        if page1.next_cursor is not None and _needs_second_page(
            page1.stations, brands, max_distance_miles, brand_tier
        ):
            await asyncio.sleep(SECOND_PAGE_PAUSE_SECONDS)
            page2 = await self._gasbuddy.search_nearest_stations(
                lat=page1.lat,
                lon=page1.lon,
                limit=GASBUDDY_PAGE_SIZE,
                cursor=page1.next_cursor,
            )
            all_stations.extend(page2.stations)

        return all_stations, page1.lat, page1.lon, len(all_stations), True

    async def _execute_tool_call(
        self, call: dict[str, Any], location: tuple[float, float] | None
    ) -> dict[str, Any]:
        """Runs one function call and returns the functionResponse payload
        to feed back to Gemini. Never raises — any failure becomes an
        error message for the model to relay, so one bad call can't crash
        the whole chat request."""
        name = call.get("name")
        if name != "find_nearby_gas_stations":
            return {"error": f"Unknown tool '{name}'."}

        # Unlike Groq/OpenAI-style tool_calls (whose arguments arrive as a
        # JSON string needing json.loads), Gemini's functionCall.args is
        # already a parsed object.
        args = call.get("args") or {}
        place = args.get("location") or None
        brands = _coerce_brand_list(args.get("brands"))
        exclude_brands = _coerce_brand_list(args.get("exclude_brands"))
        max_distance_miles = _coerce_positive_number(args.get("max_distance_miles"))
        fuel_grade = _coerce_fuel_grade(args.get("fuel_grade"))
        brand_tier = _coerce_brand_tier(args.get("brand_tier"))
        # exclude_brands and fuel_grade deliberately don't count as
        # "filters" for pagination purposes — they narrow/sort whatever
        # was already fetched, they never justify fetching more of it.
        has_filters = (
            bool(brands) or brand_tier is not None or max_distance_miles is not None
        )

        if place:
            query, lat, lon = place, None, None
        elif location is not None:
            query, lat, lon = None, location[0], location[1]
        else:
            return {"error": NO_LOCATION_MESSAGE}

        try:
            if has_filters:
                (
                    all_stations,
                    res_lat,
                    res_lon,
                    scanned_count,
                    any_nearby,
                ) = await self._fetch_and_filter_stations(
                    query=query,
                    lat=lat,
                    lon=lon,
                    brands=brands,
                    max_distance_miles=max_distance_miles,
                    brand_tier=brand_tier,
                )
            else:
                result = await self._gasbuddy.search_nearest_stations(
                    query=query, lat=lat, lon=lon, limit=GASBUDDY_PAGE_SIZE
                )
                all_stations = result.stations
                res_lat, res_lon = result.lat, result.lon
                scanned_count = len(all_stations)
                any_nearby = bool(all_stations)
        except GeocodingError as exc:
            return {"error": str(exc)}
        except MissingSearchData:
            return {"error": "Missing search parameters for that location."}
        except CloudflareBlocked:
            return {
                "error": (
                    "GasBuddy is temporarily blocking automated requests. "
                    "Try again shortly."
                )
            }
        except (LibraryError, APIError) as exc:
            return {"error": f"GasBuddy lookup failed: {exc}"}
        except Exception as exc:  # a tool call must never crash the whole request
            return {"error": f"Station lookup failed unexpectedly: {exc}"}

        stations = _filter_stations(
            all_stations, brands, exclude_brands, max_distance_miles, brand_tier
        )
        if not stations:
            return {
                "error": _no_match_message(
                    brands,
                    exclude_brands,
                    max_distance_miles,
                    any_nearby,
                    scanned_count,
                    brand_tier,
                )
            }

        cheapest: dict[str, Any] | None = None
        average_price: float | None = None
        average_price_formatted: str | None = None
        if fuel_grade:
            sorted_stations = _sort_by_fuel_grade(stations, fuel_grade)
            if not sorted_stations:
                return {"error": _no_fuel_grade_message(fuel_grade, len(stations))}
            stations = sorted_stations
            cheapest = _station_summary(stations[0])
            average_info = _average_fuel_price(stations, fuel_grade)
            if average_info is not None:
                average_price, average_price_formatted = average_info

        payload: dict[str, Any] = {
            "searched_lat": res_lat,
            "searched_lon": res_lon,
            "station_count": len(stations),
            "stations": [_station_summary(s) for s in stations],
        }
        if fuel_grade:
            # An explicit instruction, not just data — the model is
            # unreliable at comparing many prices itself (see
            # SYSTEM_PROMPT), so this spells out that the order and the
            # cheapest/average_price fields below are already correct.
            payload["sorted_by"] = (
                f"{fuel_grade}_price ascending (cheapest first) — the "
                "list below is already in this exact order; relay it "
                "as-is, do not re-sort or recompute the ranking"
            )
            payload["cheapest"] = cheapest
            payload["average_price"] = average_price
            payload["average_price_formatted"] = average_price_formatted

        filters_applied: dict[str, Any] = {}
        if brands:
            filters_applied["brands"] = brands
        if exclude_brands:
            filters_applied["exclude_brands"] = exclude_brands
        if brand_tier:
            filters_applied["brand_tier"] = brand_tier
        if max_distance_miles is not None:
            filters_applied["max_distance_miles"] = max_distance_miles
        if fuel_grade:
            filters_applied["fuel_grade"] = fuel_grade
        if filters_applied:
            payload["filters_applied"] = filters_applied
        return payload


def get_chat_service(
    gasbuddy: GasBuddyService = Depends(get_gasbuddy_service),
) -> ChatService:
    return ChatService(gasbuddy)
