from unittest.mock import patch

from app.config import Settings
from app.services.gasbuddy_client import (
    GasBuddyService,
    _select_brands,
    _to_gas_station,
    get_gasbuddy_service,
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
    # GasBuddy sometimes lists the same brand twice for one station
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
    # Matches a real GasBuddy response for 684 Hespeler Rd, Cambridge, ON —
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


# --- solver_url wiring (FlareSolverr, for Cloudflare-blocked deploys) ------


def test_gasbuddy_service_passes_solver_url_to_the_underlying_client():
    with patch("app.services.gasbuddy_client.GasBuddy") as fake_gasbuddy:
        GasBuddyService(solver_url="http://127.0.0.1:8191/v1")

    fake_gasbuddy.assert_called_once_with(solver_url="http://127.0.0.1:8191/v1")


def test_gasbuddy_service_defaults_to_no_solver_url():
    with patch("app.services.gasbuddy_client.GasBuddy") as fake_gasbuddy:
        GasBuddyService()

    fake_gasbuddy.assert_called_once_with(solver_url=None)


def test_get_gasbuddy_service_reads_solver_url_from_settings():
    settings = Settings(gasbuddy_solver_url="http://127.0.0.1:8191/v1")
    with (
        patch("app.services.gasbuddy_client.get_settings", return_value=settings),
        patch("app.services.gasbuddy_client.GasBuddy") as fake_gasbuddy,
    ):
        get_gasbuddy_service()

    fake_gasbuddy.assert_called_once_with(solver_url="http://127.0.0.1:8191/v1")


def test_get_gasbuddy_service_defaults_to_no_solver_url_when_unset():
    settings = Settings(gasbuddy_solver_url="")
    with (
        patch("app.services.gasbuddy_client.get_settings", return_value=settings),
        patch("app.services.gasbuddy_client.GasBuddy") as fake_gasbuddy,
    ):
        get_gasbuddy_service()

    fake_gasbuddy.assert_called_once_with(solver_url=None)
