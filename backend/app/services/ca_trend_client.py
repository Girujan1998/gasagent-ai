import time
from datetime import date
from typing import Any

import httpx

from app.services.national_trend import NationalTrend

CA_TREND_URL = (
    "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
)

# Table 18-10-0001-01 ("Monthly average retail prices for gasoline and fuel
# oil, by geography"), the Canada-wide "Regular unleaded gasoline at self
# service filling stations" series — confirmed live via
# getSeriesInfoFromCubePidCoord for productId 18100001, coordinate
# "20.2.0.0.0.0.0.0.0.0". Free and keyless, unlike the US trend source.
GASOLINE_VECTOR_ID = 1352087861

# This source releases the series monthly, a few weeks after month-end —
# no reason to poll more often than that.
CACHE_TTL_SECONDS = 3600 * 12


class CaTrendError(Exception):
    """Raised when the Canadian trend lookup fails."""


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


# Module-level, not per-instance — same reasoning as ev_community_client.py's
# cache: get_ca_trend_service() hands out a fresh instance per request.
# There's only one series here (a national trend, not per-location), so
# this is a single cached value rather than a dict keyed by coordinates.
_cache: tuple[float, NationalTrend | None] | None = None


class CaTrendService:
    async def latest_trend(self) -> NationalTrend | None:
        """The most recent month-over-month change in Canada's average
        self-serve regular gasoline price, or None if the lookup fails."""
        global _cache
        if _cache is not None:
            cached_at, trend = _cache
            if time.monotonic() - cached_at < CACHE_TTL_SECONDS:
                return trend

        trend = await self._fetch()
        # Only a successful fetch is cached — a transient failure (a
        # network blip, the source briefly unavailable) must retry on
        # the very next call rather than silently suppressing every
        # Canadian forecast for the full CACHE_TTL_SECONDS window.
        if trend is not None:
            _cache = (time.monotonic(), trend)
        return trend

    async def _fetch(self) -> NationalTrend | None:
        body = [{"vectorId": GASOLINE_VECTOR_ID, "latestN": 2}]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(CA_TREND_URL, json=body)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # print rather than `logging` — see chat_agent_client.py's own
            # comment on why. This result gets cached for
            # CACHE_TTL_SECONDS (12h) — a transient failure here
            # otherwise silently suppresses every Canadian forecast for
            # that whole window with no visible cause.
            print(f"[ca_trend] request failed: {exc!r}")
            return None

        trend = _parse_trend(payload)
        if trend is None:
            print(f"[ca_trend] got a response but couldn't parse a trend from it: {payload!r}")
        return trend


def get_ca_trend_service() -> CaTrendService:
    return CaTrendService()
