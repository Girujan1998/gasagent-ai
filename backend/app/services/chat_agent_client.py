import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import Depends
from py_gasbuddy import APIError, CloudflareBlocked, LibraryError, MissingSearchData

from app.config import get_settings
from app.models.schemas import ChatMessage, EvStation, FuelPrice, GasStation
from app.services import brand_directory
from app.services.ev_directory_client import EvDirectoryError
from app.services.ev_search import EvSearchService, get_ev_search_service
from app.services.gas_price_client import (
    GAS_PRICE_PAGE_SIZE,
    GasPriceService,
    StationSearchResult,
    format_price_like,
    get_gas_price_service,
)
from app.services.forecast import ForecastService, get_forecast_service
from app.services.geo import haversine_miles
from app.services.geocoding import GeocodingError, geocode

# The classic generateContent REST shape — Google's newer "Interactions
# API" is now GA and recommended for new work, but it's stateful (keeps
# conversation history server-side) and needs the google-genai SDK rather
# than plain HTTP. generateContent stays close to this app's existing
# "resend the whole conversation every time" design and needs no SDK at
# all, just httpx, so it's the starting point for this scaffold.
LLM_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# Started as a single, deliberately minimal tool with just `location`, to
# prove the function-calling round-trip works end to end against
# the model's request/response shape. brands/exclude_brands/max_distance_
# miles/fuel_grade below rebuild the filtering/sorting the earlier Groq-
# backed tool had — done in code here too, never left for the model to
# judge by reading a raw station list itself.
FIND_STATIONS_TOOL: dict[str, Any] = {
    "name": "find_nearby_gas_stations",
    "description": (
        "Look up real, current gas stations and their live fuel "
        "prices near a location, using the app's own gas-price "
        "lookup. Supports optional filters — one or more "
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
                    "radius in miles ('within 5 miles', 'closer "
                    "than 2 miles'). Use max_distance_km instead "
                    "when the user gave the radius in "
                    "kilometres — don't convert it yourself. "
                    "Omit both when no distance was mentioned."
                ),
            },
            "max_distance_km": {
                "type": "number",
                "description": (
                    "Only include stations within this many "
                    "kilometres of the searched location — ONLY "
                    "when the user gave an explicit radius in "
                    "kilometres ('within 10 km', 'closer than 5 "
                    "kilometres'). The tool converts this to "
                    "miles itself — never convert km to miles "
                    "yourself. Don't set both max_distance_miles "
                    "and max_distance_km at once."
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
                    "actual cheapest matching station, with its "
                    "own price_per_litre/price_unit for use with "
                    "calculate_fuel_cost) and an average_price "
                    "field, computed for you — answer directly "
                    "from those fields for a 'cheapest' or "
                    "'average price' question, never by "
                    "comparing prices in the stations list "
                    "yourself. Omit entirely when the user isn't "
                    "asking about price ranking at all."
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
            "max_report_age_minutes": {
                "type": "number",
                "description": (
                    "Only include stations whose price (for fuel_grade, "
                    "or 'regular' if fuel_grade isn't set) was reported "
                    "within this many minutes — e.g. 'gas stations with "
                    "a price reported in the last 30 minutes' → 30. "
                    "Every returned station already includes how long "
                    "ago its price was reported (the "
                    "{grade}_reported/{grade}_reported_minutes_ago "
                    "fields) regardless of this param — only set this "
                    "when the user wants stations FILTERED by freshness, "
                    "not just told the age. Omit entirely when the user "
                    "didn't ask about report recency."
                ),
            },
            "sort_by_recency": {
                "type": "boolean",
                "description": (
                    "Pass true when the user asks for the most "
                    "recently updated/reported price ('what's the most "
                    "recently updated gas price nearby', 'freshest "
                    "price near me') — the tool sorts by report time "
                    "(for fuel_grade, or 'regular' if not set) and "
                    "returns the answer in most_recent; never judge "
                    "recency from timestamps yourself. Omit entirely "
                    "for a plain search with no recency ranking asked "
                    "for."
                ),
            },
            "sort_by_distance": {
                "type": "boolean",
                "description": (
                    "Pass true when the user wants just the single "
                    "CLOSEST/NEAREST gas station ('what's the closest "
                    "gas station to me', 'nearest station nearby') — "
                    "the tool sorts by real distance and returns the "
                    "answer in nearest; never judge distance from the "
                    "station list yourself. A plain 'gas stations near "
                    "me' with no closest/nearest wording does NOT need "
                    "this — omit entirely for a plain search with no "
                    "distance ranking asked for."
                ),
            },
            "top_n": {
                "type": "integer",
                "description": (
                    "How many results to return. Pass this whenever the "
                    "user names a specific count — 'the 5 cheapest gas "
                    "stations', 'top 3 nearest stations', 'the 12 "
                    "nearest Shells', 'show me 8 Petro-Canada stations' "
                    "→ top_n: 5, 3, 12, or 8 — whether or not a ranking "
                    "param is also set. A plain search with no count "
                    "named (e.g. 'What is the price at Shell?') already "
                    "returns a small default set on its own — omit "
                    "top_n for that; only pass it to request a specific "
                    "number instead. Omit entirely for a single-answer "
                    "ranking question ('the cheapest station', 'the "
                    "closest station') — that already returns exactly "
                    "one answer regardless of top_n."
                ),
            },
        },
        "required": [],
    },
}

# A separate, purely computational tool — none of this touches the
# gas-price lookup.
# Every one of cost/volume/savings/fill-up math is unreliable for the
# model to do itself (the same reason price sorting and cheapest/
# average-price were moved into find_nearby_gas_stations earlier), so
# `mode` selects a deterministic calculation in code instead. Money
# results are always in dollars, even when the per-litre input was in
# cents, since a total cost/savings is naturally a dollar figure either
# way (e.g. "$72.50", never "7250¢").
CALCULATE_FUEL_COST_TOOL: dict[str, Any] = {
    "name": "calculate_fuel_cost",
    "description": (
        "Does exact fuel-cost arithmetic — total cost for a volume, how "
        "many litres a budget buys, how much switching prices saves, or "
        "the cost to fill a partially-full tank. Call this for ANY "
        "question involving multiplying/dividing a price by a volume or "
        "budget, or comparing two prices — never do this math yourself, "
        "you are not reliable at arithmetic. Can be combined with "
        "find_nearby_gas_stations: call that first to get a real price "
        "(e.g. its cheapest field), then call this with that price."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": [
                    "cost_for_volume",
                    "volume_for_budget",
                    "savings",
                    "fill_up_cost",
                ],
                "description": (
                    "Which calculation to run. 'cost_for_volume': total "
                    "cost of a given volume at a given price (needs "
                    "volume_litres, price_per_litre, price_unit). "
                    "'volume_for_budget': how many litres a dollar "
                    "budget buys at a given price (needs budget, "
                    "price_per_litre, price_unit). 'savings': how much "
                    "cheaper one price is than another for a given "
                    "volume (needs volume_litres, and either "
                    "compare_price_per_litre or price_difference "
                    "alongside price_per_litre/price_unit). "
                    "'fill_up_cost': cost to fill a tank from its "
                    "current level (needs tank_capacity_litres, "
                    "current_fill_percent, price_per_litre, price_unit)."
                ),
            },
            "volume_litres": {
                "type": "number",
                "description": (
                    "The volume in litres — for 'cost_for_volume' and "
                    "'savings'. Omit for the other modes."
                ),
            },
            "price_per_litre": {
                "type": "number",
                "description": (
                    "The price per litre to use. Required alongside "
                    "price_unit for every mode except 'volume_for_"
                    "budget' with a plain price, where it's still "
                    "required. When relaying a price the user typed "
                    "themselves (e.g. '$1.45/L'), use price_unit: "
                    "'dollars'. When relaying a price from a "
                    "find_nearby_gas_stations result (its cheapest."
                    "price_per_litre or average_price fields), use "
                    "that same result's own price_unit field directly "
                    "— never convert or guess it yourself."
                ),
            },
            "price_unit": {
                "type": "string",
                "enum": ["dollars", "cents"],
                "description": (
                    "The unit price_per_litre/compare_price_per_litre/"
                    "price_difference are given in. Required whenever "
                    "any of those are set."
                ),
            },
            "budget": {
                "type": "number",
                "description": (
                    "The total amount to spend, in dollars — for "
                    "'volume_for_budget' (e.g. 'if I spend $60'). "
                    "Always dollars, never cents."
                ),
            },
            "compare_price_per_litre": {
                "type": "number",
                "description": (
                    "A second absolute price per litre, in the same "
                    "price_unit as price_per_litre — for 'savings' when "
                    "the user gave two specific prices ('$1.40 instead "
                    "of $1.47'). Use price_difference instead when the "
                    "user gave a direct difference instead of two "
                    "prices."
                ),
            },
            "price_difference": {
                "type": "number",
                "description": (
                    "A direct price-per-litre difference (not two "
                    "absolute prices) — for 'savings' when the user "
                    "says something is cheaper/more expensive by a "
                    "specific amount ('gas is 6 cents cheaper'). Use "
                    "compare_price_per_litre instead when the user gave "
                    "two absolute prices instead of a difference."
                ),
            },
            "tank_capacity_litres": {
                "type": "number",
                "description": (
                    "The tank's total capacity in litres — for "
                    "'fill_up_cost'."
                ),
            },
            "current_fill_percent": {
                "type": "number",
                "description": (
                    "How full the tank currently is, 0-100 — for "
                    "'fill_up_cost' (e.g. '25% full' → 25). The tool "
                    "computes the litres actually needed to fill it "
                    "itself — never compute that yourself."
                ),
            },
        },
        "required": ["mode"],
    },
}

