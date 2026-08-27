from dataclasses import dataclass

from fastapi import Depends

from app.models.schemas import EvStation
from app.services.ev_directory_client import EvDirectoryError, EvDirectoryService, get_ev_directory_service
from app.services.geo import haversine_miles
from app.services.ev_community_client import EvCommunityError, EvCommunityService, get_ev_community_service

# Two stations within this distance of each other are treated as the same
# physical charger — the directory and community sources don't share
# IDs, so this is the only way to catch a station reported independently
# to both (as opposed to the community source's own re-imports of the
# directory source, which are already filtered out in
# ev_community_client.py before they ever reach this dedup step).
DUPLICATE_THRESHOLD_MILES = 0.03  # ~50 meters


@dataclass
class EvStationSearchResult:
    stations: list[EvStation]
    total_results: int
    lat: float
    lon: float


def _find_duplicate(candidate: EvStation, existing: list[EvStation]) -> EvStation | None:
    if candidate.latitude is None or candidate.longitude is None:
        return None
    for station in existing:
        if (
            station.latitude is not None
            and station.longitude is not None
            and haversine_miles(
                candidate.latitude, candidate.longitude, station.latitude, station.longitude
            )
            < DUPLICATE_THRESHOLD_MILES
        ):
            return station
    return None


def _enrich_with_community_data(directory_station: EvStation, community_candidate: EvStation) -> None:
    """Folds a community-source duplicate's content into the directory
    station kept in its place, instead of discarding it — the directory
    source has no comments/photos of its own at all, so simply dropping
    the community copy on a proximity match would lose that data for the
    large majority of stations (the ones both sources report), leaving
    comments/photos surfaced only for the rare directory-doesn't-have-
    it-at-all stations.
    """
    directory_station.comments = directory_station.comments + community_candidate.comments
    directory_station.photo_urls = directory_station.photo_urls + community_candidate.photo_urls
    # The directory source never has per-connector Amps/Voltage/PowerKW
    # at all, so this is always pure addition, never a conflict to
    # resolve.
    directory_station.connector_details = (
        directory_station.connector_details + community_candidate.connector_details
    )


class EvSearchService:
    """Merges the EV directory source (primary) with the community source
    (coverage supplement).

    The community source tends to pick up independent/small-network
    stations the directory source's own pipeline hasn't ingested — this
    adds those in, deduped against the directory source by proximity,
    without ever treating the community source as primary (the
    directory source's station specs are generally the more reliable of
    the two).
    """

    def __init__(self, directory: EvDirectoryService, community: EvCommunityService) -> None:
        self._directory = directory
        self._community = community

    async def search_nearest_ev_stations(
        self,
        *,
        query: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        limit: int = 20,
        radius_km: float | None = None,
    ) -> EvStationSearchResult:
        directory_result = await self._directory.search_nearest_ev_stations(
            query=query, lat=lat, lon=lon, limit=limit, radius_km=radius_km
        )

        # A failed community-source lookup (or a missing/invalid key)
        # shouldn't take down a search that the directory source alone
        # already answered — it just means no supplement gets added this
        # time.
        try:
            community_candidates = await self._community.nearby_supplement_stations(
                directory_result.lat, directory_result.lon
            )
        except EvCommunityError:
            community_candidates = []

        supplement = []
        for candidate in community_candidates:
            duplicate = _find_duplicate(candidate, directory_result.stations)
            if duplicate is not None:
                _enrich_with_community_data(duplicate, candidate)
                continue
            # The cached community-source record's distance was relative
            # to whatever grid-snapped point it was originally fetched
            # for, not this search's actual coordinates — recomputed
            # here so "how far away" is always accurate regardless of a
            # cache hit.
            distance = (
                haversine_miles(
                    directory_result.lat, directory_result.lon, candidate.latitude, candidate.longitude
                )
                if candidate.latitude is not None and candidate.longitude is not None
                else None
            )
            supplement.append(candidate.model_copy(update={"distance_miles": distance}))

        merged = directory_result.stations + supplement
        merged.sort(
            key=lambda s: s.distance_miles if s.distance_miles is not None else float("inf")
        )

        return EvStationSearchResult(
            stations=merged[:limit],
            total_results=directory_result.total_results + len(supplement),
            lat=directory_result.lat,
            lon=directory_result.lon,
        )


def get_ev_search_service(
    directory: EvDirectoryService = Depends(get_ev_directory_service),
    community: EvCommunityService = Depends(get_ev_community_service),
) -> EvSearchService:
    return EvSearchService(directory, community)
