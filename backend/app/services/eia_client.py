import time
from datetime import date
from typing import Any

import httpx

from app.config import get_settings
from app.services.national_trend import NationalTrend

EIA_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"

# NUS = the US national average (not a specific state/PADD region) — no
# reverse-geocoded state name to match against a facet, and a national
# trend is a reasonable secondary signal regardless of which US state the
# search landed in. EPMR = "Regular All Formulations" gasoline.
DUOAREA = "NUS"
PRODUCT = "EPMR"

# Confirmed live (without a key, which this app doesn't have one of to
# test with) that this route + param shape is correct: an unauthenticated
# request returns 403 API_KEY_MISSING rather than a 404, meaning the path
# itself is right. The response shape below follows EIA v2's documented
# convention (a response.data array of {period, value, ...} objects) but
# hasn't been exercised against a real key — this fails closed (returns
# None) rather than raising if that assumption is ever wrong.
CACHE_TTL_SECONDS = 3600 * 6  # EIA releases weekly; no need to poll often.


class EiaError(Exception):
    """Raised when the EIA trend lookup fails."""


def _parse_trend(payload: Any) -> NationalTrend | None:
    try:
        points = payload["response"]["data"]
        if len(points) < 2:
            return None
        # Requested sorted descending by period, so index 0 is latest.
        latest, previous = points[0], points[1]
        latest_value = float(latest["value"])
        previous_value = float(previous["value"])
        latest_period = date.fromisoformat(latest["period"])
        previous_period = date.fromisoformat(previous["period"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None

    period_days = (latest_period - previous_period).days
    if period_days <= 0 or previous_value == 0:
        return None

    return NationalTrend(
        latest_value=latest_value,
        previous_value=previous_value,
        latest_period=latest["period"],
        period_days=period_days,
    )


# Module-level for the same reason as statcan_client.py's cache — a single
# national trend value, not keyed by location.
_cache: tuple[float, NationalTrend | None] | None = None


class EiaService:
    def __init__(self) -> None:
        self._api_key = get_settings().eia_api_key

    async def latest_trend(self) -> NationalTrend | None:
        """The most recent week-over-week change in the US national
        average regular gasoline price, or None if no API key is
        configured or the lookup fails.

        No separate check for a missing key — an empty or invalid key
        fails the request the same way (EIA rejects it with 403), which
        the generic error handling in _fetch() already turns into None.
        """
        global _cache
        if _cache is not None:
            cached_at, trend = _cache
            if time.monotonic() - cached_at < CACHE_TTL_SECONDS:
                return trend

        trend = await self._fetch()
        _cache = (time.monotonic(), trend)
        return trend

    async def _fetch(self) -> NationalTrend | None:
        params = {
            "api_key": self._api_key,
            "frequency": "weekly",
            "data[0]": "value",
            "facets[duoarea][]": DUOAREA,
            "facets[product][]": PRODUCT,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": 4,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(EIA_URL, params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        return _parse_trend(payload)


def get_eia_service() -> EiaService:
    return EiaService()
