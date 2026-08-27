import pytest

from app.models.schemas import EvConnectorDetail, EvStation, EvStationComment
from app.services.ev_directory_client import EvDirectoryError
from app.services.ev_search import EvSearchService
from app.services.ev_community_client import EvCommunityError


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


class FakeEvDirectoryService:
    def __init__(self, stations, total_results=None, error=None):
        self._stations = stations
        self._total_results = (
            total_results if total_results is not None else len(stations)
        )
        self._error = error

    async def search_nearest_ev_stations(self, **kwargs):
        if self._error:
            raise self._error
        from app.services.ev_directory_client import EvStationSearchResult

        return EvStationSearchResult(
            stations=self._stations,
            total_results=self._total_results,
            lat=41.85,
            lon=-87.65,
        )


class FakeEvCommunityService:
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
async def test_adds_a_community_station_that_the_directory_does_not_have():
    directory = FakeEvDirectoryService([make_ev_station("directory-1", 41.85, -87.65)])
    # Far enough from the directory station to not be a duplicate.
    community = FakeEvCommunityService([make_ev_station("community-1", 41.95, -87.55)])

    result = await EvSearchService(directory, community).search_nearest_ev_stations(
        lat=41.85, lon=-87.65
    )

    assert {s.station_id for s in result.stations} == {"directory-1", "community-1"}
    assert result.total_results == 2


@pytest.mark.asyncio
async def test_drops_a_community_station_that_is_essentially_the_same_physical_charger():
    directory = FakeEvDirectoryService([make_ev_station("directory-1", 41.85, -87.65)])
    # ~15m away — well within the "same charger" threshold.
    community = FakeEvCommunityService([make_ev_station("community-1", 41.85005, -87.65005)])

    result = await EvSearchService(directory, community).search_nearest_ev_stations(
        lat=41.85, lon=-87.65
    )

    assert [s.station_id for s in result.stations] == ["directory-1"]
    assert result.total_results == 1


@pytest.mark.asyncio
async def test_enriches_the_kept_directory_station_with_a_duplicates_community_data_instead_of_discarding_it():
    # The directory source alone has neither of these; the community
    # source's copy (dropped as a duplicate of the directory station kept
    # in its place) is where they come from — this is what makes
    # comments/photos show up for the large majority of stations, since
    # most physical chargers exist in both sources.
    directory = FakeEvDirectoryService([make_ev_station("directory-1", 41.85, -87.65)])
    community = FakeEvCommunityService(
        [
            make_ev_station(
                "community-1",
                41.85005,  # ~15m away — a duplicate of directory-1
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

    result = await EvSearchService(directory, community).search_nearest_ev_stations(
        lat=41.85, lon=-87.65
    )

    assert [s.station_id for s in result.stations] == ["directory-1"]
    station = result.stations[0]
    assert station.comments == [EvStationComment(author="Driver", text="Works great.")]
    assert station.photo_urls == ["https://example.com/photo.jpg"]
    assert station.connector_details == [
        EvConnectorDetail(connector_type="J1772COMBO", amps=125, voltage=400, power_kw=50)
    ]


@pytest.mark.asyncio
async def test_recomputes_the_community_stations_distance_from_the_real_search_point():
    directory = FakeEvDirectoryService([])
    # The community station's own (cached, possibly stale) distance_miles
    # is deliberately wrong here — it must be ignored and recalculated.
    community = FakeEvCommunityService(
        [make_ev_station("community-1", 41.90, -87.60, distance_miles=999)]
    )

    result = await EvSearchService(directory, community).search_nearest_ev_stations(
        lat=41.85, lon=-87.65
    )

    assert result.stations[0].distance_miles is not None
    assert result.stations[0].distance_miles < 10


@pytest.mark.asyncio
async def test_sorts_the_merged_list_by_distance_and_respects_the_limit():
    directory = FakeEvDirectoryService(
        [
            make_ev_station("far", 42.20, -87.10, distance_miles=25),
            make_ev_station("near", 41.86, -87.64, distance_miles=1),
        ]
    )
    community = FakeEvCommunityService(
        [make_ev_station("middle", 41.95, -87.55, distance_miles=999)]
    )

    result = await EvSearchService(directory, community).search_nearest_ev_stations(
        lat=41.85, lon=-87.65, limit=2
    )

    assert [s.station_id for s in result.stations] == ["near", "middle"]


@pytest.mark.asyncio
async def test_passes_the_directorys_resolved_coordinates_to_the_community_lookup():
    # The directory source does the geocoding when a text query is
    # given — the community source must reuse those resolved coordinates
    # rather than geocoding a second time.
    directory = FakeEvDirectoryService([])
    community = FakeEvCommunityService([])

    await EvSearchService(directory, community).search_nearest_ev_stations(query="Chicago")

    assert community.last_call_args == (41.85, -87.65)


@pytest.mark.asyncio
async def test_a_failed_community_lookup_does_not_break_the_search():
    directory = FakeEvDirectoryService([make_ev_station("directory-1", 41.85, -87.65)])
    community = FakeEvCommunityService(error=EvCommunityError("boom"))

    result = await EvSearchService(directory, community).search_nearest_ev_stations(
        lat=41.85, lon=-87.65
    )

    assert [s.station_id for s in result.stations] == ["directory-1"]
    assert result.total_results == 1


@pytest.mark.asyncio
async def test_a_failed_directory_lookup_still_raises():
    directory = FakeEvDirectoryService([], error=EvDirectoryError("boom"))
    community = FakeEvCommunityService([])

    with pytest.raises(EvDirectoryError):
        await EvSearchService(directory, community).search_nearest_ev_stations(
            lat=41.85, lon=-87.65
        )
