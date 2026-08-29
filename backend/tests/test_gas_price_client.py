from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.services import brand_directory
from app.services.gas_price_client import (
    GasPriceService,
    _select_brands,
    _to_gas_station,
    get_gas_price_service,
)


def test_select_brands_picks_the_brand_matching_station_name():
    brands = [
        {"name": "Circle K", "brandingType": "cstore", "imageUrl": "circlek.png"},
        {"name": "Esso", "brandingType": "fuel", "imageUrl": "esso.png"},
    ]

    primary, secondary = _select_brands(brands, "Esso")

    assert primary is not None
    assert primary["name"] == "Esso"
    assert secondary is not None
    assert secondary["name"] == "Circle K"


def test_select_brands_is_case_insensitive():
    brands = [{"name": "esso", "imageUrl": "esso.png"}]

    primary, secondary = _select_brands(brands, "Esso")

    assert primary is not None
    assert primary["name"] == "esso"
    assert secondary is None


def test_select_brands_falls_back_to_first_when_no_name_match():
    brands = [
        {"name": "Shell", "imageUrl": "shell.png"},
        {"name": "Circle K", "imageUrl": "circlek.png"},
    ]

    primary, secondary = _select_brands(brands, "123 Main St")

    assert primary is not None
    assert primary["name"] == "Shell"
    assert secondary is not None
    assert secondary["name"] == "Circle K"


def test_select_brands_handles_no_brands():
    assert _select_brands([], "Anything") == (None, None)


def test_select_brands_ignores_a_duplicate_of_the_primary_brand():
    # The underlying lookup sometimes lists the same brand twice for one station
    # (identical name/logo) rather than a genuine second brand.
    brands = [
        {"name": "Esso", "brandingType": "cstore", "imageUrl": "esso.png"},
        {"name": "Esso", "brandingType": "cstore", "imageUrl": "esso.png"},
    ]

    primary, secondary = _select_brands(brands, "Esso")

    assert primary is not None
    assert primary["name"] == "Esso"
    assert secondary is None


def test_select_brands_is_case_insensitive_when_deduping():
    brands = [{"name": "Esso"}, {"name": "esso"}]

    _, secondary = _select_brands(brands, "Esso")

    assert secondary is None


def test_select_brands_still_finds_a_genuine_secondary_past_a_duplicate():
    brands = [
        {"name": "Esso", "imageUrl": "esso.png"},
        {"name": "Esso", "imageUrl": "esso.png"},
        {"name": "Circle K", "imageUrl": "circlek.png"},
    ]

    primary, secondary = _select_brands(brands, "Esso")

    assert primary is not None
    assert primary["name"] == "Esso"
    assert secondary is not None
    assert secondary["name"] == "Circle K"


def test_to_gas_station_maps_connected_brand():
    raw = {
        "station_id": "11982",
        "name": "Esso",
        "brands": [
            {"name": "Circle K", "brandingType": "cstore", "imageUrl": "circlek.png"},
            {"name": "Esso", "brandingType": "fuel", "imageUrl": "esso.png"},
        ],
    }

    station = _to_gas_station(raw)

    assert station.brand == "Esso"
    assert station.brand_logo_url == "esso.png"
    assert station.connected_brand == "Circle K"
    assert station.connected_brand_logo_url == "circlek.png"


def test_to_gas_station_has_no_connected_brand_when_brands_list_duplicates_primary():
    # Matches a real response for 684 Hespeler Rd, Cambridge, ON —
    # `brands` lists "Esso" twice instead of a genuine second brand.
    raw = {
        "station_id": "11983",
        "name": "Esso",
        "brands": [
            {"name": "Esso", "brandingType": "cstore", "imageUrl": "esso.png"},
            {"name": "Esso", "brandingType": "cstore", "imageUrl": "esso.png"},
        ],
    }

    station = _to_gas_station(raw)

    assert station.brand == "Esso"
    assert station.brand_logo_url == "esso.png"
    assert station.connected_brand is None
    assert station.connected_brand_logo_url is None


def test_to_gas_station_has_no_connected_brand_for_single_brand_station():
    raw = {
        "station_id": "1",
        "name": "Shell",
        "brands": [{"name": "Shell", "imageUrl": "shell.png"}],
    }

    station = _to_gas_station(raw)

    assert station.brand == "Shell"
    assert station.connected_brand is None
    assert station.connected_brand_logo_url is None


def test_to_gas_station_maps_amenity_names():
    raw = {
        "station_id": "11982",
        "name": "Esso",
        "amenities": [
            {"amenityId": 1, "name": "Car Wash", "imageUrl": None},
            {"amenityId": 2, "name": "Restrooms", "imageUrl": None},
        ],
    }

    station = _to_gas_station(raw)

    assert station.amenities == ["Car Wash", "Restrooms"]


def test_to_gas_station_has_no_amenities_when_missing():
    raw = {"station_id": "1", "name": "Shell"}

    station = _to_gas_station(raw)

    assert station.amenities == []


# --- opportunistic brand_id capture (see brand_directory.py) ------


