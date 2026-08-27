import time
from typing import Any

import httpx

from app.config import get_settings
from app.models.schemas import EvConnectorDetail, EvStation, EvStationComment

EV_COMMUNITY_URL = "https://api.openchargemap.io/v3/poi/"

# A wide, fixed radius reused across every caller (List, Load More, Map,
# refresh) — see the module-level cache below, which is what actually
# makes this "efficient": one real community-source request per ~grid
# cell covers all of them, rather than one per call.
EV_COMMUNITY_SEARCH_RADIUS_MILES = 18.64  # ~30km, matching ev_directory_client's map radius
# The community source returns nearest-first regardless of data
# provenance, and directory-reimported duplicates usually vastly
# outnumber genuinely-unique stations — a lower cap here was found
# (live, for a Cambridge, ON test point) to cut off 6 of 24
# genuinely-unique stations before the fetch ever reached the edge of
# the search radius, because closer duplicate entries used up the budget
# first. 500 was confirmed (same test point) to reach the full radius.
# This only affects one cached request's response size, not how often
# the community source gets called, so there's no added load from
# raising it.
EV_COMMUNITY_MAX_RESULTS = 500

# The community source re-imports the directory source's own feed as one
# of its data sources — most of its results, in practice, are tagged
# with this as their DataProvider. It's tempting to use that tag as a
# cheap dedup shortcut (skip anything directory-tagged, since
# EvDirectoryService should already have it) — but that tag only
# reflects where the community source *originally* imported a record
# from, not whether it's still in the directory source's *current* live
# feed. Confirmed live: a station tagged with a stale provider and no
# status update since 2019 was absent from EvDirectoryService's live
# results entirely — the community source's copy had gone stale without
# the directory source's own feed keeping it in sync. Real dedup happens
# by proximity against this search's actual directory-source results
# (see ev_search.py) instead, so a stale tag can't hide a station that
# genuinely isn't a current duplicate.

# The community source's own StatusType IDs whose IsOperational flag
# (per its own reference data) is true: 10/20 are automated live-status
# codes, 30 covers a charger that's momentarily busy/offline but not
# actually broken, 50 is the plain "Operational" flag, 75 is a
# partly-working multi-connector station. Using only 50 originally
# missed genuinely current stations reported through the other
# operational codes.
STATUS_IDS_OPERATIONAL = "10,20,30,50,75"
# 1=Public, 4=Public - Membership Required, 5=Public - Pay At Location,
# 7=Public - Notice Required — all genuinely public (usable by any driver,
# just with an extra step), unlike 2/3/6 (private) or 0 (unknown). Using
# only ID 1 here originally excluded a large amount of real, currently
# usable infrastructure — for one Cambridge, ON test location, it dropped
# a large share of the fast-charging stations in the area (2 surviving
# directory-only stations vs. 24 with the full public set).
USAGE_IDS_PUBLIC = "1,4,5,7"

# No published rate limit was found for keyed requests against this
# source, so this errs on the conservative side regardless: real station
# listings don't change minute to minute, and every caller in a session
# (List's first page, Load More, Map's own fetch, a refresh) shares this
# same cache rather than each issuing its own request.
CACHE_TTL_SECONDS = 3600
# Rounds the query point to a coarse grid before caching, so nearby
# searches (a few km apart) share one cache entry instead of each missing
# it by a fraction of a degree. ~0.1 degrees is roughly 11km at these
# latitudes — comfortably inside the 30km fetch radius even for a point at
# the far edge of its grid cell.
CACHE_GRID_DEGREES = 0.1

# station_id -> Level.ID, mirroring the directory source's own
# level1/level2/dc_fast split.
LEVEL_ID_TO_FIELD = {1: "level1_count", 2: "level2_count", 3: "dc_fast_count"}

# The community source's connector Titles mapped onto the same short
# codes the directory source uses (see ev_directory_client.py / the
# mobile app's CONNECTOR_LABELS), so a merged list formats identically
# regardless of which source a station came from. Anything not in this
# table is passed through as the community source's own title text —
# same "don't hide it, just don't bother normalizing it" fallback the
# mobile formatter already uses for unrecognized directory-source codes.
CONNECTOR_TITLE_TO_CODE = {
    "Type 1 (J1772)": "J1772",
    "CHAdeMO": "CHADEMO",
    "CCS (Type 1)": "J1772COMBO",
    "NACS / Tesla Supercharger": "TESLA",
    "Tesla (Model S/X)": "TESLA",
}


class EvCommunityError(Exception):
    """Raised when the EV community-data API request fails."""


def _cache_key(lat: float, lon: float) -> tuple[float, float]:
    return (
        round(lat / CACHE_GRID_DEGREES) * CACHE_GRID_DEGREES,
        round(lon / CACHE_GRID_DEGREES) * CACHE_GRID_DEGREES,
    )


def _connector_code(title: str | None) -> str | None:
    if not title:
        return None
    return CONNECTOR_TITLE_TO_CODE.get(title, title)


def _build_address(address_info: dict[str, Any]) -> str | None:
    parts = [
        address_info.get("AddressLine1"),
        address_info.get("Town"),
        address_info.get("StateOrProvince"),
    ]
    joined = ", ".join(part for part in parts if part)
    return joined or None


def _comments(raw_comments: list[dict[str, Any]] | None) -> list[EvStationComment]:
    comments = []
    for raw in raw_comments or []:
        text = (raw.get("Comment") or "").strip()
        if not text:
            # A check-in with no written note — nothing to show.
            continue
        checkin_status_type = raw.get("CheckinStatusType") or {}
        comments.append(
            EvStationComment(
                author=raw.get("UserName") or "Anonymous",
                text=text,
                date=raw.get("DateCreated"),
                checkin_status=checkin_status_type.get("Title"),
                checkin_is_positive=checkin_status_type.get("IsPositive"),
            )
        )
    return comments


