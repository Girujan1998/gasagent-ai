from dataclasses import dataclass

from fastapi import Depends

from app.models.schemas import EvStation
from app.services.afdc_client import AfdcError, AfdcService, get_afdc_service
from app.services.geo import haversine_miles
from app.services.ocm_client import OcmError, OcmService, get_ocm_service

# Two stations within this distance of each other are treated as the same
# physical charger — AFDC and OCM don't share IDs, so this is the only way
# to catch a station reported independently to both (as opposed to OCM's
# own re-imports of AFDC, which are already filtered out in ocm_client.py
# before they ever reach this dedup step).
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


def _enrich_with_ocm_data(afdc_station: EvStation, ocm_candidate: EvStation) -> None:
    """Folds an OCM duplicate's community content into the AFDC station kept
    in its place, instead of discarding it — AFDC has no comments/photos of
    its own at all, so simply dropping the OCM copy on a proximity match
    would lose that data for the large majority of stations (the ones both
    sources report), leaving comments/photos surfaced only for the rare
    AFDC-doesn't-have-it-at-all stations.
    """
    afdc_station.comments = afdc_station.comments + ocm_candidate.comments
    afdc_station.photo_urls = afdc_station.photo_urls + ocm_candidate.photo_urls
    # AFDC never has per-connector Amps/Voltage/PowerKW at all, so this is
    # always pure addition, never a conflict to resolve.
    afdc_station.connector_details = (
        afdc_station.connector_details + ocm_candidate.connector_details
    )


class EvSearchService:
    """Merges AFDC (primary) with Open Charge Map (coverage supplement).

    OCM tends to pick up independent/small-network stations AFDC's own
    pipeline hasn't ingested — this adds those in, deduped against AFDC by
    proximity, without ever treating OCM as the primary source (AFDC's
    station specs are generally the more reliable of the two).
    """

    def __init__(self, afdc: AfdcService, ocm: OcmService) -> None:
        self._afdc = afdc
        self._ocm = ocm

    async def search_nearest_ev_stations(
        self,
        *,
        query: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        limit: int = 20,
        radius_km: float | None = None,
    ) -> EvStationSearchResult:
        afdc_result = await self._afdc.search_nearest_ev_stations(
            query=query, lat=lat, lon=lon, limit=limit, radius_km=radius_km
        )

        # A failed OCM lookup (or a missing/invalid key) shouldn't take down
        # a search that AFDC alone already answered — it just means no
        # supplement gets added this time.
        try:
            ocm_candidates = await self._ocm.nearby_supplement_stations(
                afdc_result.lat, afdc_result.lon
            )
        except OcmError:
            ocm_candidates = []

        supplement = []
        for candidate in ocm_candidates:
            duplicate = _find_duplicate(candidate, afdc_result.stations)
            if duplicate is not None:
                _enrich_with_ocm_data(duplicate, candidate)
                continue
            # The cached OCM record's distance was relative to whatever
            # grid-snapped point it was originally fetched for, not this
            # search's actual coordinates — recomputed here so "how far
            # away" is always accurate regardless of a cache hit.
            distance = (
                haversine_miles(
                    afdc_result.lat, afdc_result.lon, candidate.latitude, candidate.longitude
                )
                if candidate.latitude is not None and candidate.longitude is not None
                else None
            )
            supplement.append(candidate.model_copy(update={"distance_miles": distance}))

        merged = afdc_result.stations + supplement
        merged.sort(
            key=lambda s: s.distance_miles if s.distance_miles is not None else float("inf")
        )

        return EvStationSearchResult(
            stations=merged[:limit],
            total_results=afdc_result.total_results + len(supplement),
            lat=afdc_result.lat,
            lon=afdc_result.lon,
        )


def get_ev_search_service(
    afdc: AfdcService = Depends(get_afdc_service),
    ocm: OcmService = Depends(get_ocm_service),
) -> EvSearchService:
    return EvSearchService(afdc, ocm)
