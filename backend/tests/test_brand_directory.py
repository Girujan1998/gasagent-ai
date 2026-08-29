from app.services import brand_directory


def _reset():
    brand_directory._KNOWN_BRAND_IDS.clear()
    brand_directory._KNOWN_BRAND_IDS.update({"costco": 38})


def setup_function():
    _reset()


def teardown_function():
    _reset()


def test_costco_is_seeded_by_default():
    assert brand_directory.get_brand_id("Costco") == 38


def test_lookup_is_case_insensitive_and_trims_whitespace():
    assert brand_directory.get_brand_id("  COSTCO  ") == 38


def test_unknown_brand_returns_none():
    assert brand_directory.get_brand_id("Some Unmapped Brand") is None


def test_record_brand_id_learns_a_new_brand():
    brand_directory.record_brand_id("Shell", 5)

    assert brand_directory.get_brand_id("Shell") == 5
    assert brand_directory.get_brand_id("shell") == 5


def test_record_brand_id_coerces_a_string_id():
    # Confirmed live: GasBuddy's own raw brandId field sometimes comes
    # back as a string ("38") rather than an int.
    brand_directory.record_brand_id("Petro-Canada", "12")

    assert brand_directory.get_brand_id("Petro-Canada") == 12


def test_record_brand_id_ignores_an_unparseable_id():
    brand_directory.record_brand_id("Weird Brand", "not-a-number")

    assert brand_directory.get_brand_id("Weird Brand") is None


def test_record_brand_id_ignores_a_missing_id():
    brand_directory.record_brand_id("No Id Brand", None)

    assert brand_directory.get_brand_id("No Id Brand") is None


def test_record_brand_id_ignores_an_empty_name():
    brand_directory.record_brand_id("", 99)

    assert brand_directory.get_brand_id("") is None


def test_record_brand_id_first_seen_wins():
    brand_directory.record_brand_id("Shell", 5)
    brand_directory.record_brand_id("Shell", 999)

    assert brand_directory.get_brand_id("Shell") == 5
