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
# Only "costco" is seeded here, since it's the only id confirmed live
# (verified across 3 real Ontario locations in manual testing). Every
# other entry is learned from real traffic as it happens, rather than
# guessed — a wrong guessed id would silently return wrong results,
# worse than today's honest "not found".
_KNOWN_BRAND_IDS: dict[str, int] = {
    "costco": 38,
}


def normalize_brand_name(name: str) -> str:
    return name.strip().lower()


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