def _photo_urls(raw_media: list[dict[str, Any]] | None) -> list[str]:
    return [
        item["ItemURL"]
        for item in (raw_media or [])
        if item.get("IsEnabled") and not item.get("IsVideo") and item.get("ItemURL")
    ]


def _connector_details(
    connections: list[dict[str, Any]],
) -> list[EvConnectorDetail]:
    # The directory source has no equivalent per-connector
    # Amps/Voltage/PowerKW data at all, so this is community-source-only,
    # same as comments/photos. Kept one entry per raw Connection rather
    # than deduped by type, since two connectors of the same type can
    # have different specs (e.g. a J1772 on a slower and a faster
    # charger at the same station).
    details = []
    for connection in connections:
        code = _connector_code((connection.get("ConnectionType") or {}).get("Title"))
        amps = connection.get("Amps")
        voltage = connection.get("Voltage")
        power_kw = connection.get("PowerKW")
        if not code and amps is None and voltage is None and power_kw is None:
            continue
        details.append(
            EvConnectorDetail(
                connector_type=code or "Unknown",
                quantity=connection.get("Quantity"),
                amps=amps,
                voltage=voltage,
                power_kw=power_kw,
            )
        )
    return details


def _to_ev_station(poi: dict[str, Any]) -> EvStation | None:
    address_info = poi.get("AddressInfo") or {}
    lat, lon = address_info.get("Latitude"), address_info.get("Longitude")
    if lat is None or lon is None:
        return None

    operator = poi.get("OperatorInfo") or {}
    connections = poi.get("Connections") or []

    counts = {"level1_count": 0, "level2_count": 0, "dc_fast_count": 0}
    connector_codes: list[str] = []
    for connection in connections:
        level_id = (connection.get("Level") or {}).get("ID")
        field = LEVEL_ID_TO_FIELD.get(level_id)
        if field:
            counts[field] += connection.get("Quantity") or 0

        code = _connector_code((connection.get("ConnectionType") or {}).get("Title"))
        if code and code not in connector_codes:
            connector_codes.append(code)

    return EvStation(
        # Prefixed so this can never collide with a directory-source
        # station_id (both sources use small increasing integers as
        # their own native ID).
        station_id=f"community-{poi['UUID']}",
        name=address_info.get("Title") or "",
        network=operator.get("Title"),
        network_web=operator.get("WebsiteURL"),
        address=_build_address(address_info),
        latitude=lat,
        longitude=lon,
        # Recomputed later, relative to the actual searched location, by
        # ev_search.py — this cached record may have been fetched for a
        # nearby (grid-snapped) point, not the real search point.
        distance_miles=None,
        phone=address_info.get("ContactTelephone1"),
        access_hours=address_info.get("AccessComments"),
        access_code="public",  # server-side usagetypeid filter guarantees this
        status_code="E",  # server-side statustypeid filter guarantees this
        level1_count=counts["level1_count"] or None,
        level2_count=counts["level2_count"] or None,
        dc_fast_count=counts["dc_fast_count"] or None,
        connector_types=connector_codes,
        connector_details=_connector_details(connections),
        date_last_confirmed=poi.get("DateLastStatusUpdate"),
        comments=_comments(poi.get("UserComments")),
        photo_urls=_photo_urls(poi.get("MediaItems")),
    )


# Module-level, not per-instance: get_ev_community_service() below hands
# out a fresh EvCommunityService per request (same dependency-injection
# pattern as get_ev_directory_service), so the cache has to live above
# that to actually persist across requests — an instance attribute would
# reset every time and never save a single request against this source.
_cache: dict[tuple[float, float], tuple[float, list[EvStation]]] = {}


class EvCommunityService:
    def __init__(self) -> None:
        self._api_key = get_settings().ocm_api_key

    async def nearby_supplement_stations(
        self, lat: float, lon: float
    ) -> list[EvStation]:
        """EV stations from the community source with a
        confirmed-operational, public status.

        Does not filter by data-source/provider — a station's
        DataProvider tag isn't a reliable signal for whether
        EvDirectoryService will also return it (see the module-level
        comment above). Every result here still needs deduping against
        this search's own directory-source results by proximity, which
        ev_search.py does.
        """
        key = _cache_key(lat, lon)
        cached = _cache.get(key)
        if cached is not None:
            cached_at, stations = cached
            if time.monotonic() - cached_at < CACHE_TTL_SECONDS:
                return stations

        grid_lat, grid_lon = key
        params = {
            "key": self._api_key,
            "latitude": grid_lat,
            "longitude": grid_lon,
            "distance": EV_COMMUNITY_SEARCH_RADIUS_MILES,
            "distanceunit": "Miles",
            "maxresults": EV_COMMUNITY_MAX_RESULTS,
            "statustypeid": STATUS_IDS_OPERATIONAL,
            "usagetypeid": USAGE_IDS_PUBLIC,
            "compact": "false",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(EV_COMMUNITY_URL, params=params)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EvCommunityError(f"EV community-data lookup failed: {exc}") from exc

        pois = response.json()
        supplement = [
            station
            for poi in pois
            if (station := _to_ev_station(poi)) is not None
        ]

        _cache[key] = (time.monotonic(), supplement)
        return supplement


def get_ev_community_service() -> EvCommunityService:
    return EvCommunityService()