# Reuses the app's existing EV backend (EvSearchService, already powering
# the EV tab) rather than adding new EV data-fetching logic — filtering
# below happens entirely in code (mirroring find_nearby_gas_stations'
# brands/exclude_brands/fuel_grade), never left for the model to judge by
# reading a raw station list itself.
FIND_EV_CHARGERS_TOOL: dict[str, Any] = {
    "name": "find_nearby_ev_chargers",
    "description": (
        "Look up real, current EV charging stations near a location, "
        "using the app's own EV charging data (public directory and "
        "community-sourced data, combined). Supports optional filters — networks to include/exclude, "
        "connector types, charger levels, and min/max/exact thresholds "
        "for total charger count, power (kW), voltage, and amperage — "
        "plus sort_by/sort_order for ranking questions ('highest "
        "voltage', 'lowest kW'). Pass only what the user actually asked "
        "for. Call this whenever the user asks about nearby EV charging "
        "stations, where to charge, or what charger types/specs are "
        "available nearby — never answer such questions from general "
        "knowledge or invent station names or addresses; never filter, "
        "rank, or judge stations yourself — the tool does all of that "
        "for you (see the returned top_match/sorted_by/"
        "connector_types_available fields). Not for gas stations or gas "
        "prices."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": (
                    "A specific place to search near — a city, "
                    "neighborhood, postal code, or address — ONLY when "
                    "the user named one explicitly (e.g. 'Toronto', "
                    "'near 90210'). Omit this entirely when the user "
                    "means their own current location ('near me', "
                    "'nearby', 'around here', or no place mentioned at "
                    "all) — the backend already knows the user's "
                    "current location and will use it automatically."
                ),
            },
            "max_distance_km": {
                "type": "number",
                "description": (
                    "Only include charging stations within this many "
                    "kilometres of the searched location — ONLY when "
                    "the user gave an explicit distance or radius "
                    "('within 10 km', 'closer than 5 kilometres'). "
                    "Omit entirely when no distance was mentioned; the "
                    "tool then uses a sensible wide default radius."
                ),
            },
            "networks": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "One or more specific EV charging networks/operators "
                    "to INCLUDE — e.g. ['ChargePoint'], or ['ChargePoint', "
                    "'FLO'] for several. Always pass this as a list, even "
                    "for a single network. A station matching ANY listed "
                    "network is included. Omit entirely when the user "
                    "didn't name a specific network."
                ),
            },
            "exclude_networks": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "One or more specific EV charging networks/operators "
                    "to EXCLUDE — e.g. ['Tesla'] for 'EV chargers near me "
                    "that aren't Tesla'. A station matching ANY listed "
                    "network here is removed. Use this whenever the user "
                    "says 'not X', 'excluding X', or 'other than X'. "
                    "Omit entirely when the user didn't ask to exclude "
                    "any network."
                ),
            },
            "connector_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "One or more connector types to require — e.g. "
                    "'CCS', 'CHAdeMO', 'Tesla'/'NACS', 'J1772', "
                    "'NEMA 14-50'. Always pass as a list, even for one "
                    "type. A station matching ANY listed connector is "
                    "included. Pass the term the user used (e.g. 'CCS') "
                    "as-is — the tool normalizes it itself, never "
                    "translate or guess a code yourself. Omit entirely "
                    "when the user didn't name a connector type."
                ),
            },
            "charger_levels": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["level1", "level2", "dc_fast"],
                },
                "description": (
                    "One or more charger levels to require — 'level1' "
                    "(slow, standard household outlet), 'level2' (the "
                    "common public/home charger speed), 'dc_fast' (rapid "
                    "charging, sometimes called 'fast charging' or "
                    "'Superchargers'). A station matching ANY listed "
                    "level is included. Omit entirely when the user "
                    "didn't ask for a specific charger level."
                ),
            },
            "chargers_min": {
                "type": "number",
                "description": (
                    "Only include stations with AT LEAST this many total "
                    "charging plugs (all levels combined) — 'a location "
                    "with 2 chargers' → 2, 'more than 2 chargers' → 3. "
                    "Omit entirely when the user didn't ask about how "
                    "many chargers are at a location."
                ),
            },
            "chargers_max": {
                "type": "number",
                "description": "Only include stations with AT MOST this many total charging plugs.",
            },
            "chargers_equals": {
                "type": "number",
                "description": (
                    "Only include stations with EXACTLY this many total "
                    "charging plugs — use this, not chargers_min, when "
                    "the user asks for an exact count ('a station with "
                    "exactly 4 chargers')."
                ),
            },
            "power_kw_min": {
                "type": "number",
                "description": (
                    "Only include stations with a connector rated at "
                    "least this many kW — e.g. 'chargers with at least "
                    "150kW' or 'more than 100kW' (round up to the next "
                    "whole kW for 'more than'). Only some stations report "
                    "this level of detail (mostly community-sourced "
                    "ones); stations without it are correctly excluded, "
                    "not a bug — say so if the user seems surprised by a "
                    "short result. Omit entirely when the user didn't ask "
                    "about charging power/speed in kW."
                ),
            },
            "power_kw_max": {
                "type": "number",
                "description": (
                    "Only include stations with a connector rated at most "
                    "this many kW. Same data-availability caveat as "
                    "power_kw_min."
                ),
            },
            "power_kw_equals": {
                "type": "number",
                "description": (
                    "Only include stations with a connector rated at "
                    "EXACTLY this many kW. Same data-availability caveat "
                    "as power_kw_min."
                ),
            },
            "voltage_min": {
                "type": "number",
                "description": (
                    "Only include stations with a connector rated at "
                    "least this many volts. Same data-availability caveat "
                    "as power_kw_min. Omit entirely when the user didn't "
                    "ask about voltage."
                ),
            },
            "voltage_max": {
                "type": "number",
                "description": "Only include stations with a connector rated at most this many volts.",
            },
            "voltage_equals": {
                "type": "number",
                "description": "Only include stations with a connector rated at EXACTLY this many volts.",
            },
            "amperage_min": {
                "type": "number",
                "description": (
                    "Only include stations with a connector rated at "
                    "least this many amps. Same data-availability caveat "
                    "as power_kw_min. Omit entirely when the user didn't "
                    "ask about amperage."
                ),
            },
            "amperage_max": {
                "type": "number",
                "description": "Only include stations with a connector rated at most this many amps.",
            },
            "amperage_equals": {
                "type": "number",
                "description": "Only include stations with a connector rated at EXACTLY this many amps.",
            },
            "sort_by": {
                "type": "string",
                "enum": ["chargers", "power_kw", "voltage", "amperage", "distance"],
                "description": (
                    "Pass this whenever the user asks for a ranking — "
                    "'the highest voltage charger near me', 'lowest kW "
                    "charger nearby', 'the station with the most "
                    "chargers', 'the CLOSEST/NEAREST charger to me' "
                    "(pass 'distance' for this — a plain 'EV chargers "
                    "near me' with no ranking word does NOT need this, "
                    "only use it when the user specifically wants just "
                    "the one nearest/farthest station). Always pair with "
                    "sort_order. The tool sorts and picks the answer for "
                    "you (top_match field) — never rank or compare "
                    "stations yourself. Omit entirely for a plain search "
                    "with no ranking asked for."
                ),
            },
            "sort_order": {
                "type": "string",
                "enum": ["highest", "lowest"],
                "description": (
                    "Pairs with sort_by — 'highest' for 'the "
                    "highest/most/fastest X'/'farthest', 'lowest' for "
                    "'the lowest/least/slowest X'/'closest'/'nearest'. "
                    "If omitted, defaults to 'lowest' for sort_by: "
                    "'distance' (closest) and 'highest' for everything "
                    "else — safest to always set it explicitly rather "
                    "than rely on this."
                ),
            },
            "top_n": {
                "type": "integer",
                "description": (
                    "Pass this when the user wants more than ONE ranked "
                    "result — 'the 5 nearest chargers', 'top 3 highest "
                    "power stations' → top_n: 5 or 3. Only meaningful "
                    "paired with sort_by; ignored otherwise. Omit "
                    "entirely for a single-answer ranking question ('the "
                    "closest charger', 'the highest voltage charger') — "
                    "that already returns exactly one answer in "
                    "top_match, or for a plain unranked search, which "
                    "already returns the full matching list."
                ),
            },
        },
        "required": [],
    },
}

# Only for genuinely combined questions — asking about both gas and EV at
# once, or specifically wanting the closest gas-station/EV-charger pair.
# A plain single-type question ("gas stations near me") stays on
# find_nearby_gas_stations/find_nearby_ev_chargers — this tool is not a
# general-purpose replacement for either.
FIND_GAS_AND_EV_TOOL: dict[str, Any] = {
    "name": "find_nearby_gas_and_ev_stations",
    "description": (
        "Search for BOTH gas stations and EV charging stations near a "
        "location at once, and find the closest gas-station/EV-charger "
        "PAIR — the specific gas station and specific EV charger that "
        "are nearest to EACH OTHER (by real distance between them, "
        "computed in code, not from the user). Use this ONLY for "
        "genuinely combined questions: 'find a gas station and EV "
        "charger closest to each other', 'is there gas and EV charging "
        "near me', 'closest Shell and ChargePoint to each other'. Do "
        "NOT use this for a plain single-type question ('gas stations "
        "near me', 'EV chargers near me') — use find_nearby_gas_stations "
        "or find_nearby_ev_chargers for those instead, since this tool "
        "costs more tokens by searching and returning both at once. "
        "Supports the same brands/exclude_brands (gas) and "
        "networks/exclude_networks (EV) filters as those two tools — "
        "pass only what the user actually asked for. If the user asks "
        "for ANOTHER pair after already getting one in this "
        "conversation ('find another', 'a different one'), call this "
        "again with exclude_gas_stations/exclude_ev_stations set to "
        "every station already shown so far — the tool then computes a "
        "genuinely different, verified pair; never answer 'another' "
        "from memory or by picking different-looking stations out of an "
        "earlier response yourself, since that pair's distance was "
        "never actually computed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": (
                    "A specific place to search near — a city, "
                    "neighborhood, postal code, or address — ONLY when "
                    "the user named one explicitly. Omit this entirely "
                    "when the user means their own current location "
                    "('near me', 'nearby', or no place mentioned at all) "
                    "— the backend already knows the user's current "
                    "location and will use it automatically."
                ),
            },
            "max_distance_miles": {
                "type": "number",
                "description": (
                    "Only include stations within this many miles of the "
                    "searched location — ONLY when the user gave an "
                    "explicit distance in miles. Use max_distance_km "
                    "instead for kilometres — don't convert it yourself."
                ),
            },
            "max_distance_km": {
                "type": "number",
                "description": (
                    "Only include stations within this many kilometres "
                    "of the searched location. The tool converts this to "
                    "miles itself — never convert km to miles yourself. "
                    "Don't set both max_distance_miles and "
                    "max_distance_km at once."
                ),
            },
            "brands": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "One or more gas brands to INCLUDE, e.g. ['Shell']. "
                    "Always pass as a list. Omit entirely when the user "
                    "didn't name a gas brand."
                ),
            },
            "exclude_brands": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One or more gas brands to EXCLUDE. Omit entirely when not asked for.",
            },
            "networks": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "One or more EV charging networks to INCLUDE, e.g. "
                    "['ChargePoint']. Always pass as a list. Omit "
                    "entirely when the user didn't name a network."
                ),
            },
            "exclude_networks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One or more EV networks to EXCLUDE. Omit entirely when not asked for.",
            },
            "exclude_gas_stations": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Gas station NAMES to exclude from consideration — "
                    "use this for a 'find another pair' follow-up, set "
                    "to every gas station already shown earlier in this "
                    "conversation (not just the most recent one). Omit "
                    "entirely on a first-time request."
                ),
            },
            "exclude_ev_stations": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "EV charging station NAMES to exclude from "
                    "consideration — same 'find another pair' use as "
                    "exclude_gas_stations, set to every EV charger "
                    "already shown earlier in this conversation. Omit "
                    "entirely on a first-time request."
                ),
            },
        },
        "required": [],
    },
}

# Deliberately has no day-count/date param at all — this projects ONE day
# (tomorrow) from today's live gas-price average and a national trend rate
# (see ForecastService in forecast.py); there's no multi-day series
# anywhere behind it, so there's nothing further-out to ask this tool for.
GET_GAS_PRICE_FORECAST_TOOL: dict[str, Any] = {
    "name": "get_gas_price_forecast",
    "description": (
        "Get TOMORROW's projected local gas price — today's live "
        "average, tomorrow's forecasted average/lowest/highest, "
        "whether the price is trending up or down, and the price "
        "difference between today and tomorrow (for both the average "
        "and the lowest/highest). Covers ONLY the next day — there is "
        "no way to forecast any day beyond tomorrow (not next week, not "
        "a specific future date); if the user asks for that, say only "
        "a next-day forecast is available rather than guessing or "
        "inventing one. Call this whenever the user asks about future "
        "gas prices, whether prices are going up or down, or a "
        "tomorrow/next-day price — never estimate this yourself. Not "
        "for today's current prices (use find_nearby_gas_stations for "
        "that)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": (
                    "A specific place to forecast for — a city, "
                    "neighborhood, postal code, or address — ONLY when "
                    "the user named one explicitly. Omit this entirely "
                    "when the user means their own current location "
                    "('near me', 'my area', or no place mentioned at "
                    "all) — the backend already knows the user's "
                    "current location and will use it automatically."
                ),
            },
        },
        "required": [],
    },
}

# All five declarations live under one "Tool" entry — safer than
# separate Tool objects, which some versions of this API don't support
# alongside each other when functionDeclarations are involved.
TOOLS = [
    {
        "functionDeclarations": [
            FIND_STATIONS_TOOL,
            CALCULATE_FUEL_COST_TOOL,
            FIND_EV_CHARGERS_TOOL,
            FIND_GAS_AND_EV_TOOL,
            GET_GAS_PRICE_FORECAST_TOOL,
        ]
    }
]

# Rounds 1-3 offer tools; round 4 omits `tools` entirely, which should
# make it structurally impossible for the model to return another
# functionCall on that round (confirmed live on Groq/OpenAI-compatible
# APIs for the equivalent case; not yet independently re-confirmed for
# this model specifically). Raised from 3 to 4 so a question needing two
# station searches (e.g. comparing two brands' own cheapest prices) plus
# one calculate_fuel_cost call still has a round left for the final
# answer — a plain single-search-then-calculate question still finishes
# in 2 tool rounds as before, so this only raises the ceiling for the
# rarer multi-brand-comparison case, not the common one.
MAX_TOOL_ROUNDS = 4

# The pause before fetching a second page of stations (brands/distance
# lookups only) — the underlying gas-price lookup is an unofficial
# scrape of a third-party site's internal API, so two rapid-fire
# requests in the same tool call look more like a scripted burst than a
# second page ever does on its own.
# Only ever awaited immediately before a genuinely-needed second-page
# fetch (see _needs_second_page), never speculatively.
SECOND_PAGE_PAUSE_SECONDS = 1.0

# Matches the GasStation attribute names for each grade's FuelPrice field,
# so a validated fuel_grade string can be used directly with getattr().
VALID_FUEL_GRADES = {"regular", "midgrade", "premium", "diesel"}

VALID_BRAND_TIERS = {"major", "lesser_known"}

# The codes the EV directory and community sources' EvStation.connector_types
# already use (the community source's raw titles are mapped onto these same
# codes in ev_community_client.py) — common ways a
# model might phrase a connector request, mapped onto them. Anything not
# here is passed through uppercased rather than hidden, same fallback
# mobile's formatConnectorType uses for a code it doesn't recognize.
EV_CONNECTOR_ALIASES = {
    "j1772": "J1772",
    "type1": "J1772",
    "type 1": "J1772",
    "chademo": "CHADEMO",
    "ccs": "J1772COMBO",
    "j1772combo": "J1772COMBO",
    "combo": "J1772COMBO",
    "tesla": "TESLA",
    "nacs": "TESLA",
    "nema1450": "NEMA1450",
    "nema 14-50": "NEMA1450",
    "nema520": "NEMA520",
    "nema 5-20": "NEMA520",
}

