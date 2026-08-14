from app.services.geocoding import _extract_ca_fsa


def test_extract_ca_fsa_with_space():
    assert _extract_ca_fsa("M5V 3L9") == "M5V"


def test_extract_ca_fsa_without_space():
    assert _extract_ca_fsa("M5V3L9") == "M5V"


def test_extract_ca_fsa_lowercase():
    assert _extract_ca_fsa("m5v 3l9") == "M5V"


def test_extract_ca_fsa_rejects_us_zip():
    assert _extract_ca_fsa("60614") is None


def test_extract_ca_fsa_rejects_city_name():
    assert _extract_ca_fsa("Chicago") is None


def test_extract_ca_fsa_rejects_invalid_letter():
    # D, F, I, O, Q, U are never valid in a Canadian postal code.
    assert _extract_ca_fsa("D5V 3L9") is None
