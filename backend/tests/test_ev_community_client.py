from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services import ev_community_client
from app.services.ev_community_client import CACHE_TTL_SECONDS, EvCommunityError, EvCommunityService


@pytest.fixture(autouse=True)
def _clear_ev_community_cache():
    # The cache is module-level (see ev_community_client.py's own comment on why),
    # so it has to be reset between tests or one test's fetch would leak
    # into the next as a false cache hit.
    ev_community_client._cache.clear()
    yield
    ev_community_client._cache.clear()


class _FakeCommunityResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _raw_poi(**overrides):
    raw = {
        "UUID": "abc-123",
        "DataProvider": {"Title": "Community Contributors"},
        "OperatorInfo": {
            "Title": "EVgo Network",
            "WebsiteURL": "https://www.evgo.com",
        },
        "AddressInfo": {
            "Title": "Riverwalk Fast Charge",
            "AddressLine1": "35 E Wacker Dr",
            "Town": "Chicago",
            "StateOrProvince": "IL",
            "Latitude": 41.887,
            "Longitude": -87.627,
            "ContactTelephone1": "888-555-1234",
            "AccessComments": "24 hours daily",
        },
        "Connections": [
            {
                "Level": {"ID": 3},
                "ConnectionType": {"Title": "CCS (Type 1)"},
                "Quantity": 4,
                "Amps": 125,
                "Voltage": 400,
                "PowerKW": 50,
            },
            {
                "Level": {"ID": 3},
                "ConnectionType": {"Title": "CHAdeMO"},
                "Quantity": 2,
                "Amps": None,
                "Voltage": None,
                "PowerKW": 62.5,
            },
        ],
        "DateLastStatusUpdate": "2026-08-01T00:00:00Z",
    }
    raw.update(overrides)
    return raw


def _directory_import_poi(**overrides):
    return _raw_poi(
        UUID="def-456",
        DataProvider={"Title": "directory-source.example"},
        **overrides,
    )


@pytest.mark.asyncio
async def test_maps_community_fields_onto_ev_station():
    fake_response = _FakeCommunityResponse([_raw_poi()])
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        stations = await EvCommunityService().nearby_supplement_stations(41.85, -87.65)

    assert len(stations) == 1
    station = stations[0]
    assert station.station_id == "community-abc-123"
    assert station.name == "Riverwalk Fast Charge"
    assert station.network == "EVgo Network"
    assert station.network_web == "https://www.evgo.com"
    assert station.address == "35 E Wacker Dr, Chicago, IL"
    assert station.latitude == 41.887
    assert station.longitude == -87.627
    assert station.phone == "888-555-1234"
    assert station.access_hours == "24 hours daily"
    assert station.access_code == "public"
    assert station.status_code == "E"
    # Two DC-fast connections (Level.ID 3), quantities 4 + 2.
    assert station.dc_fast_count == 6
    assert station.level1_count is None
    assert station.level2_count is None
    assert station.connector_types == ["J1772COMBO", "CHADEMO"]
    assert len(station.connector_details) == 2
    assert station.connector_details[0].connector_type == "J1772COMBO"
    assert station.connector_details[0].quantity == 4
    assert station.connector_details[0].amps == 125
    assert station.connector_details[0].voltage == 400
    assert station.connector_details[0].power_kw == 50
    assert station.connector_details[1].connector_type == "CHADEMO"
    assert station.connector_details[1].amps is None
    assert station.connector_details[1].voltage is None
    assert station.connector_details[1].power_kw == 62.5
    assert station.date_last_confirmed == "2026-08-01T00:00:00Z"
    # distance_miles is deliberately left for ev_search.py to recompute
    # against the real search point, not whatever grid cell this was
    # fetched for.
    assert station.distance_miles is None
    assert station.comments == []
    assert station.photo_urls == []