# There's no separate raw "level" field on an EvStation — a station's
# charger level is inferred purely from which of level1_count/level2_count/
# dc_fast_count is nonzero (see _matches_charger_level below).
EV_CHARGER_LEVELS = {"level1", "level2", "dc_fast"}

# Fetched instead of the unfiltered default (20) whenever any EV filter is
# set — filtering the 20 nearest stations down can leave almost nothing
# even when better matches exist slightly farther out. The EV directory/
# community sources have no cursor pagination to page through (unlike
# the gas-price lookup), so widening the single limit= call is all
# that's needed; MAX_LIMIT in ev_directory_client.py is 200, so this is
# well within range.
EV_FILTERED_FETCH_LIMIT = 100

# The widened fetch above is for finding good matches, not for relaying
# all of them back to the model — a broad filter can still leave dozens
# of matches, and every one costs real tokens in the tool response.
# Capped at the same size the gas-price lookup's own page naturally caps gas results
# to (GAS_PRICE_PAGE_SIZE), applied after filtering/sorting so the
# nearest/best matches are always what gets kept.
EV_MAX_STATIONS_IN_RESPONSE = 20

# find_nearby_gas_and_ev_stations' own EV-side fetch — wider than EV's own
# unfiltered default (20) since a bigger candidate pool improves
# closest-pair quality, and safe to widen since the EV directory/
# community sources (unlike the gas-price lookup) have no rate-limit
# fragility to worry about.
GAS_AND_EV_FETCH_LIMIT = 40

# Each side's returned list is capped separately at this size — this
# tool's payload already embeds two full station lists at once (roughly
# double either single tool's own token cost), so capping matters more
# here, not less. Smaller than EV_MAX_STATIONS_IN_RESPONSE since two
# lists of this size are already comparable to one list at that size.
GAS_AND_EV_MAX_STATIONS_IN_RESPONSE = 15

# Upper bound for the new top_n param (gas and EV both) — a "top N ranked
# stations" card list beyond this is neither a realistic ask nor worth
# the tokens; matches EV_MAX_STATIONS_IN_RESPONSE's existing cap.
MAX_TOP_N = 20

# A plain gas-station search with no ranking (no fuel_grade/
# sort_by_recency/sort_by_distance) and no explicit top_n from the user
# used to return every matching station — e.g. "What is the price at
# Shell?" showing all 20 nearest Shells instead of a manageable few.
# Defaults that case to the nearest few instead; station_count in the
# response still reports the true total, so the model can say e.g.
# "found 12 Shell stations, here are the 3 closest" and the user can
# ask for a specific count (top_n) to see more.
DEFAULT_UNRANKED_TOP_N = 3

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

# Confirmed live: the model occasionally times out or returns a transient
# 5xx (server overload) even on an otherwise-normal request. A single
# retry (2 attempts total, 30s timeout) still let a 502 through — the
# retry attempt hit a second, back-to-back ReadTimeout — so this allows 2
# retries (3 attempts total) at a longer 60s timeout each, since back-to-
# back timeouts aren't necessarily independent one-off blips and a
# bigger round 2 request (more prompt data, more "thinking") can
# genuinely take longer to complete on its own.
LLM_REQUEST_TIMEOUT_SECONDS = 60.0
LLM_MAX_ATTEMPTS = 3
LLM_RETRY_PAUSE_SECONDS = 1.0

NO_LOCATION_MESSAGE = (
    "No location is available for this user right now — the app hasn't "
    "shared a current location, and no place was named. Ask the user to "
    "share their location or name a city, postal code, or address."
)

# The place the user named couldn't be geocoded — distinct from
# NO_LOCATION_MESSAGE above (no place was given at all). The app's
# geocoder only recognizes cities/towns, provinces/states, and postal
# codes (see geocoding.py) — landmarks, schools, malls, and other points
# of interest aren't in its index, so this is routine, not a bug.
LOCATION_NOT_FOUND_MESSAGE = (
    "That location couldn't be found — the app's location lookup only "
    "recognizes cities/towns, provinces/states, and postal codes, not "
    "landmarks or businesses. Ask the user to share their current "
    "location, name a city or province, give a postal code, or browse "
    "stations on the map in the Gas or EV tab instead."
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
    "Stay strictly inside this app's domain: real-time gas prices, gas "
    "stations, fuel-cost calculations, and EV charging stations. "
    "Refuse everything else, no matter how simple or how well you "
    "could actually answer it — general knowledge (weather, sports "
    "results, trivia), writing code, recipes, cover letters or other "
    "writing help, or any other unrelated topic. When you refuse, say "
    "briefly and politely that you're built specifically for gas and "
    "EV charging in this app, without answering the off-topic part "
    "even partially — don't soften a refusal by giving a short answer "
    "anyway.\n\n"
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
    "gas-price lookup, optionally filtered by brand, excluded "
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
    "or average prices yourself.\n"
    "- Every returned station already shows how long ago its price was "
    "reported ({grade}_reported, e.g. '12 minutes ago', and "
    "{grade}_reported_minutes_ago) for every grade it has a price for — "
    "no extra argument needed, just relay it; never estimate an age from "
    "a timestamp yourself.\n"
    "- 'Gas stations with a price reported in the last N minutes' or "
    "similar freshness requirement: pass max_report_age_minutes: N — "
    "the tool filters to only stations that fresh before anything else "
    "(brand/price sorting still apply on top of that narrowed set).\n"
    "- 'Most recently updated/reported gas price near me', 'freshest "
    "price nearby': pass sort_by_recency: true, then answer from the "
    "tool's most_recent field — never judge which price is freshest "
    "yourself. This can be combined with fuel_grade: cheapest and "
    "most_recent may be different stations, since they answer different "
    "questions.\n"
    "- 'Closest/nearest gas station to me' — a question wanting just "
    "the single nearest station, not a general list: pass "
    "sort_by_distance: true, then answer strictly from the tool's "
    "nearest field — never judge distance from the station list "
    "yourself. This can be combined with fuel_grade/sort_by_recency: "
    "nearest, cheapest, and most_recent may all be different stations, "
    "since they answer different questions.\n"
    "- A TOP-N ranked list instead of just one station ('the 5 "
    "cheapest gas stations', 'top 3 nearest stations near me'): also "
    "pass top_n alongside whichever ranking param matches (fuel_grade "
    "for cheapest, sort_by_recency for freshest, sort_by_distance for "
    "nearest) — the tool returns exactly that many stations, already "
    "in the right order; never guess, truncate, or re-rank the list "
    "yourself.\n\n"
    "You also have a tool, calculate_fuel_cost, for ANY question "
    "involving fuel arithmetic — total cost for a volume, litres for a "
    "budget, savings from a price difference, or the cost to fill a "
    "partially-full tank. You are not reliable at arithmetic, so never "
    "multiply/divide a price by a volume or budget yourself, and never "
    "compute a savings amount yourself — always call this tool instead, "
    "and relay its result exactly as given. To answer a question that "
    "needs a real price first (e.g. 'find the cheapest Shell and "
    "calculate the cost of 60L'), call find_nearby_gas_stations first, "
    "then pass its cheapest station's price_per_litre and price_unit "
    "fields directly into calculate_fuel_cost — don't parse, convert, "
    "or re-type that number yourself. To compare two specific brands' "
    "own cheapest prices (e.g. 'compare the cheapest Shell and Esso'), "
    "call find_nearby_gas_stations once per brand (brands: ['Shell'], "
    "then brands: ['Esso']) before calculating — passing both brands "
    "in one call only finds one overall cheapest station, not each "
    "brand's own.\n\n"
    "You also have a tool, find_nearby_ev_chargers, for EV charging "
    "questions — real charging stations near a location, optionally "
    "within a distance in kilometres. Call it whenever the user asks "
    "about EV charging or where to charge an electric vehicle; never "
    "answer from general knowledge or invent station names or "
    "addresses. It supports the same style of filtering as the gas "
    "tool: networks/exclude_networks to include or exclude specific "
    "charging networks, connector_types (CCS, CHAdeMO, Tesla/NACS, "
    "J1772, etc.), charger_levels (level1/level2/dc_fast), and "
    "min/max/equals thresholds for charger count "
    "(chargers_min/max/equals) and charging power "
    "(power_kw/voltage/amperage, each with its own _min/_max/_equals) — "
    "'at least' → _min, 'at most' → _max, 'more than'/'less than' → "
    "round to the next _min/_max, 'exactly' → _equals. For ranking "
    "questions ('highest voltage charger near me', 'lowest kW charger "
    "nearby', 'the station with the most chargers', 'the CLOSEST/"
    "NEAREST charger to me' — pass sort_by: 'distance' for this one), "
    "pass sort_by and sort_order — the response's top_match field is "
    "already the answer, and stations is already sorted; never rank, "
    "compare, or judge distance yourself. For a TOP-N ranked list "
    "instead of just one station ('the 5 nearest chargers', 'top 3 "
    "highest power stations'), also pass top_n — the tool returns "
    "exactly that many, already sorted; never guess, truncate, or "
    "re-rank the list yourself. For 'what charger types are near me' "
    "or similar "
    "listing questions, call with no filters and read the response's "
    "connector_types_available field directly. Only some stations "
    "report power/voltage/amperage detail; if a power-based filter or "
    "ranking comes back with few or no results, say so rather than "
    "treating it as an error. Never filter, sort, count, or judge "
    "connector specs yourself — pass only what the user actually asked "
    "for and let the tool do it.\n\n"
    "For a genuinely COMBINED question — asking about both gas and EV "
    "charging at once, or specifically wanting the closest gas-station/"
    "EV-charger PAIR ('find a gas station and EV charger closest to "
    "each other', 'is there gas and EV charging near me', 'closest "
    "Shell and ChargePoint to each other') — use "
    "find_nearby_gas_and_ev_stations instead of the two tools above. Do "
    "NOT use it for a plain single-type question ('gas stations near "
    "me', 'EV chargers near me') — that stays on "
    "find_nearby_gas_stations/find_nearby_ev_chargers, since the "
    "combined tool costs more tokens by searching and returning both at "
    "once. It supports the same brands/exclude_brands and "
    "networks/exclude_networks filters as the two dedicated tools. Its "
    "response's closest_pair field, when present, is already the "
    "correct minimum-distance pair — computed from real coordinates in "
    "code — relay it exactly as given; never estimate, recompute, or "
    "second-guess that distance yourself. If either gas_lookup_note or "
    "ev_lookup_note is present, relay that one side's search failed or "
    "found nothing before answering with whatever the other side did "
    "find. If the user asks for ANOTHER pair after already getting one "
    "in this conversation ('find another', 'a different one'), call "
    "this tool again with exclude_gas_stations/exclude_ev_stations set "
    "to every station already shown so far (not just the most recent "
    "pair) — this is the ONLY way to get a genuinely different, "
    "verified pair; never answer 'another' from memory or by picking "
    "different-looking stations out of an earlier response yourself, "
    "since that pair's distance was never actually computed.\n\n"
    "For future gas prices, use get_gas_price_forecast — it covers "
    "tomorrow's price, whether it's trending up or down, the price "
    "difference from today, and tomorrow's lowest/highest price with "
    "their own differences, all in one call. It forecasts ONLY the next "
    "day — there is no data for next week, next month, or any specific "
    "future date beyond tomorrow. If asked about any of those, say "
    "plainly that only a next-day forecast is available; never guess or "
    "extrapolate one yourself. Every field in its response is already "
    "computed (the price itself, the change, and the up/down direction) "
    "— relay them as-is, never recalculate a difference or percentage "
    "yourself. If its response's note says a real forecast wasn't "
    "available for that area, say so honestly rather than presenting a "
    "'no change' result as an actual prediction. Not for today's "
    "current prices — use find_nearby_gas_stations for those.\n\n"
    "After the tool responds, base your answer strictly on the stations "
    "it returned — mention only those exact stations, with their real "
    "prices and distances, and never add, guess at, or invent any "
    "others, even if the user seems to expect more results. If the tool "
    "reports no location is available, say so plainly and ask the user "
    "to share their location or name a place. If the tool reports that "
    "the named location couldn't be found, relay its suggested next "
    "steps directly (share location, name a city/province, give a "
    "postal code, or browse the map in the Gas/EV tab) rather than just "
    "apologizing — this is routine, not a system failure, so don't "
    "downplay it as 'try again later'. If the tool reports that no "
    "stations were found, say so plainly rather than guessing or "
    "inventing a match. If the tool reports any other error, apologize "
    "briefly and suggest trying again shortly, without exposing "
    "technical details.\n\n"
    "If the user asks anything outside gas prices/stations, fuel-cost "
    "calculations, or EV charging, refuse it plainly as described "
    "above and redirect back to what you can help with — never answer "
    "it from general knowledge, even briefly."
)


