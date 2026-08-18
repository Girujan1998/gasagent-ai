import time
from datetime import date
from typing import Any

import httpx

from app.services.national_trend import NationalTrend

STATCAN_URL = (
    "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
)

# Statistics Canada table 18-10-0001-01 ("Monthly average retail prices for
# gasoline and fuel oil, by geography"), the Canada-wide "Regular unleaded
# gasoline at self service filling stations" series — confirmed live via
# getSeriesInfoFromCubePidCoord for productId 18100001, coordinate
# "20.2.0.0.0.0.0.0.0.0". Free and keyless, unlike EIA.
GASOLINE_VECTOR_ID = 1352087861

# StatCan releases this monthly, a few weeks after month-end — no reason to
# poll more often than that.
CACHE_TTL_SECONDS = 3600 * 12


class StatCanError(Exception):
    """Raised when the Statistics Canada trend lookup fails."""


def _parse_trend(payload: Any) -> NationalTrend | None:
    try:
        points = payload[0]["object"]["vectorDataPoint"]
        if len(points) < 2:
            return None
        previous, latest = points[-2], points[-1]
        latest_value = float(latest["value"])
        previous_value = float(previous["value"])
        latest_period = date.fromisoformat(latest["refPer"])
        previous_period = date.fromisoformat(previous["refPer"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None

    period_days = (latest_period - previous_period).days
    if period_days <= 0 or previous_value == 0:
        return None

    return NationalTrend(
        latest_value=latest_value,
        previous_value=previous_value,
        latest_period=latest["refPer"],
        period_days=period_days,
    )


# Module-level, not per-instance — same reasoning as ocm_client.py's cache:
# get_statcan_service() hands out a fresh instance per request. There's
# only one series here (a national trend, not per-location), so this is a
# single cached value rather than a dict keyed by coordinates.
_cache: tuple[float, NationalTrend | None] | None = None


class StatCanService:
    async def latest_trend(self) -> NationalTrend | None:
        """The most recent month-over-month change in Canada's average
        self-serve regular gasoline price, or None if the lookup fails."""
        global _cache
        if _cache is not None:
            cached_at, trend = _cache
            if time.monotonic() - cached_at < CACHE_TTL_SECONDS:
                return trend

        trend = await self._fetch()
        _cache = (time.monotonic(), trend)
        return trend

    async def _fetch(self) -> NationalTrend | None:
        body = [{"vectorId": GASOLINE_VECTOR_ID, "latestN": 2}]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(STATCAN_URL, json=body)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        return _parse_trend(payload)


def get_statcan_service() -> StatCanService:
    return StatCanService()