def test_to_gas_station_records_brand_ids_for_primary_and_connected_brands():
    brand_directory._KNOWN_BRAND_IDS.clear()
    try:
        raw = {
            "station_id": "11982",
            "name": "Esso",
            "brands": [
                {"name": "Circle K", "brandId": "7", "imageUrl": "circlek.png"},
                {"name": "Esso", "brandId": 12, "imageUrl": "esso.png"},
            ],
        }

        _to_gas_station(raw)

        assert brand_directory.get_brand_id("Circle K") == 7
        assert brand_directory.get_brand_id("Esso") == 12
    finally:
        brand_directory._KNOWN_BRAND_IDS.clear()
        brand_directory._KNOWN_BRAND_IDS.update({"costco": 38})


# --- solver_url wiring (anti-bot solver, for blocked deploys) ------


def test_gas_price_service_passes_solver_url_to_the_underlying_client():
    with patch("app.services.gas_price_client.GasBuddy") as fake_gas_client:
        GasPriceService(solver_url="http://127.0.0.1:8191/v1")

    fake_gas_client.assert_called_once_with(
        solver_url="http://127.0.0.1:8191/v1", timeout=60000
    )


def test_gas_price_service_defaults_to_no_solver_url():
    with patch("app.services.gas_price_client.GasBuddy") as fake_gas_client:
        GasPriceService()

    fake_gas_client.assert_called_once_with(solver_url=None, timeout=60000)


def test_gas_price_service_passes_timeout_ms_to_the_underlying_client():
    # Confirmed live that a harder/slower anti-bot challenge can need
    # more than the underlying client's own 60s default to solve — this
    # is what lets that be raised without patching the library itself.
    with patch("app.services.gas_price_client.GasBuddy") as fake_gas_client:
        GasPriceService(timeout_ms=120000)

    fake_gas_client.assert_called_once_with(solver_url=None, timeout=120000)


def test_get_gas_price_service_reads_solver_url_from_settings():
    # get_gas_price_service is @lru_cache'd (see its own docstring for why
    # — a real singleton, not just cheap-to-construct) — cleared here so
    # this test observes a fresh construction rather than a cached
    # instance left over from another test.
    get_gas_price_service.cache_clear()
    settings = Settings(gasbuddy_solver_url="http://127.0.0.1:8191/v1")
    with (
        patch("app.services.gas_price_client.get_settings", return_value=settings),
        patch("app.services.gas_price_client.GasBuddy") as fake_gas_client,
    ):
        get_gas_price_service()

    fake_gas_client.assert_called_once_with(
        solver_url="http://127.0.0.1:8191/v1", timeout=120000
    )
    get_gas_price_service.cache_clear()


def test_get_gas_price_service_defaults_to_no_solver_url_when_unset():
    get_gas_price_service.cache_clear()
    settings = Settings(gasbuddy_solver_url="")
    with (
        patch("app.services.gas_price_client.get_settings", return_value=settings),
        patch("app.services.gas_price_client.GasBuddy") as fake_gas_client,
    ):
        get_gas_price_service()

    fake_gas_client.assert_called_once_with(solver_url=None, timeout=120000)
    get_gas_price_service.cache_clear()


def test_get_gas_price_service_reads_timeout_ms_from_settings():
    get_gas_price_service.cache_clear()
    settings = Settings(gasbuddy_timeout_ms=180000)
    try:
        with (
            patch("app.services.gas_price_client.get_settings", return_value=settings),
            patch("app.services.gas_price_client.GasBuddy") as fake_gas_client,
        ):
            get_gas_price_service()

        fake_gas_client.assert_called_once_with(solver_url=None, timeout=180000)
    finally:
        get_gas_price_service.cache_clear()


@pytest.mark.asyncio
async def test_search_nearest_stations_passes_brand_id_to_the_underlying_client():
    service = GasPriceService()
    service._client.price_lookup_service = AsyncMock(
        return_value={"results": [], "next_cursor": None}
    )

    await service.search_nearest_stations(lat=43.36, lon=-80.31, limit=20, brand_id=38)

    service._client.price_lookup_service.assert_awaited_once_with(
        lat=43.36, lon=-80.31, limit=20, cursor=None, brand_id=38
    )


@pytest.mark.asyncio
async def test_search_nearest_stations_defaults_to_no_brand_id():
    service = GasPriceService()
    service._client.price_lookup_service = AsyncMock(
        return_value={"results": [], "next_cursor": None}
    )

    await service.search_nearest_stations(lat=43.36, lon=-80.31, limit=20)

    service._client.price_lookup_service.assert_awaited_once_with(
        lat=43.36, lon=-80.31, limit=20, cursor=None, brand_id=None
    )


def test_get_gas_price_service_returns_the_same_instance_across_calls():
    # The actual point of @lru_cache here — concurrent requests must
    # share one client so its token-refresh lock and cached token
    # actually apply across requests, not just within one.
    get_gas_price_service.cache_clear()
    try:
        assert get_gas_price_service() is get_gas_price_service()
    finally:
        get_gas_price_service.cache_clear()