class ChatError(Exception):
    """Raised when the chat completion request fails."""


class RateLimitError(ChatError):
    """Raised specifically when the provider reports its own rate limit
    was hit (HTTP 429) — handled distinctly in send() so the user gets a
    normal chat reply (RATE_LIMIT_MESSAGE) instead of the generic error
    banner every other ChatError produces via the /chat route."""


@dataclass
class StationBundle:
    """The real GasStation/EvStation objects behind one tool call (or,
    accumulated across a whole turn) — kept entirely separate from the
    dict payload sent to the model. Every _execute_*_call method returns one
    of these alongside its model-call payload; send() merges them across the
    turn's tool calls into the one returned to the API route for card
    rendering. Never serialized into a ChatMessage or model content."""

    gas_stations: list[GasStation] = field(default_factory=list)
    ev_stations: list[EvStation] = field(default_factory=list)


@dataclass
class ChatTurnResult:
    message: ChatMessage
    gas_stations: list[GasStation] = field(default_factory=list)
    ev_stations: list[EvStation] = field(default_factory=list)


def _merge_stations(existing: list[Any], new: list[Any]) -> list[Any]:
    """Appends only stations not already present (by station_id) — a turn
    can call the same tool more than once (e.g. comparing two brands),
    and a station found by both calls shouldn't produce two cards."""
    seen = {s.station_id for s in existing}
    merged = list(existing)
    for s in new:
        if s.station_id not in seen:
            seen.add(s.station_id)
            merged.append(s)
    return merged


def _extract_error_message(response: httpx.Response) -> str | None:
    try:
        return response.json()["error"]["message"]
    except (KeyError, TypeError, ValueError):
        return None