@pytest.mark.asyncio
async def test_maps_comments_and_drops_blank_ones():
    fake_response = _FakeCommunityResponse(
        [
            _raw_poi(
                UserComments=[
                    {
                        "UserName": "Celso Azevedo",
                        "Comment": "Changed operator, still works fine.",
                        "DateCreated": "2025-06-14T18:44:21.44Z",
                        "CheckinStatusType": {
                            "Title": "Charged Successfully",
                            "IsPositive": True,
                        },
                    },
                    # A check-in with no written note — should be dropped,
                    # not shown as a blank comment.
                    {
                        "UserName": "Anonymous Driver",
                        "Comment": "",
                        "DateCreated": "2025-01-01T00:00:00Z",
                        "CheckinStatusType": {"Title": "Charged Successfully"},
                    },
                ]
            )
        ]
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        stations = await EvCommunityService().nearby_supplement_stations(41.85, -87.65)

    comments = stations[0].comments
    assert len(comments) == 1
    assert comments[0].author == "Celso Azevedo"
    assert comments[0].text == "Changed operator, still works fine."
    assert comments[0].date == "2025-06-14T18:44:21.44Z"
    assert comments[0].checkin_status == "Charged Successfully"
    assert comments[0].checkin_is_positive is True


@pytest.mark.asyncio
async def test_maps_photo_urls_and_drops_disabled_or_video_items():
    fake_response = _FakeCommunityResponse(
        [
            _raw_poi(
                MediaItems=[
                    {
                        "ItemURL": "https://media.example.com/photo1.jpg",
                        "IsEnabled": True,
                        "IsVideo": False,
                    },
                    {
                        "ItemURL": "https://media.example.com/disabled.jpg",
                        "IsEnabled": False,
                        "IsVideo": False,
                    },
                    {
                        "ItemURL": "https://media.example.com/video.mp4",
                        "IsEnabled": True,
                        "IsVideo": True,
                    },
                ]
            )
        ]
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        stations = await EvCommunityService().nearby_supplement_stations(41.85, -87.65)

    assert stations[0].photo_urls == [
        "https://media.example.com/photo1.jpg"
    ]


@pytest.mark.asyncio
async def test_does_not_filter_by_data_provider():
    # A directory-tagged POI isn't necessarily a current duplicate — the
    # community source's copy can go stale after the directory source's
    # own live feed drops a station (confirmed live for a real station:
    # tagged with a stale directory-source provider, no status update
    # since 2019, and genuinely absent from EvDirectoryService's current
    # results). So this is left for ev_search.py's proximity dedup against
    # the search's *actual* directory-source results, not decided here by
    # a source tag.
    fake_response = _FakeCommunityResponse([_raw_poi(), _directory_import_poi()])
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        stations = await EvCommunityService().nearby_supplement_stations(41.85, -87.65)

    assert {s.station_id for s in stations} == {"community-abc-123", "community-def-456"}


@pytest.mark.asyncio
async def test_drops_a_poi_with_no_coordinates():
    fake_response = _FakeCommunityResponse(
        [_raw_poi(AddressInfo={**_raw_poi()["AddressInfo"], "Latitude": None})]
    )
    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        stations = await EvCommunityService().nearby_supplement_stations(41.85, -87.65)

    assert stations == []


@pytest.mark.asyncio
async def test_sends_expected_request_params():
    fake_response = _FakeCommunityResponse([])
    fake_get = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.get", new=fake_get):
        await EvCommunityService().nearby_supplement_stations(41.85, -87.65)

    _, kwargs = fake_get.call_args
    params = kwargs["params"]
    assert params["distanceunit"] == "Miles"
    # 10/20/30/50/75 are this source's own IsOperational=true status codes.
    assert params["statustypeid"] == "10,20,30,50,75"
    # 1=Public, 4=Membership Required, 5=Pay At Location, 7=Notice
    # Required — all genuinely public/usable, unlike Private or Unknown.
    assert params["usagetypeid"] == "1,4,5,7"
    assert params["maxresults"] == 500


@pytest.mark.asyncio
async def test_snaps_the_query_point_to_a_coarse_grid_before_requesting():
    # Two nearby points a fraction of a degree apart should share one grid
    # cell (and therefore one cache entry / one real request) rather than
    # each issuing their own request against this source.
    fake_response = _FakeCommunityResponse([])
    fake_get = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.get", new=fake_get):
        await EvCommunityService().nearby_supplement_stations(41.8501, -87.6499)

    _, kwargs = fake_get.call_args
    params = kwargs["params"]
    assert params["latitude"] == pytest.approx(41.9)
    assert params["longitude"] == pytest.approx(-87.6)


@pytest.mark.asyncio
async def test_reuses_the_cached_result_for_a_nearby_point_without_a_second_request():
    fake_response = _FakeCommunityResponse([_raw_poi()])
    fake_get = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.get", new=fake_get):
        service = EvCommunityService()
        await service.nearby_supplement_stations(41.83, -87.63)
        # A different point, but within the same ~11km grid cell.
        await service.nearby_supplement_stations(41.84, -87.64)

    assert fake_get.call_count == 1


@pytest.mark.asyncio
async def test_refetches_once_the_cache_entry_has_expired():
    fake_response = _FakeCommunityResponse([_raw_poi()])
    fake_get = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.get", new=fake_get), patch(
        "app.services.ev_community_client.time.monotonic",
        # 1st call: cache write for the first fetch. 2nd call: the
        # not-yet-expired check on the second call — made to fail (i.e.
        # look expired) by being far past the TTL. 3rd: cache write for
        # the resulting refetch.
        side_effect=[0.0, CACHE_TTL_SECONDS + 1, CACHE_TTL_SECONDS + 1],
    ):
        service = EvCommunityService()
        await service.nearby_supplement_stations(41.85, -87.65)
        await service.nearby_supplement_stations(41.85, -87.65)

    assert fake_get.call_count == 2


@pytest.mark.asyncio
async def test_a_failed_community_request_raises_community_error():
    fake_get = AsyncMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.AsyncClient.get", new=fake_get):
        with pytest.raises(EvCommunityError):
            await EvCommunityService().nearby_supplement_stations(41.85, -87.65)
