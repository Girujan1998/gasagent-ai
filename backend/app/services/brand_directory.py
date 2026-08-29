# A brand-name -> GasBuddy brand_id lookup, used to scope a station search
# to one specific chain server-side (see gas_price_client.py's `brand_id`
# param) instead of hoping that chain shows up in a nearest-any-brand
# pool. GasBuddy publishes no such table anywhere — the only way to learn
# an id is to observe the `brandId` field already present in every raw
# station's `brands` list, which gas_price_client.py otherwise discards.
# Module-level, not per-instance — mirrors country_lookup.py's own cache
# (see that file's comment for why) — so every station ever parsed, by
# any request, opportunistically grows this for free.
#
# Every entry below was verified live (not guessed) — a wrong guessed id
# would silently return wrong results, worse than today's honest "not
# found". "costco" was the first, confirmed across 3 real Ontario
# locations; the rest were confirmed 2026-08-29 by scanning real,
# unfiltered nearest-station results — the Canadian entries across
# Toronto ON, Calgary AB, Halifax NS, and Vancouver BC, the US-only
# entries (Exxon/BP/Sunoco/Marathon/Valero/Speedway, none of which
# operate in Canada) across Dallas/San Antonio TX, Philadelphia PA, and
# Columbus OH — reading off each station's own self-reported brandId.
# All 18 of WELL_KNOWN_BRANDS (see chat_agent_client.py) are covered.
# "76" (Phillips 66's West Coast brand, not in WELL_KNOWN_BRANDS) was
# added the same way, confirmed in Los Angeles CA.
#
# The remaining entries below were confirmed 2026-08-29 in a broader
# regional pass (Houston/Dallas/San Antonio/El Paso TX, Denver CO,
# Chicago IL, Minneapolis MN, Des Moines IA, Philadelphia/Pittsburgh PA,
# Baltimore MD, Cincinnati OH, Boston MA, Oklahoma City OK, Honolulu HI,
# Calgary AB, Vancouver BC, Ottawa ON, St. John's NL). A station's own
# brandId is sometimes null even when its brand name appears in the
# data (e.g. an independent-ish "Stinson" station near Ottawa) — that's
# a real GasBuddy data gap, not something to guess around, so a handful
# of asked-for brands below are still genuinely unconfirmed:
# Murphy Express (distinct brand from Murphy USA), Sam's Club, Walmart,
# RaceTrac, RaceWay, Sheetz, Cenex, Kwik Trip (distinct from Kwik Star),
# Pilot, Flying J, TravelCenters of America, Buc-ee's (the last four are
# highway/travel-center chains — none showed up scanning city downtown
# cores, which makes sense; they'd need a highway-adjacent search
# point instead), Aloha Petroleum (Honolulu hit a GasBuddy-side API
# error, unrelated to rate-limiting), Fas Gas Plus (only the related
# but distinct "Fas Gas" banner turned up), Canco, UFA, GOCO, and the
# Quebec City-area brands (Harnois/Sonic/Crevier/EKO/Petro-T/XTR —
# "Quebec City, Quebec" didn't geocode, never actually searched).
#
# The batch above was resolved a second time, using the exact real
# coordinates of a known station of each remaining brand instead of a
# city center — found 17 more of the above list this way. Still
# genuinely unconfirmed after that: TravelCenters of America, Aloha
# Petroleum (its own "Aloha" banner is the one that's actually stored —
# see the aliasing below), Fas Gas Plus, UFA, GOCO, Petro-T (its "Petro
# T" banner, no hyphen, is what's actually stored — see below), and
# XTR — each for its own reason (a null brandId on that specific
# station, a same-area brand that turned out distinct on inspection, or
# a GasBuddy-side API error for that location unrelated to rate-
# limiting). "Canco" was captured as a *connected* brand on a
# multi-branded station (its own name never appeared as the primary
# brand in any of that day's raw responses) — confirmed by re-reading
# connected_brand, not just brand, on the underlying GasStation objects.
_KNOWN_BRAND_IDS: dict[str, int] = {
    "costco": 38,
    "shell": 122,
    "esso": 13,
    "exxon": 48,
    "mobil": 92,
    "chevron": 31,
    "bp": 23,
    "circle k": 32,
    "sunoco": 130,
    "marathon": 87,
    "valero": 142,
    "speedway": 125,
    "7-eleven": 14,
    "petro-canada": 100,
    "canadian tire": 26,
    "husky": 68,
    "ultramar": 140,
    "pioneer": 103,
    "76": 15,
    "arco": 20,
    "amoco": 367,
    "citgo": 33,
    "casey's": 28,
    "centex": 2140,
    "co-op": 37,
    "conoco": 36,
    "cumberland farms": 43,
    "dk": 2081,
    "domo": 47,
    "getgo": 180,
    "gulf": 61,
    "holiday": 165,
    "irving": 71,
    "kwik star": 2164,
    "macewen": 84,
    "maverik": 88,
    "murphy usa": 94,
    "north atlantic": 2008,
    "phillips 66": 101,
    "quiktrip": 108,
    "royal farms": 116,
    "sinclair": 123,
    "super save gas": 2155,
    "tempo": 133,
    "texaco": 135,
    "thorntons": 136,
    "united dairy farmers": 336,
    "wawa": 143,
    # GasBuddy's own name for this brand includes "Travel Stop" — aliased
    # so a plain "Love's" lookup (how the brand's actually asked for)
    # still resolves.
    "love's": 82,
    "love's travel stop": 82,
    # Verified but not one of the brands actually asked for — a
    # different, related banner from the still-unconfirmed "Fas Gas
    # Plus" above, kept since it's real and free.
    "fas gas": 51,
    "murphy express": 2038,
    "sam's club": 119,
    "walmart": 238,
    "racetrac": 109,
    "raceway": 111,
    "kwik trip": 79,
    "cenex": 29,
    "sheetz": 121,
    "pilot": 102,
    "flying j": 55,
    "buc-ee's": 345,
    "canco": 2005,
    "stinson": 2015,
    "harnois": 312,
    "sonic": 124,
    "crevier": 64,
    "eko": 2004,
    # GasBuddy's own name for this one is just "Aloha" — aliased so
    # "Aloha Petroleum" (how the brand's actually asked for) resolves.
    "aloha": 19,
    "aloha petroleum": 19,
    # GasBuddy's own name has no hyphen ("Petro T") — aliased so
    # "Petro-T"/"Pétro-T" (how the brand's actually asked for) resolve.
    "petro t": 318,
    "petro-t": 318,
    "pétro-t": 318,
}


def normalize_brand_name(name: str) -> str:
    # Folds the typographic right single quote (’) to a plain apostrophe
    # ('), so "Sam's Club"/"Buc-ee's" resolve the same way regardless of
    # which one a source (GasBuddy's own data, a user, the model) used —
    # confirmed live these genuinely differ otherwise, since this is a
    # plain string key, not a fuzzy match.
    return name.strip().lower().replace("’", "'")


def record_brand_id(name: str, brand_id: int | str | None) -> None:
    """Learns a brand's id from a real station response, if not already
    known. First-seen wins — a brand's id should never legitimately
    change, so a later, possibly-anomalous value never overwrites a
    good cached one."""
    if not name or brand_id is None:
        return
    key = normalize_brand_name(name)
    if key in _KNOWN_BRAND_IDS:
        return
    try:
        _KNOWN_BRAND_IDS[key] = int(brand_id)
    except (TypeError, ValueError):
        return


def get_brand_id(name: str) -> int | None:
    return _KNOWN_BRAND_IDS.get(normalize_brand_name(name))