def _minutes_since(timestamp: str | None) -> int | None:
    """Age of a FuelPrice.last_updated timestamp, in whole minutes. Never
    raises — a missing or unparseable timestamp (not every price comes
    with one) just means no age can be shown."""
    if not timestamp:
        return None
    try:
        reported = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if reported.tzinfo is None:
        reported = reported.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - reported
    return max(0, int(delta.total_seconds() // 60))


def _format_minutes_ago(minutes: int) -> str:
    """Mirrors mobile/src/utils/time.ts's timeAgo bucketing, so the chat
    agent and the app's own station cards describe freshness the same
    way."""
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def _fuel_price_report_fields(fuel: FuelPrice | None) -> dict[str, Any]:
    minutes = _minutes_since(fuel.last_updated) if fuel else None
    return {
        "reported": _format_minutes_ago(minutes) if minutes is not None else None,
        "reported_minutes_ago": minutes,
    }


def _station_report_minutes(station: GasStation, fuel_grade: str) -> int | None:
    fuel: FuelPrice | None = getattr(station, fuel_grade, None)
    return _minutes_since(fuel.last_updated) if fuel else None


def _station_summary(s: GasStation) -> dict[str, Any]:
    regular_report = _fuel_price_report_fields(s.regular)
    midgrade_report = _fuel_price_report_fields(s.midgrade)
    premium_report = _fuel_price_report_fields(s.premium)
    diesel_report = _fuel_price_report_fields(s.diesel)
    return {
        "name": s.name,
        "brand": s.brand,
        "address": s.address,
        "distance_miles": s.distance_miles,
        "regular_price": s.regular.formatted_price if s.regular else None,
        "regular_reported": regular_report["reported"],
        "regular_reported_minutes_ago": regular_report["reported_minutes_ago"],
        "midgrade_price": s.midgrade.formatted_price if s.midgrade else None,
        "midgrade_reported": midgrade_report["reported"],
        "midgrade_reported_minutes_ago": midgrade_report["reported_minutes_ago"],
        "premium_price": s.premium.formatted_price if s.premium else None,
        "premium_reported": premium_report["reported"],
        "premium_reported_minutes_ago": premium_report["reported_minutes_ago"],
        "diesel_price": s.diesel.formatted_price if s.diesel else None,
        "diesel_reported": diesel_report["reported"],
        "diesel_reported_minutes_ago": diesel_report["reported_minutes_ago"],
    }


def _ev_station_summary(s: EvStation) -> dict[str, Any]:
    return {
        "name": s.name,
        "network": s.network,
        "address": s.address,
        "distance_miles": s.distance_miles,
        "level1_count": s.level1_count,
        "level2_count": s.level2_count,
        "dc_fast_count": s.dc_fast_count,
        "connector_types": s.connector_types,
        # Community-source-only (see connector_details' own doc comment in
        # schemas.py) — empty for directory-only stations. Included so the model can relay
        # *why* a station matched a power/voltage/amperage filter, the
        # same way gas's cheapest/average_price let it relay why a
        # station is the cheapest.
        "connector_details": [
            {
                "connector_type": d.connector_type,
                "power_kw": d.power_kw,
                "voltage": d.voltage,
                "amps": d.amps,
            }
            for d in s.connector_details
        ],
    }


# Generic enough to reuse for any free-text "close enough, not exact"
# matching problem — also used for EV network matching below.
def _normalize_text_for_matching(value: str) -> str:
    return re.sub(r"[-\s]+", " ", value.strip().lower())


def _brand_matches(station: GasStation, brand_query: str) -> bool:
    query = _normalize_text_for_matching(brand_query)
    if not query:
        return False
    for candidate in (station.brand, station.name, station.connected_brand):
        if not candidate:
            continue
        normalized = _normalize_text_for_matching(candidate)
        if query in normalized or normalized in query:
            return True
    return False


def _matches_any_brand(station: GasStation, brands: list[str]) -> bool:
    return any(_brand_matches(station, b) for b in brands)


def _known_brand_ids(brands: list[str] | None) -> list[int] | None:
    """Distinct GasBuddy brand_ids for every name in `brands`, via
    brand_directory.py — or None if any single name isn't known yet,
    signaling "no brand_id-scoped shortcut available; fall back to a
    plain nearest-any-brand search". A named-brand search this hasn't
    seen before falls back the same way, but real traffic is what grows
    the directory (see gas_price_client.py's _to_gas_station), not
    guesswork here."""
    if not brands:
        return None
    ids: list[int] = []
    for name in brands:
        brand_id = brand_directory.get_brand_id(name)
        if brand_id is None:
            return None
        if brand_id not in ids:
            ids.append(brand_id)
    return ids


async def _search_stations_by_brand_ids(
    gas_price: GasPriceService,
    brand_ids: list[int],
    *,
    query: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> StationSearchResult:
    """Fetches one page per distinct brand_id concurrently — GasBuddy's
    own server-side brand filter, sorted nearest-first *for that brand*
    regardless of how far its nearest station is, unlike paging through
    a nearest-any-brand pool hoping the brand turns up. Merges the pages,
    deduplicating by station_id (a station could plausibly appear under
    two different requested brands in an edge case). Always returns
    next_cursor=None — a single page per brand has comfortably covered
    every real case seen in testing, so there's no second-page fetch for
    this path the way there is for the nearest-any-brand one.

    Resolves lat/lon once up front, same as GasPriceService.
    search_nearest_stations' own query fallback (mirrored here rather
    than reused, since this needs the resolved coordinates *before*
    firing its own concurrent per-brand calls, to avoid a redundant
    geocode per brand) — so a bad `query` raises GeocodingError from
    this coroutine itself, exactly like a plain search_nearest_stations
    call would, for callers (e.g. an asyncio.gather with
    return_exceptions=True) that depend on that."""
    if lat is None or lon is None:
        lat, lon = await geocode(query) if query else (None, None)

    results = await asyncio.gather(
        *(
            gas_price.search_nearest_stations(
                lat=lat, lon=lon, brand_id=brand_id, limit=GAS_PRICE_PAGE_SIZE
            )
            for brand_id in brand_ids
        )
    )
    merged: dict[str, GasStation] = {}
    for result in results:
        for station in result.stations:
            merged.setdefault(station.station_id, station)
    return StationSearchResult(
        stations=list(merged.values()), next_cursor=None, lat=lat, lon=lon
    )


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
    # Distance, when given, is the sole authority — the gas-price lookup
    # returns nearest-first, so once page 1's farthest station already exceeds
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


# Generic "a, b, or c" list formatter — brand_tier is a gas-only extra
# (used only by the gas tool's own call sites below); EV network messages
# just pass a plain list and leave it at its default of None.
def _list_descriptor(items: list[str] | None, brand_tier: str | None = None) -> str | None:
    if items:
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} or {items[1]}"
        return f"{', '.join(items[:-1])}, or {items[-1]}"
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
    brand_id_scoped: bool = False,
) -> str:
    if brand_id_scoped:
        # A brand_id-scoped search asks GasBuddy directly for this brand
        # near this location — it never fetches a nearest-any-brand pool
        # at all, so the usual "among the N nearest stations checked"
        # framing below (which assumes exactly that) doesn't apply here.
        return f"No {_list_descriptor(brands, brand_tier)} stations were found near that location."
    if not any_nearby:
        return "No gas stations were found near that location at all."
    descriptor = _list_descriptor(brands, brand_tier)
    bits: list[str] = []
    if descriptor:
        bits.append(f"matching {descriptor}")
    if exclude_brands:
        bits.append(f"excluding {_list_descriptor(exclude_brands)}")
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


def _sort_by_recency(stations: list[GasStation], fuel_grade: str) -> list[GasStation]:
    """Sorts stations by how recently their given grade's price was
    reported, freshest first — the deterministic replacement for asking
    the model to judge recency from raw timestamps. A station with no
    report time for this grade can't be ranked, so it's dropped
    entirely, same as _sort_by_fuel_grade drops an unpriced station."""
    dated = [
        (s, _station_report_minutes(s, fuel_grade))
        for s in stations
    ]
    dated = [(s, minutes) for s, minutes in dated if minutes is not None]
    dated.sort(key=lambda pair: pair[1])
    return [s for s, _ in dated]


def _sort_by_distance(stations: list[GasStation]) -> list[GasStation]:
    """Sorts stations nearest-first by real distance_miles — the
    deterministic answer for a 'closest gas station' question. A station
    with no distance can't be ranked, so it's dropped entirely, same as
    _sort_by_recency drops a station with no report time."""
    with_distance = [s for s in stations if s.distance_miles is not None]
    return sorted(with_distance, key=lambda s: s.distance_miles)


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


def _network_matches(station: EvStation, network_query: str) -> bool:
    query = _normalize_text_for_matching(network_query)
    if not query or not station.network:
        return False
    normalized = _normalize_text_for_matching(station.network)
    return query in normalized or normalized in query


def _matches_any_network(station: EvStation, networks: list[str]) -> bool:
    return any(_network_matches(station, n) for n in networks)


def _ev_station_total_chargers(s: EvStation) -> int:
    return (s.level1_count or 0) + (s.level2_count or 0) + (s.dc_fast_count or 0)


def _matches_charger_level(s: EvStation, levels: list[str]) -> bool:
    counts = {"level1": s.level1_count, "level2": s.level2_count, "dc_fast": s.dc_fast_count}
    return any(counts.get(level) for level in levels)


# A (min, max, equals) triple, used for every numeric EV criterion
# (chargers/power_kw/voltage/amperage) so none of the functions below need
# a separate scalar param per operator.
NumericRange = tuple[float | None, float | None, float | None]


def _range_is_set(min_: float | None, max_: float | None, equals: float | None) -> bool:
    return min_ is not None or max_ is not None or equals is not None


def _any_range_set(*ranges: NumericRange) -> bool:
    return any(_range_is_set(*r) for r in ranges)


def _numeric_in_range(value: float | None, range_: NumericRange) -> bool:
    min_, max_, equals = range_
    if not _range_is_set(min_, max_, equals):
        return True
    if value is None:
        return False
    if equals is not None and abs(value - equals) > 1e-6:
        return False
    if min_ is not None and value < min_:
        return False
    if max_ is not None and value > max_:
        return False
    return True


def _matches_connector_power_specs(
    s: EvStation,
    power_kw_range: NumericRange,
    voltage_range: NumericRange,
    amperage_range: NumericRange,
) -> bool:
    """True if at least one of the station's connectors satisfies ALL
    three ranges at once (they describe one physical connector's spec
    together, not three independent ones). Community-source-only data —
    a directory-only station (connector_details == []) never matches once any of the three
    ranges is set, since there's nothing here to check it against."""
    for detail in s.connector_details:
        if not _numeric_in_range(detail.power_kw, power_kw_range):
            continue
        if not _numeric_in_range(detail.voltage, voltage_range):
            continue
        if not _numeric_in_range(detail.amps, amperage_range):
            continue
        return True
    return False


def _filter_ev_stations(
    stations: list[EvStation],
    networks: list[str] | None,
    exclude_networks: list[str] | None,
    connector_types: list[str] | None,
    charger_levels: list[str] | None,
    chargers_range: NumericRange,
    power_kw_range: NumericRange,
    voltage_range: NumericRange,
    amperage_range: NumericRange,
) -> list[EvStation]:
    filtered = stations
    if networks:
        filtered = [s for s in filtered if _matches_any_network(s, networks)]
    if exclude_networks:
        filtered = [s for s in filtered if not _matches_any_network(s, exclude_networks)]
    if connector_types:
        wanted = set(connector_types)
        filtered = [
            s for s in filtered if wanted & {c.upper() for c in s.connector_types}
        ]
    if charger_levels:
        filtered = [s for s in filtered if _matches_charger_level(s, charger_levels)]
    if _range_is_set(*chargers_range):
        filtered = [
            s for s in filtered if _numeric_in_range(_ev_station_total_chargers(s), chargers_range)
        ]
    if _any_range_set(power_kw_range, voltage_range, amperage_range):
        filtered = [
            s
            for s in filtered
            if _matches_connector_power_specs(s, power_kw_range, voltage_range, amperage_range)
        ]
    return filtered


def _exclude_stations_by_name(stations: list[Any], excluded_names: list[str] | None) -> list[Any]:
    """Drops stations whose name matches one of excluded_names — used for
    'find another pair' follow-ups on find_nearby_gas_and_ev_stations,
    where the model only ever knows a station by name (never station_id,
    which isn't in _station_summary/_ev_station_summary). Same forgiving
    substring-either-direction match _brand_matches already uses, so a
    slightly reworded name still excludes correctly."""
    if not excluded_names:
        return stations
    normalized_excluded = [_normalize_text_for_matching(n) for n in excluded_names]

    def is_excluded(s: Any) -> bool:
        normalized_name = _normalize_text_for_matching(s.name)
        return any(
            n in normalized_name or normalized_name in n for n in normalized_excluded
        )

    return [s for s in stations if not is_excluded(s)]


def _closest_gas_ev_pair(
    gas_stations: list[GasStation], ev_stations: list[EvStation]
) -> tuple[GasStation, EvStation, float] | None:
    """The gas station and EV charger nearest to EACH OTHER (not to the
    user) — real Haversine distance between every pair, minimum kept.
    Stations missing coordinates are skipped rather than crashing (rare,
    but neither the gas-price lookup nor the EV directory/community
    sources guarantee lat/lon on every result). None if either list is
    empty or no pair has coordinates on
    both sides."""
    best: tuple[GasStation, EvStation, float] | None = None
    for gas in gas_stations:
        if gas.latitude is None or gas.longitude is None:
            continue
        for ev in ev_stations:
            if ev.latitude is None or ev.longitude is None:
                continue
            distance = haversine_miles(gas.latitude, gas.longitude, ev.latitude, ev.longitude)
            if best is None or distance < best[2]:
                best = (gas, ev, distance)
    return best


def _range_descriptor(unit_label: str, range_: NumericRange) -> str:
    min_, max_, equals = range_
    if equals is not None:
        return f"exactly {equals:g}{unit_label}"
    parts = []
    if min_ is not None:
        parts.append(f"at least {min_:g}{unit_label}")
    if max_ is not None:
        parts.append(f"at most {max_:g}{unit_label}")
    return " and ".join(parts)


def _no_ev_match_message(
    networks: list[str] | None,
    exclude_networks: list[str] | None,
    connector_types: list[str] | None,
    charger_levels: list[str] | None,
    chargers_range: NumericRange,
    power_kw_range: NumericRange,
    voltage_range: NumericRange,
    amperage_range: NumericRange,
    any_nearby: bool,
    scanned_count: int,
) -> str:
    if not any_nearby:
        return "No EV charging stations were found near that location at all."
    bits: list[str] = []
    if networks:
        bits.append(f"on {_list_descriptor(networks)}")
    if exclude_networks:
        bits.append(f"excluding {_list_descriptor(exclude_networks)}")
    if connector_types:
        bits.append(f"with a {'/'.join(connector_types)} connector")
    if charger_levels:
        bits.append(f"with a {'/'.join(charger_levels)} charger")
    if _range_is_set(*chargers_range):
        bits.append(f"with {_range_descriptor(' chargers', chargers_range)}")
    if _any_range_set(power_kw_range, voltage_range, amperage_range):
        spec_bits = []
        if _range_is_set(*power_kw_range):
            spec_bits.append(_range_descriptor(" kW", power_kw_range))
        if _range_is_set(*voltage_range):
            spec_bits.append(_range_descriptor(" V", voltage_range))
        if _range_is_set(*amperage_range):
            spec_bits.append(_range_descriptor(" A", amperage_range))
        bits.append(f"meeting {' / '.join(spec_bits)} (only some stations report specs)")
    if not bits:
        return "No stations matched the requested filters."
    return (
        f"No EV charging stations {' and '.join(bits)} were found, among the "
        f"{scanned_count} nearest stations checked."
    )


def _sort_ev_stations_by_metric(
    stations: list[EvStation], sort_by: str, sort_order: str
) -> list[EvStation]:
    """Ranks by a single scalar per station. For chargers, that's always
    the total plug count; for distance, distance_miles directly. For a
    connector spec (power_kw/voltage/amperage), it's that station's OWN
    highest value of the field when ranking highest, or its own lowest
    value when ranking lowest — the natural reading of "the highest
    voltage charger at this station." Stations with no connector_details
    for that field (directory-only) have no value to rank by and are dropped,
    not sorted to one end."""
    reverse = sort_order == "highest"
    if sort_by == "chargers":
        return sorted(stations, key=_ev_station_total_chargers, reverse=reverse)
    if sort_by == "distance":
        # Straight off the station, unlike the connector-detail-derived
        # fields below — closest/farthest by real distance from the user.
        with_distance = [s for s in stations if s.distance_miles is not None]
        return sorted(with_distance, key=lambda s: s.distance_miles, reverse=reverse)

    field = {"power_kw": "power_kw", "voltage": "voltage", "amperage": "amps"}[sort_by]
    scored: list[tuple[float, EvStation]] = []
    for s in stations:
        values = [
            getattr(d, field) for d in s.connector_details if getattr(d, field) is not None
        ]
        if not values:
            continue
        metric = max(values) if sort_order == "highest" else min(values)
        scored.append((metric, s))
    scored.sort(key=lambda pair: pair[0], reverse=reverse)
    return [s for _, s in scored]


def _gas_lookup_error_note(exc: BaseException) -> str:
    """Mirrors the exception-to-message mapping in
    ChatService._execute_find_stations_call, kept separate rather than
    shared since find_nearby_gas_and_ev_stations degrades gracefully
    (one side can fail while the other still returns real results) —
    the dedicated gas tool has no such "other side" to fall back to."""
    if isinstance(exc, GeocodingError):
        return LOCATION_NOT_FOUND_MESSAGE
    if isinstance(exc, MissingSearchData):
        return "Missing search parameters for that location."
    if isinstance(exc, CloudflareBlocked):
        return "The gas price service is temporarily blocking automated requests. Try again shortly."
    if isinstance(exc, (LibraryError, APIError)):
        return f"Gas price lookup failed: {exc}"
    return f"Gas station lookup failed unexpectedly: {exc}"


def _ev_lookup_error_note(exc: BaseException) -> str:
    """Mirrors ChatService._execute_ev_chargers_call's exception mapping — see
    _gas_lookup_error_note for why this isn't shared with it directly."""
    if isinstance(exc, GeocodingError):
        return LOCATION_NOT_FOUND_MESSAGE
    if isinstance(exc, EvDirectoryError):
        return f"EV charger lookup failed: {exc}"
    return f"EV charger lookup failed unexpectedly: {exc}"


def _coerce_string_list(value: Any) -> list[str] | None:
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
        key = _normalize_text_for_matching(stripped)
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


def _coerce_top_n(value: Any) -> int | None:
    n = _coerce_positive_number(value)
    if n is None:
        return None
    return max(1, min(MAX_TOP_N, int(n)))


def _coerce_fuel_grade(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in VALID_FUEL_GRADES else None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _coerce_brand_tier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in VALID_BRAND_TIERS else None


def _coerce_connector_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    seen: set[str] = set()
    codes: list[str] = []
    for v in value:
        if not isinstance(v, str) or not v.strip():
            continue
        key = re.sub(r"[\s\-]+", "", v.strip().lower())
        code = EV_CONNECTOR_ALIASES.get(key, v.strip().upper())
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes or None


def _coerce_charger_level_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    seen: set[str] = set()
    levels: list[str] = []
    for v in value:
        if not isinstance(v, str):
            continue
        normalized = v.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized not in EV_CHARGER_LEVELS or normalized in seen:
            continue
        seen.add(normalized)
        levels.append(normalized)
    return levels or None


def _coerce_numeric_range(args: dict[str, Any], prefix: str) -> NumericRange:
    return (
        _coerce_positive_number(args.get(f"{prefix}_min")),
        _coerce_positive_number(args.get(f"{prefix}_max")),
        _coerce_positive_number(args.get(f"{prefix}_equals")),
    )


EV_SORT_FIELDS = {"chargers", "power_kw", "voltage", "amperage", "distance"}
EV_SORT_ORDERS = {"highest", "lowest"}


def _coerce_ev_sort_by(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in EV_SORT_FIELDS else None


def _coerce_ev_sort_order(value: Any, sort_by: str) -> str:
    # "Highest" is the sensible default for every field except distance —
    # a model that says sort_by: "distance" and forgets sort_order must
    # get the CLOSEST station, not the farthest, so distance's default
    # flips to "lowest" here rather than relying on the model to always
    # remember to set it explicitly.
    default = "lowest" if sort_by == "distance" else "highest"
    if not isinstance(value, str):
        return default
    normalized = value.strip().lower()
    return normalized if normalized in EV_SORT_ORDERS else default


VALID_PRICE_UNITS = {"dollars", "cents"}


def _coerce_price_unit(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in VALID_PRICE_UNITS else None


def _price_to_dollars(value: float, unit: str) -> float:
    return value / 100 if unit == "cents" else value


def _price_unit_and_value_for_station(
    station: GasStation, fuel_grade: str
) -> tuple[float, str] | None:
    """Derives the raw price and its unit ("cents"/"dollars") from a
    station's own formatted price for a grade — e.g. "168.9¢" -> (168.9,
    "cents") — so a price relayed from a station search into
    calculate_fuel_cost is a direct copy, never something the model has
    to parse a number back out of a formatted string for."""
    fuel_price = getattr(station, fuel_grade)
    if fuel_price is None or fuel_price.price is None:
        return None
    formatted = (fuel_price.formatted_price or "").strip()
    unit = "cents" if formatted.endswith("¢") else "dollars"
    return fuel_price.price, unit


def _format_dollars(value: float) -> str:
    return f"${value:.2f}"


def _format_litres(value: float) -> str:
    return f"{value:.2f} L"


def _calculate_fuel_cost(args: dict[str, Any]) -> dict[str, Any]:
    """Every fuel-cost calculation the model might ask for, done as
    exact arithmetic in code rather than left to the model — the same
    reasoning as the deterministic price sorting on find_nearby_gas_
    stations. Never raises; an invalid/incomplete combination of
    arguments for the given mode returns a clear {"error": ...} instead.
    All money results are in dollars regardless of the input price's
    unit, since a total cost/savings is naturally a dollar figure either
    way."""
    mode = args.get("mode")

    def price_in_dollars(raw_key: str, unit_key: str = "price_unit") -> float | None:
        raw = _coerce_positive_number(args.get(raw_key))
        unit = _coerce_price_unit(args.get(unit_key))
        if raw is None or unit is None:
            return None
        return _price_to_dollars(raw, unit)

    if mode == "cost_for_volume":
        volume = _coerce_positive_number(args.get("volume_litres"))
        price = price_in_dollars("price_per_litre")
        if volume is None or price is None:
            return {
                "error": (
                    "cost_for_volume needs a positive volume_litres and "
                    "a price_per_litre with its price_unit."
                )
            }
        cost = volume * price
        return {
            "mode": mode,
            "volume_litres": volume,
            "cost": cost,
            "cost_formatted": _format_dollars(cost),
            "note": (
                "This is the exact cost — relay it as-is, don't "
                "recompute or double-check the arithmetic yourself."
            ),
        }

    if mode == "volume_for_budget":
        budget = _coerce_positive_number(args.get("budget"))
        price = price_in_dollars("price_per_litre")
        if budget is None or price is None:
            return {
                "error": (
                    "volume_for_budget needs a positive budget (in "
                    "dollars) and a price_per_litre with its price_unit."
                )
            }
        volume = budget / price
        return {
            "mode": mode,
            "budget": budget,
            "volume_litres": volume,
            "volume_formatted": _format_litres(volume),
            "note": (
                "This is the exact volume — relay it as-is, don't "
                "recompute or double-check the arithmetic yourself."
            ),
        }

    if mode == "savings":
        volume = _coerce_positive_number(args.get("volume_litres"))
        if volume is None:
            return {"error": "savings needs a positive volume_litres."}

        price_difference = _coerce_positive_number(args.get("price_difference"))
        price_unit = _coerce_price_unit(args.get("price_unit"))
        if price_difference is not None and price_unit is not None:
            diff_dollars = _price_to_dollars(price_difference, price_unit)
        else:
            base_price = price_in_dollars("price_per_litre")
            compare_price = price_in_dollars("compare_price_per_litre")
            if base_price is None or compare_price is None:
                return {
                    "error": (
                        "savings needs either price_difference with a "
                        "price_unit, or both price_per_litre and "
                        "compare_price_per_litre with a price_unit."
                    )
                }
            diff_dollars = abs(base_price - compare_price)

        savings = volume * diff_dollars
        return {
            "mode": mode,
            "volume_litres": volume,
            "savings": savings,
            "savings_formatted": _format_dollars(savings),
            "note": (
                "This is the exact savings — relay it as-is, don't "
                "recompute or double-check the arithmetic yourself."
            ),
        }

    if mode == "fill_up_cost":
        capacity = _coerce_positive_number(args.get("tank_capacity_litres"))
        fill_percent = args.get("current_fill_percent")
        price = price_in_dollars("price_per_litre")
        if (
            capacity is None
            or not isinstance(fill_percent, (int, float))
            or isinstance(fill_percent, bool)
            or not (0 <= fill_percent <= 100)
            or price is None
        ):
            return {
                "error": (
                    "fill_up_cost needs a positive tank_capacity_litres, "
                    "a current_fill_percent between 0 and 100, and a "
                    "price_per_litre with its price_unit."
                )
            }
        volume_needed = capacity * (1 - fill_percent / 100)
        cost = volume_needed * price
        return {
            "mode": mode,
            "volume_needed_litres": volume_needed,
            "volume_needed_formatted": _format_litres(volume_needed),
            "cost": cost,
            "cost_formatted": _format_dollars(cost),
            "note": (
                "volume_needed_litres and cost are exact — relay them "
                "as-is, don't recompute or double-check the arithmetic "
                "yourself."
            ),
        }

    return {"error": f"Unknown calculate_fuel_cost mode '{mode}'."}


def _to_llm_content(message: ChatMessage) -> dict[str, Any]:
    # The model API has no "assistant" role — its equivalent turn is "model".
    role = "model" if message.role == "assistant" else "user"
    return {"role": role, "parts": [{"text": message.content}]}


class ChatService:
    def __init__(
        self,
        gas_price: GasPriceService,
        ev_search: EvSearchService,
        forecast: ForecastService,
    ) -> None:
        settings = get_settings()
        self._api_key = settings.gemini_api_key
        self._model = settings.gemini_model
        self._gas_price = gas_price
        self._ev_search = ev_search
        self._forecast = forecast

    async def send(
        self,
        messages: list[ChatMessage],
        gas_location: tuple[float, float] | None = None,
        ev_location: tuple[float, float] | None = None,
    ) -> ChatTurnResult:
        """Send the conversation so far to the model and return the agent's
        final reply, running its station-lookup tool as many times as it
        asks to (bounded by MAX_TOOL_ROUNDS) — plus the real station
        objects (if any) behind this turn's tool call(s), for the mobile
        client to render as cards. These never touch `contents`/the model
        and are accumulated purely for the returned ChatTurnResult.

        Raises ChatError on any failure. A *missing* key is checked here
        directly (rather than letting the model API reject an empty one) since
        the model API takes the key as a query parameter — an empty key would
        just produce a confusing 400 from the model API itself rather than a
        clear local error.
        """
        if not self._api_key:
            raise ChatError(
                "Chat isn't configured: set GEMINI_API_KEY in backend/.env."
            )

        contents: list[dict[str, Any]] = [_to_llm_content(m) for m in messages]
        # Summed across every _call_llm round for this one turn (a
        # single user message and everything it takes to answer it),
        # printed alongside each round's own usage so the per-turn cost
        # is visible without adding the per-call lines up by hand.
        turn_total_tokens = 0
        turn_gas_stations: list[GasStation] = []
        turn_ev_stations: list[EvStation] = []

        for round_num in range(1, MAX_TOOL_ROUNDS + 1):
            include_tools = round_num < MAX_TOOL_ROUNDS
            try:
                content, call_tokens = await self._call_llm(
                    contents, tools=TOOLS if include_tools else None, round_num=round_num
                )
            except RateLimitError:
                print(
                    f"[llm] turn total: {turn_total_tokens} tokens across "
                    f"{round_num - 1} call(s) — rate-limited on call {round_num}"
                )
                return ChatTurnResult(
                    message=ChatMessage(role="assistant", content=RATE_LIMIT_MESSAGE)
                )
            turn_total_tokens += call_tokens

            parts = content.get("parts") or []
            function_calls = [p["functionCall"] for p in parts if "functionCall" in p]

            if not function_calls:
                text = "".join(p.get("text", "") for p in parts)
                if not text:
                    raise ChatError("The model returned an unexpected response shape.")
                print(
                    f"[llm] turn total: {turn_total_tokens} tokens across "
                    f"{round_num} call(s)"
                )
                return ChatTurnResult(
                    message=ChatMessage(role="assistant", content=text),
                    gas_stations=turn_gas_stations,
                    ev_stations=turn_ev_stations,
                )

            contents.append({"role": "model", "parts": parts})

            for call in function_calls:
                response, bundle = await self._execute_tool_call(
                    call, gas_location, ev_location
                )
                turn_gas_stations = _merge_stations(turn_gas_stations, bundle.gas_stations)
                turn_ev_stations = _merge_stations(turn_ev_stations, bundle.ev_stations)
                contents.append(
                    # Confirmed live: this model's role enum rejects
                    # "function" (a valid role in some other versions/docs
                    # of this API) — "user" is what actually works for
                    # feeding a functionResponse part back.
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

        # Unreachable: the final round never includes `tools`, so the model
        # cannot return a functionCall on it — the loop above always
        # returns before falling off the end.
        print(
            f"[llm] turn total: {turn_total_tokens} tokens across "
            f"{MAX_TOOL_ROUNDS} call(s) — forced stop at the round cap"
        )
        raise ChatError("The model returned an unexpected response shape.")

    async def _call_llm(
        self,
        contents: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        round_num: int,
    ) -> tuple[dict[str, Any], int]:
        url = LLM_URL_TEMPLATE.format(model=self._model)
        payload: dict[str, Any] = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        }
        if tools:
            payload["tools"] = tools

        data: dict[str, Any] | None = None
        for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
            is_last_attempt = attempt == LLM_MAX_ATTEMPTS
            try:
                async with httpx.AsyncClient(
                    timeout=LLM_REQUEST_TIMEOUT_SECONDS
                ) as client:
                    response = await client.post(
                        url, json=payload, params={"key": self._api_key}
                    )
                    response.raise_for_status()
                    data = response.json()
                break
            except httpx.HTTPStatusError as exc:
                detail = _extract_error_message(exc.response) or (
                    f"Model request failed with status {exc.response.status_code}."
                )
                if exc.response.status_code == 429:
                    raise RateLimitError(detail) from exc
                # 5xx from the model API itself is usually transient overload
                # (confirmed live: a 503 "currently experiencing high
                # demand") — worth one retry before giving up.
                if exc.response.status_code >= 500 and not is_last_attempt:
                    print(
                        f"[llm] call {round_num}/{MAX_TOOL_ROUNDS} got "
                        f"{exc.response.status_code}, retrying..."
                    )
                    await asyncio.sleep(LLM_RETRY_PAUSE_SECONDS)
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
                        f"[llm] call {round_num}/{MAX_TOOL_ROUNDS} network "
                        f"error ({exc!r}), retrying..."
                    )
                    await asyncio.sleep(LLM_RETRY_PAUSE_SECONDS)
                    continue
                raise ChatError(f"Model request failed: {exc}") from exc
            except (httpx.HTTPError, ValueError) as exc:
                raise ChatError(f"Model request failed: {exc}") from exc

        # print rather than `logging` — guarantees this shows up in
        # whatever plain stdout redirect the backend is run with (e.g.
        # `> backend.log`), with no dependency on uvicorn's own logging
        # config/level being set up to pass through an app-level logger.
        usage = data.get("usageMetadata", {})
        print(
            f"[llm] call {round_num}/{MAX_TOOL_ROUNDS} model={self._model} "
            f"prompt_tokens={usage.get('promptTokenCount')} "
            f"candidates_tokens={usage.get('candidatesTokenCount')} "
            f"total_tokens={usage.get('totalTokenCount')}"
        )

        try:
            return data["candidates"][0]["content"], usage.get("totalTokenCount") or 0
        except (KeyError, IndexError, TypeError) as exc:
            raise ChatError("The model returned an unexpected response shape.") from exc

    async def _fetch_and_filter_stations(
        self,
        *,
        query: str | None,
        lat: float | None,
        lon: float | None,
        brands: list[str] | None,
        max_distance_miles: float | None,
        brand_tier: str | None = None,
    ) -> tuple[list[GasStation], float, float, int, bool, bool]:
        """If every name in `brands` has a known brand_id (see
        brand_directory.py), fetches one brand-scoped page per id
        directly — GasBuddy's own server-side brand filter, so a brand
        far outside a plain nearest-any-brand search still turns up.
        Otherwise (no brands filter, or any name not yet known) fetches
        page 1 (up to GAS_PRICE_PAGE_SIZE stations) and, only if page 1
        doesn't already satisfy brands/brand_tier/max_distance_miles, a
        second page (up to GAS_PRICE_PAGE_SIZE more — 40 stations total
        across at most 2 calls), pausing SECOND_PAGE_PAUSE_SECONDS first
        so two rapid gas-price lookup calls in one tool call don't look
        like a scripted burst. Returns (all_stations, lat, lon,
        scanned_count, any_nearby, brand_id_scoped) — exclude_brands/
        fuel_grade never affect how many pages get fetched, only how the
        already-fetched set is filtered/sorted afterward (see
        _execute_tool_call)."""
        if lat is None or lon is None:
            lat, lon = await geocode(query) if query else (None, None)

        brand_ids = _known_brand_ids(brands)
        if brand_ids is not None:
            page1 = await _search_stations_by_brand_ids(
                self._gas_price, brand_ids, lat=lat, lon=lon
            )
        else:
            page1 = await self._gas_price.search_nearest_stations(
                lat=lat, lon=lon, limit=GAS_PRICE_PAGE_SIZE
            )
        if not page1.stations:
            return [], page1.lat, page1.lon, 0, False, brand_ids is not None

        all_stations = list(page1.stations)
        if page1.next_cursor is not None and _needs_second_page(
            page1.stations, brands, max_distance_miles, brand_tier
        ):
            await asyncio.sleep(SECOND_PAGE_PAUSE_SECONDS)
            page2 = await self._gas_price.search_nearest_stations(
                lat=page1.lat,
                lon=page1.lon,
                limit=GAS_PRICE_PAGE_SIZE,
                cursor=page1.next_cursor,
            )
            all_stations.extend(page2.stations)

        return all_stations, page1.lat, page1.lon, len(all_stations), True, False

    async def _execute_tool_call(
        self,
        call: dict[str, Any],
        gas_location: tuple[float, float] | None,
        ev_location: tuple[float, float] | None,
    ) -> tuple[dict[str, Any], StationBundle]:
        """Runs one function call and returns the functionResponse payload
        to feed back to the model, plus the real station objects (if any)
        behind it for card rendering. Never raises — any failure becomes
        an error message for the model to relay, so one bad call can't
        crash the whole chat request.

        The station-bearing _execute_*_call methods take `bundle` and
        fill it in as a side effect, right at the point they already
        have the real station objects on hand to summarize for the model —
        cheaper and far less invasive than turning every one of their
        many early error-return statements into a tuple."""
        name = call.get("name")
        # Unlike Groq/OpenAI-style tool_calls (whose arguments arrive as a
        # JSON string needing json.loads), the model's functionCall.args is
        # already a parsed object.
        args = call.get("args") or {}
        bundle = StationBundle()
        if name == "find_nearby_gas_stations":
            result = await self._execute_find_stations_call(args, gas_location, bundle)
        elif name == "calculate_fuel_cost":
            result = _calculate_fuel_cost(args)
        elif name == "find_nearby_ev_chargers":
            result = await self._execute_ev_chargers_call(args, ev_location, bundle)
        elif name == "find_nearby_gas_and_ev_stations":
            result = await self._execute_combined_search_call(
                args, gas_location, ev_location, bundle
            )
        elif name == "get_gas_price_forecast":
            result = await self._execute_forecast_call(args, gas_location)
        else:
            result = {"error": f"Unknown tool '{name}'."}
        return result, bundle

    async def _execute_ev_chargers_call(
        self,
        args: dict[str, Any],
        location: tuple[float, float] | None,
        bundle: StationBundle,
    ) -> dict[str, Any]:
        place = args.get("location") or None
        max_distance_km = _coerce_positive_number(args.get("max_distance_km"))
        networks = _coerce_string_list(args.get("networks"))
        exclude_networks = _coerce_string_list(args.get("exclude_networks"))
        connector_types = _coerce_connector_list(args.get("connector_types"))
        charger_levels = _coerce_charger_level_list(args.get("charger_levels"))
        chargers_range = _coerce_numeric_range(args, "chargers")
        power_kw_range = _coerce_numeric_range(args, "power_kw")
        voltage_range = _coerce_numeric_range(args, "voltage")
        amperage_range = _coerce_numeric_range(args, "amperage")
        sort_by = _coerce_ev_sort_by(args.get("sort_by"))
        sort_order = (
            _coerce_ev_sort_order(args.get("sort_order"), sort_by) if sort_by else None
        )
        top_n = _coerce_top_n(args.get("top_n"))
        has_filters = any(
            [
                networks,
                exclude_networks,
                connector_types,
                charger_levels,
                _range_is_set(*chargers_range),
                _any_range_set(power_kw_range, voltage_range, amperage_range),
                sort_by is not None,
            ]
        )

        if place:
            query, lat, lon = place, None, None
        elif location is not None:
            query, lat, lon = None, location[0], location[1]
        else:
            return {"error": NO_LOCATION_MESSAGE}

        try:
            result = await self._ev_search.search_nearest_ev_stations(
                query=query,
                lat=lat,
                lon=lon,
                limit=EV_FILTERED_FETCH_LIMIT if has_filters else 20,
                radius_km=max_distance_km,
            )
        except GeocodingError:
            return {"error": LOCATION_NOT_FOUND_MESSAGE}
        except EvDirectoryError as exc:
            return {"error": f"EV charger lookup failed: {exc}"}
        except Exception as exc:  # a tool call must never crash the whole request
            return {"error": f"EV charger lookup failed unexpectedly: {exc}"}

        if not result.stations:
            return {"error": "No EV charging stations were found near that location."}

        stations = _filter_ev_stations(
            result.stations,
            networks,
            exclude_networks,
            connector_types,
            charger_levels,
            chargers_range,
            power_kw_range,
            voltage_range,
            amperage_range,
        )
        if not stations:
            return {
                "error": _no_ev_match_message(
                    networks,
                    exclude_networks,
                    connector_types,
                    charger_levels,
                    chargers_range,
                    power_kw_range,
                    voltage_range,
                    amperage_range,
                    any_nearby=True,
                    scanned_count=len(result.stations),
                )
            }

        if sort_by:
            stations = _sort_ev_stations_by_metric(stations, sort_by, sort_order)
            if not stations:
                return {
                    "error": (
                        f"None of the nearby stations report {sort_by.replace('_', ' ')} "
                        f"data for their chargers, so a '{sort_order}' ranking isn't "
                        "possible here — only some stations (mostly Open Charge "
                        "Map-sourced) include this level of detail."
                    )
                }

        # Order (by distance, or by sort_by above) is already correct, so
        # the nearest/best matches are always what survives the cap — a
        # broad filter can still leave dozens of matches, and every one
        # relayed back costs real tokens.
        total_matching = len(stations)
        stations = stations[:EV_MAX_STATIONS_IN_RESPONSE]
        # Same rule as the gas tool: once sort_by picks a specific "the
        # answer" station (top_match), only that shows as a card — a
        # plain, unranked search has no single answer, so its full
        # matching list becomes cards instead. top_n widens that from 1
        # to N cards for a "top N ranked" question, still just the
        # highlighted answer(s), not the whole candidate pool.
        highlight_count = top_n or 1
        bundle.ev_stations = (
            stations[:highlight_count] if sort_by and stations else stations
        )

        payload: dict[str, Any] = {
            "searched_lat": result.lat,
            "searched_lon": result.lon,
            "station_count": len(stations),
            "stations": [_ev_station_summary(s) for s in stations],
            # Directly answers "what charger types are near me?" without
            # the model needing to enumerate/dedupe the station list
            # itself — it's fine at relaying a plain list, just
            # unreliable at comparing/ranking one.
            "connector_types_available": sorted(
                {c.upper() for s in stations for c in s.connector_types}
            ),
        }
        if total_matching > len(stations):
            payload["total_matching_count"] = total_matching
            payload["note"] = (
                f"{total_matching} stations matched — showing the nearest "
                f"{len(stations)}. Mention there are more if the user asks "
                "for a longer list, but don't invent additional stations "
                "yourself."
            )
        if sort_by:
            payload["sorted_by"] = (
                f"{sort_by} {sort_order} first — the list below is already in "
                "this exact order; relay it as-is, do not re-sort or "
                "recompute the ranking"
            )
            payload["top_match"] = _ev_station_summary(stations[0])

        filters_applied: dict[str, Any] = {}
        if networks:
            filters_applied["networks"] = networks
        if exclude_networks:
            filters_applied["exclude_networks"] = exclude_networks
        if connector_types:
            filters_applied["connector_types"] = connector_types
        if charger_levels:
            filters_applied["charger_levels"] = charger_levels
        if _range_is_set(*chargers_range):
            filters_applied["chargers_range"] = chargers_range
        if _range_is_set(*power_kw_range):
            filters_applied["power_kw_range"] = power_kw_range
        if _range_is_set(*voltage_range):
            filters_applied["voltage_range"] = voltage_range
        if _range_is_set(*amperage_range):
            filters_applied["amperage_range"] = amperage_range
        if sort_by:
            filters_applied["sort_by"] = sort_by
            filters_applied["sort_order"] = sort_order
        if top_n:
            filters_applied["top_n"] = top_n
        if filters_applied:
            payload["filters_applied"] = filters_applied
        return payload

    async def _execute_combined_search_call(
        self,
        args: dict[str, Any],
        gas_location: tuple[float, float] | None,
        ev_location: tuple[float, float] | None,
        bundle: StationBundle,
    ) -> dict[str, Any]:
        place = args.get("location") or None
        max_distance_miles = _coerce_positive_number(args.get("max_distance_miles"))
        max_distance_km = _coerce_positive_number(args.get("max_distance_km"))
        if max_distance_miles is None and max_distance_km is not None:
            max_distance_miles = max_distance_km * 0.621371
        brands = _coerce_string_list(args.get("brands"))
        exclude_brands = _coerce_string_list(args.get("exclude_brands"))
        networks = _coerce_string_list(args.get("networks"))
        exclude_networks = _coerce_string_list(args.get("exclude_networks"))
        # Name-based (not station_id — the model never sees one) exclusion
        # for "find another pair" follow-ups, so a repeat ask gets a
        # genuinely different, code-verified closest_pair instead of the
        # model inventing one from an earlier response's station lists.
        exclude_gas_stations = _coerce_string_list(args.get("exclude_gas_stations"))
        exclude_ev_stations = _coerce_string_list(args.get("exclude_ev_stations"))

        # gas_location is the arbitrary-but-consistent tie-breaker when
        # neither a place was named nor GPS was shared — the two are
        # identical whenever GPS *is* shared (see ChatScreen's own
        # gasLocation/evLocation computation), so this only matters when
        # the Gas and EV tabs were last searched at different places.
        fallback_location = gas_location if gas_location is not None else ev_location
        if place:
            query, lat, lon = place, None, None
        elif fallback_location is not None:
            query, lat, lon = None, fallback_location[0], fallback_location[1]
        else:
            return {"error": NO_LOCATION_MESSAGE}

        # query/lat/lon are passed through to gas and EV independently
        # below (each resolves its own geocoding, same as before this
        # brand_id shortcut existed) rather than resolved once here —
        # that's what lets a bad `query` fail both sides identically,
        # each raising its own GeocodingError, which the
        # isinstance(..., GeocodingError) check below relies on to tell
        # "bad location" apart from "no stations found there".
        brand_ids = _known_brand_ids(brands)
        gas_coro = (
            _search_stations_by_brand_ids(
                self._gas_price, brand_ids, query=query, lat=lat, lon=lon
            )
            if brand_ids is not None
            else self._gas_price.search_nearest_stations(
                query=query, lat=lat, lon=lon, limit=GAS_PRICE_PAGE_SIZE
            )
        )

        gas_result, ev_result = await asyncio.gather(
            gas_coro,
            self._ev_search.search_nearest_ev_stations(
                query=query, lat=lat, lon=lon, limit=GAS_AND_EV_FETCH_LIMIT, radius_km=max_distance_km
            ),
            return_exceptions=True,
        )

        gas_stations: list[GasStation] = []
        gas_note: str | None = None
        if isinstance(gas_result, BaseException):
            gas_note = _gas_lookup_error_note(gas_result)
        else:
            gas_stations = _filter_stations(
                gas_result.stations, brands, exclude_brands, max_distance_miles, brand_tier=None
            )
            gas_stations = _exclude_stations_by_name(gas_stations, exclude_gas_stations)
            if not gas_stations:
                gas_note = "No matching gas stations were found nearby."

        ev_stations: list[EvStation] = []
        ev_note: str | None = None
        if isinstance(ev_result, BaseException):
            ev_note = _ev_lookup_error_note(ev_result)
        else:
            ev_stations = _filter_ev_stations(
                ev_result.stations,
                networks,
                exclude_networks,
                None,
                None,
                (None, None, None),
                (None, None, None),
                (None, None, None),
                (None, None, None),
            )
            ev_stations = _exclude_stations_by_name(ev_stations, exclude_ev_stations)
            if not ev_stations:
                ev_note = "No matching EV chargers were found nearby."

        if not gas_stations and not ev_stations:
            if isinstance(gas_result, GeocodingError) and isinstance(ev_result, GeocodingError):
                return {"error": LOCATION_NOT_FOUND_MESSAGE}
            return {
                "error": " ".join(note for note in (gas_note, ev_note) if note)
                or "No gas stations or EV chargers were found near that location."
            }

        # At least one side succeeded with real stations at this point,
        # so exactly one of these branches always has a result to read
        # searched_lat/lon from.
        if not isinstance(gas_result, BaseException):
            res_lat, res_lon = gas_result.lat, gas_result.lon
        else:
            res_lat, res_lon = ev_result.lat, ev_result.lon

        closest = (
            _closest_gas_ev_pair(gas_stations, ev_stations)
            if gas_stations and ev_stations
            else None
        )

        gas_stations = gas_stations[:GAS_AND_EV_MAX_STATIONS_IN_RESPONSE]
        ev_stations = ev_stations[:GAS_AND_EV_MAX_STATIONS_IN_RESPONSE]
        # Same rule as the other two tools: a "closest pair" question has
        # one specific answer — the pair itself — so only those two
        # stations become cards, not every nearby candidate either side
        # searched through. Without a pair (one side came up empty), the
        # reply is a general listing of whichever side succeeded, so that
        # full list becomes cards instead.
        if closest:
            gas, ev, _distance = closest
            bundle.gas_stations = [gas]
            bundle.ev_stations = [ev]
        else:
            bundle.gas_stations = gas_stations
            bundle.ev_stations = ev_stations

        payload: dict[str, Any] = {
            "searched_lat": res_lat,
            "searched_lon": res_lon,
            "gas_station_count": len(gas_stations),
            "ev_station_count": len(ev_stations),
        }
        if gas_note:
            payload["gas_lookup_note"] = gas_note
        if ev_note:
            payload["ev_lookup_note"] = ev_note

        if closest:
            gas, ev, distance = closest
            payload["closest_pair"] = {
                "gas_station": _station_summary(gas),
                "ev_charger": _ev_station_summary(ev),
                "distance_between_miles": round(distance, 2),
            }
            # Deliberately omits the full gas_stations/ev_stations
            # candidate lists here (unlike the no-pair branch below) —
            # confirmed live: with the broader lists visible alongside
            # closest_pair, the model sometimes named a DIFFERENT station
            # from those lists instead of relaying the verified pair, even
            # on a first-time request. Taking the other candidates out of
            # its context entirely removes that option, not just asks it
            # not to.
            payload["closest_pair_note"] = (
                "closest_pair is already the minimum-distance pair between "
                "a gas station and an EV charger, computed directly from "
                "real coordinates — relay ONLY these two stations, exactly "
                "as given; never estimate, recompute, or second-guess this "
                "distance, and never mention or invent any other station "
                "yourself, even though gas_station_count/ev_station_count "
                "show more exist nearby."
            )
        else:
            payload["gas_stations"] = [_station_summary(s) for s in gas_stations]
            payload["ev_stations"] = [_ev_station_summary(s) for s in ev_stations]
            if gas_stations and ev_stations:
                payload["closest_pair_note"] = (
                    "No coordinates were available to compute a closest "
                    "gas/EV pair for these results."
                )

        filters_applied: dict[str, Any] = {}
        if brands:
            filters_applied["brands"] = brands
        if exclude_brands:
            filters_applied["exclude_brands"] = exclude_brands
        if networks:
            filters_applied["networks"] = networks
        if exclude_networks:
            filters_applied["exclude_networks"] = exclude_networks
        if max_distance_miles is not None:
            filters_applied["max_distance_miles"] = max_distance_miles
        if exclude_gas_stations:
            filters_applied["exclude_gas_stations"] = exclude_gas_stations
        if exclude_ev_stations:
            filters_applied["exclude_ev_stations"] = exclude_ev_stations
        if filters_applied:
            payload["filters_applied"] = filters_applied
        return payload

    async def _execute_forecast_call(
        self, args: dict[str, Any], location: tuple[float, float] | None
    ) -> dict[str, Any]:
        place = args.get("location") or None
        if place:
            try:
                lat, lon = await geocode(place)
            except GeocodingError:
                return {"error": LOCATION_NOT_FOUND_MESSAGE}
        elif location is not None:
            lat, lon = location
        else:
            return {"error": NO_LOCATION_MESSAGE}

        try:
            forecast = await self._forecast.forecast(lat, lon)
        except MissingSearchData:
            return {"error": "Missing search parameters for that location."}
        except CloudflareBlocked:
            return {
                "error": (
                    "The gas price service is temporarily blocking automated requests. "
                    "Try again shortly."
                )
            }
        except (LibraryError, APIError) as exc:
            return {"error": f"Gas price lookup failed: {exc}"}
        except Exception as exc:  # a tool call must never crash the whole request
            return {"error": f"Gas price forecast failed unexpectedly: {exc}"}

        if forecast.stations_sampled == 0:
            return {"error": "No nearby gas stations were found to base a forecast on."}

        payload = forecast.model_dump()
        payload["note"] = (
            "This is a next-day forecast ONLY — there is no data for any "
            "day beyond tomorrow, so never present this as a multi-day "
            "trend or answer a further-out question with it. Every "
            "price/change/direction field above is already computed — "
            "relay it as-is, never recompute or re-derive it yourself."
        )
        if forecast.source == "none":
            payload["note"] += (
                " source is 'none': no regional trend data was available "
                "for this area, so the forecasted values are identical to "
                "today's — tell the user a real forecast isn't available "
                "here rather than presenting 'no change' as an actual "
                "prediction."
            )
        return payload

    async def _execute_find_stations_call(
        self,
        args: dict[str, Any],
        location: tuple[float, float] | None,
        bundle: StationBundle,
    ) -> dict[str, Any]:
        place = args.get("location") or None
        brands = _coerce_string_list(args.get("brands"))
        exclude_brands = _coerce_string_list(args.get("exclude_brands"))
        max_distance_miles = _coerce_positive_number(args.get("max_distance_miles"))
        max_distance_km = _coerce_positive_number(args.get("max_distance_km"))
        # max_distance_miles wins if the model (against instructions) sets
        # both; the conversion (never left to the model) happens once
        # here, so all the existing distance-filtering/pagination logic
        # below only ever deals in miles.
        if max_distance_miles is None and max_distance_km is not None:
            max_distance_miles = max_distance_km * 0.621371
        fuel_grade = _coerce_fuel_grade(args.get("fuel_grade"))
        brand_tier = _coerce_brand_tier(args.get("brand_tier"))
        max_report_age_minutes = _coerce_positive_number(args.get("max_report_age_minutes"))
        sort_by_recency = _coerce_bool(args.get("sort_by_recency"))
        sort_by_distance = _coerce_bool(args.get("sort_by_distance"))
        top_n = _coerce_top_n(args.get("top_n"))
        # Each grade has its own independent report time — the same
        # "regular" default already documented for a plain "cheapest gas"
        # question with no grade named applies here too.
        recency_grade = fuel_grade or "regular"
        # exclude_brands, fuel_grade, max_report_age_minutes, and
        # sort_by_recency deliberately don't count as "filters" for
        # pagination purposes — they narrow/sort whatever was already
        # fetched, they never justify fetching more of it.
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
                    brand_id_scoped,
                ) = await self._fetch_and_filter_stations(
                    query=query,
                    lat=lat,
                    lon=lon,
                    brands=brands,
                    max_distance_miles=max_distance_miles,
                    brand_tier=brand_tier,
                )
            else:
                result = await self._gas_price.search_nearest_stations(
                    query=query, lat=lat, lon=lon, limit=GAS_PRICE_PAGE_SIZE
                )
                all_stations = result.stations
                res_lat, res_lon = result.lat, result.lon
                scanned_count = len(all_stations)
                any_nearby = bool(all_stations)
                brand_id_scoped = False
        except GeocodingError:
            return {"error": LOCATION_NOT_FOUND_MESSAGE}
        except MissingSearchData:
            return {"error": "Missing search parameters for that location."}
        except CloudflareBlocked:
            return {
                "error": (
                    "The gas price service is temporarily blocking automated requests. "
                    "Try again shortly."
                )
            }
        except (LibraryError, APIError) as exc:
            return {"error": f"Gas price lookup failed: {exc}"}
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
                    brand_id_scoped,
                )
            }

        if max_report_age_minutes is not None:
            stations = [
                s
                for s in stations
                if (m := _station_report_minutes(s, recency_grade)) is not None
                and m <= max_report_age_minutes
            ]
            if not stations:
                return {
                    "error": (
                        f"No stations had a {recency_grade} price reported within "
                        f"the last {max_report_age_minutes:g} minutes."
                    )
                }

        # Each of the three possible "the answer is THIS one station"
        # rankings is computed independently below — a question can
        # reasonably ask for more than one at once (e.g. "cheapest AND
        # most recently updated"), so none of these are mutually
        # exclusive with each other. Which one wins the final `stations`
        # ORDER (and the sorted_by instruction text) is decided
        # separately afterward.
        cheapest: dict[str, Any] | None = None
        cheapest_station: GasStation | None = None
        average_price: float | None = None
        average_price_formatted: str | None = None
        average_price_unit: str | None = None
        price_sorted_stations: list[GasStation] | None = None
        if fuel_grade:
            price_sorted_stations = _sort_by_fuel_grade(stations, fuel_grade)
            if not price_sorted_stations:
                return {"error": _no_fuel_grade_message(fuel_grade, len(stations))}
            cheapest_station = price_sorted_stations[0]
            cheapest = _station_summary(cheapest_station)
            # Adds a raw price + its unit alongside the formatted string
            # already in cheapest, so a follow-up calculate_fuel_cost
            # call can use this price directly rather than parsing it
            # back out of e.g. "168.9¢".
            price_info = _price_unit_and_value_for_station(cheapest_station, fuel_grade)
            if price_info is not None:
                cheapest["price_per_litre"], cheapest["price_unit"] = price_info
            average_info = _average_fuel_price(price_sorted_stations, fuel_grade)
            if average_info is not None:
                average_price, average_price_formatted = average_info
                if price_info is not None:
                    average_price_unit = price_info[1]

        most_recent: dict[str, Any] | None = None
        most_recent_station: GasStation | None = None
        recency_sorted_stations: list[GasStation] | None = None
        if sort_by_recency:
            recency_sorted_stations = _sort_by_recency(stations, recency_grade)
            if not recency_sorted_stations:
                return {
                    "error": (
                        f"None of the matching stations have a recent "
                        f"{recency_grade} price report to rank by."
                    )
                }
            most_recent_station = recency_sorted_stations[0]
            most_recent = _station_summary(most_recent_station)

        nearest: dict[str, Any] | None = None
        nearest_station: GasStation | None = None
        distance_sorted_stations: list[GasStation] | None = None
        if sort_by_distance:
            distance_sorted_stations = _sort_by_distance(stations)
            if not distance_sorted_stations:
                return {
                    "error": (
                        "None of the matching stations have a known "
                        "distance to rank by."
                    )
                }
            nearest_station = distance_sorted_stations[0]
            nearest = _station_summary(nearest_station)

        # Final list order + the instruction describing it: whichever
        # ranking was actually asked for wins, distance > recency > price
        # — distance is the most concrete/unambiguous signal, and recency
        # already won over price on its own (the "more specific ask" —
        # same reasoning extends to distance being even more specific).
        sorted_by: str | None = None
        if sort_by_distance:
            stations = distance_sorted_stations
            sorted_by = (
                "distance ascending (closest first) — the list below is "
                "already in this exact order; relay it as-is, do not "
                "re-sort or recompute the ranking"
            )
        elif sort_by_recency:
            stations = recency_sorted_stations
            sorted_by = (
                f"{recency_grade}_price report recency, most recently reported "
                "first — the list below is already in this exact order; "
                "relay it as-is, do not re-sort or re-derive the ranking"
            )
        elif fuel_grade:
            # An explicit instruction, not just data — the model is
            # unreliable at comparing many prices itself (see
            # SYSTEM_PROMPT), so this spells out that the order and the
            # cheapest/average_price fields below are already correct.
            stations = price_sorted_stations
            sorted_by = (
                f"{fuel_grade}_price ascending (cheapest first) — the "
                "list below is already in this exact order; relay it "
                "as-is, do not re-sort or recompute the ranking"
            )

        # Cards should mirror what the reply actually highlights, not the
        # whole candidate pool the tool searched through — once a
        # specific "the answer" station exists (cheapest/most_recent/
        # nearest), only that shows as a card, same as a "closest pair"
        # question shows just the pair, not every nearby station. A
        # plain, unranked search with no explicit count named defaults
        # to the nearest few (DEFAULT_UNRANKED_TOP_N) instead of every
        # match — see that constant's own comment for why. top_n
        # overrides this to the top N of the already precedence-resolved
        # `stations` order — a "top N ranked" (or plain "N nearby") ask
        # wants exactly N cards, not each field's own single pick merged
        # together.
        is_plain_unranked_search = (
            not top_n
            and cheapest_station is None
            and most_recent_station is None
            and nearest_station is None
        )
        if top_n:
            highlighted_stations = stations[:top_n]
        elif is_plain_unranked_search:
            highlighted_stations = stations[:DEFAULT_UNRANKED_TOP_N]
        else:
            highlighted_stations = [
                s
                for s in (cheapest_station, most_recent_station, nearest_station)
                if s is not None
            ]
        bundle.gas_stations = (
            _merge_stations([], highlighted_stations) if highlighted_stations else stations
        )

        # The model only ever sees this same capped set for a plain
        # unranked search too — giving it the full pool here would let
        # it describe more stations in its reply than the cards actually
        # show. Every other case (top_n given, or a ranking's own
        # single-answer field) is unaffected and still sees every match.
        payload_stations = highlighted_stations if is_plain_unranked_search else stations

        payload: dict[str, Any] = {
            "searched_lat": res_lat,
            "searched_lon": res_lon,
            "station_count": len(stations),
            "stations": [_station_summary(s) for s in payload_stations],
        }
        if is_plain_unranked_search and len(stations) > DEFAULT_UNRANKED_TOP_N:
            payload["note"] = (
                f"Only the {DEFAULT_UNRANKED_TOP_N} nearest of the "
                f"{len(stations)} matching stations are included above — "
                "tell the user more are available and to ask for a "
                "specific count (e.g. 'the 10 nearest') to see more."
            )
        if sorted_by:
            payload["sorted_by"] = sorted_by
        if fuel_grade:
            payload["cheapest"] = cheapest
            payload["average_price"] = average_price
            payload["average_price_formatted"] = average_price_formatted
            payload["average_price_unit"] = average_price_unit
        if sort_by_recency:
            payload["most_recent"] = most_recent
        if sort_by_distance:
            payload["nearest"] = nearest

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
        if max_report_age_minutes is not None:
            filters_applied["max_report_age_minutes"] = max_report_age_minutes
        if sort_by_recency:
            filters_applied["sort_by_recency"] = True
        if sort_by_distance:
            filters_applied["sort_by_distance"] = True
        if top_n:
            filters_applied["top_n"] = top_n
        if filters_applied:
            payload["filters_applied"] = filters_applied
        return payload


def get_chat_service(
    gas_price: GasPriceService = Depends(get_gas_price_service),
    ev_search: EvSearchService = Depends(get_ev_search_service),
    forecast: ForecastService = Depends(get_forecast_service),
) -> ChatService:
    return ChatService(gas_price, ev_search, forecast)
