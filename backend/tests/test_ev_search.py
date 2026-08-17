import pytest

from app.models.schemas import EvConnectorDetail, EvStation, EvStationComment
from app.services.afdc_client import AfdcError
from app.services.ev_search import EvSearchService
from app.services.ocm_client import OcmError


def make_ev_station(station_id: str, lat: float, lon: float, **overrides) -> EvStation:
    defaults = dict(
        station_id=station_id,
        name=f"Station {station_id}",
        network=None,
        network_web=None,
        address=None,
        latitude=lat,
        longitude=lon,
        distance_miles=None,
        phone=None,
        access_hours=None,
        access_code="public",
        status_code="E",
        level1_count=None,
        level2_count=None,
        dc_fast_count=None,
        connector_types=[],
        date_last_confirmed=None,
    )
    defaults.update(overrides)
    return EvStation(**defaults)


class FakeAfdcService:
    def __init__(self, stations, total_results=None, error=None):
        self._stations = stations
        self._total_results = (
            total_results if total_results is not None else len(stations)
        )
        self._error = error

    async def search_nearest_ev_stations(self, **kwargs):
        if self._error:
            raise self._error
        from app.services.afdc_client import EvStationSearchResult

        return EvStationSearchResult(
            stations=self._stations,
            total_results=self._total_results,
            lat=41.85,
            lon=-87.65,
        )


class FakeOcmService:
    def __init__(self, stations=None, error=None):
        self._stations = stations or []
        self._error = error
        self.last_call_args: tuple | None = None

    async def nearby_supplement_stations(self, lat, lon):
        self.last_call_args = (lat, lon)
        if self._error:
            raise self._error
        return self._stations


@pytest.mark.asyncio
async def test_adds_an_ocm_station_that_afdc_does_not_have():
    afdc = FakeAfdcService([make_ev_station("afdc-1", 41.85, -87.65)])
    # Far enough from the AFDC station to not be a duplicate.
    ocm = FakeOcmService([make_ev_station("ocm-1", 41.95, -87.55)])

    result = await EvSearchService(afdc, ocm).search_nearest_ev_stations(
        lat=41.85, lon=-87.65
    )

    assert {s.station_id for s in result.stations} == {"afdc-1", "ocm-1"}
    assert result.total_results == 2


@pytest.mark.asyncio
async def test_drops_an_ocm_station_that_is_essentially_the_same_physical_charger():
    afdc = FakeAfdcService([make_ev_station("afdc-1", 41.85, -87.65)])
    # ~15m away — well within the "same charger" threshold.
    ocm = FakeOcmService([make_ev_station("ocm-1", 41.85005, -87.65005)])

    result = await EvSearchService(afdc, ocm).search_nearest_ev_stations(
        lat=41.85, lon=-87.65
    )

    assert [s.station_id for s in result.stations] == ["afdc-1"]
    assert result.total_results == 1


@pytest.mark.asyncio
async def test_enriches_the_kept_afdc_station_with_a_duplicates_ocm_data_instead_of_discarding_it():
    # AFDC alone has neither of these; OCM's copy (dropped as a duplicate
    # of the AFDC station kept in its place) is where they come from — this
    # is what makes comments/photos show up for the large majority of
    # stations, since most physical chargers exist in both sources.
    afdc = FakeAfdcService([make_ev_station("afdc-1", 41.85, -87.65)])
    ocm = FakeOcmService(
        [
            make_ev_station(
                "ocm-1",
                41.85005,  # ~15m away — a duplicate of afdc-1
                -87.65005,
                comments=[
                    EvStationComment(author="Driver", text="Works great.")
                ],
                photo_urls=["https://example.com/photo.jpg"],
                connector_details=[
                    EvConnectorDetail(
                        connector_type="J1772COMBO", amps=125, voltage=400, power_kw=50
                    )
                ],
            )
        ]
    )

    result = await EvSearchService(afdc, ocm).search_nearest_ev_stations(
        lat=41.85, lon=-87.65
    )

    assert [s.station_id for s in result.stations] == ["afdc-1"]
    station = result.stations[0]
    assert station.comments == [EvStationComment(author="Driver", text="Works great.")]
    assert station.photo_urls == ["https://example.com/photo.jpg"]
    assert station.connector_details == [
        EvConnectorDetail(connector_type="J1772COMBO", amps=125, voltage=400, power_kw=50)
    ]


@pytest.mark.asyncio
async def test_recomputes_the_ocm_stations_distance_from_the_real_search_point():
    afdc = FakeAfdcService([])
    # The OCM station's own (cached, possibly stale) distance_miles is
    # deliberately wrong here — it must be ignored and recalculated.
    ocm = FakeOcmService(
        [make_ev_station("ocm-1", 41.90, -87.60, distance_miles=999)]
    )

    result = await EvSearchService(afdc, ocm).search_nearest_ev_stations(
        lat=41.85, lon=-87.65
    )

    assert result.stations[0].distance_miles is not None
    assert result.stations[0].distance_miles < 10


@pytest.mark.asyncio
async def test_sorts_the_merged_list_by_distance_and_respects_the_limit():
    afdc = FakeAfdcService(
        [
            make_ev_station("far", 42.20, -87.10, distance_miles=25),
            make_ev_station("near", 41.86, -87.64, distance_miles=1),
        ]
    )
    ocm = FakeOcmService(
        [make_ev_station("middle", 41.95, -87.55, distance_miles=999)]
    )

    result = await EvSearchService(afdc, ocm).search_nearest_ev_stations(
        lat=41.85, lon=-87.65, limit=2
    )

    assert [s.station_id for s in result.stations] == ["near", "middle"]


@pytest.mark.asyncio
async def test_passes_the_afdc_resolved_coordinates_to_the_ocm_lookup():
    # AFDC does the geocoding when a text query is given — OCM must reuse
    # those resolved coordinates rather than geocoding a second time.
    afdc = FakeAfdcService([])
    ocm = FakeOcmService([])

    await EvSearchService(afdc, ocm).search_nearest_ev_stations(query="Chicago")

    assert ocm.last_call_args == (41.85, -87.65)


@pytest.mark.asyncio
async def test_a_failed_ocm_lookup_does_not_break_the_search():
    afdc = FakeAfdcService([make_ev_station("afdc-1", 41.85, -87.65)])
    ocm = FakeOcmService(error=OcmError("boom"))

    result = await EvSearchService(afdc, ocm).search_nearest_ev_stations(
        lat=41.85, lon=-87.65
    )

    assert [s.station_id for s in result.stations] == ["afdc-1"]
    assert result.total_results == 1


@pytest.mark.asyncio
async def test_a_failed_afdc_lookup_still_raises():
    afdc = FakeAfdcService([], error=AfdcError("boom"))
    ocm = FakeOcmService([])

    with pytest.raises(AfdcError):
        await EvSearchService(afdc, ocm).search_nearest_ev_stations(
            lat=41.85, lon=-87.65
        )
