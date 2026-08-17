from unittest.mock import AsyncMock, patch

import pytest

from app.services.geocoding import (
    _extract_ca_fsa,
    _looks_like_ca_postal_code,
    autocomplete_locations,
)


class _FakeGeocodingResponse:
    """Stands in for httpx.Response — just enough of its interface for
    _autocomplete_city, without making a real network call."""

    def __init__(self, results):
        self._results = results

    def raise_for_status(self):
        pass

    def json(self):
        return {"results": self._results}


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


def test_extract_ca_fsa_accepts_a_bare_fsa():
    # A search shouldn't require the full 6 characters — the lookup only
    # ever used the first 3 anyway.
    assert _extract_ca_fsa("M5V") == "M5V"


def test_extract_ca_fsa_bare_fsa_is_case_insensitive():
    assert _extract_ca_fsa("m5v") == "M5V"


def test_extract_ca_fsa_rejects_a_partial_fsa():
    assert _extract_ca_fsa("M5") is None


def test_looks_like_ca_postal_code_from_a_bare_fsa():
    assert _looks_like_ca_postal_code("M5V") is True


def test_looks_like_ca_postal_code_from_a_full_code_in_progress():
    assert _looks_like_ca_postal_code("M5V 3") is True


def test_looks_like_ca_postal_code_rejects_a_city_name():
    assert _looks_like_ca_postal_code("Cambridge") is False


def test_looks_like_ca_postal_code_rejects_fewer_than_3_characters():
    assert _looks_like_ca_postal_code("M5") is False


@pytest.mark.asyncio
async def test_autocomplete_locations_short_circuits_under_three_characters():
    # Below the 3-character threshold, no network call should happen at
    # all — this returns synchronously regardless of network availability.
    assert await autocomplete_locations("ab") == []


@pytest.mark.asyncio
async def test_autocomplete_locations_short_circuits_on_whitespace_only():
    assert await autocomplete_locations("   ") == []


@pytest.mark.asyncio
async def test_autocomplete_city_only_returns_us_and_canada_matches():
    # "Paris" is dominated by its French namesake (by far the largest by
    # population) — this is exactly the case the US/CA filter exists for.
    fake_results = [
        {
            "name": "Paris",
            "country_code": "FR",
            "country": "France",
            "admin1": "Île-de-France Region",
            "population": 2138551,
        },
        {
            "name": "Paris",
            "country_code": "US",
            "country": "United States",
            "admin1": "Texas",
            "population": 24782,
        },
        {
            "name": "Paris",
            "country_code": "CA",
            "country": "Canada",
            "admin1": "Ontario",
            "population": 12310,
        },
    ]

    with patch(
        "httpx.AsyncClient.get",
        new=AsyncMock(return_value=_FakeGeocodingResponse(fake_results)),
    ):
        results = await autocomplete_locations("Paris")

    labels = [r.label for r in results]
    assert "Paris, Texas, United States" in labels
    assert "Paris, Ontario, Canada" in labels
    assert not any("France" in label for label in labels)


@pytest.mark.asyncio
async def test_autocomplete_city_returns_nothing_when_no_us_or_canada_matches():
    fake_results = [
        {
            "name": "London",
            "country_code": "GB",
            "country": "United Kingdom",
            "admin1": "England",
            "population": 8961989,
        },
    ]

    with patch(
        "httpx.AsyncClient.get",
        new=AsyncMock(return_value=_FakeGeocodingResponse(fake_results)),
    ):
        results = await autocomplete_locations("London")

    assert results == []
