from fastapi import Depends

from app.models.schemas import GasPriceForecast, GasStation
from app.services.country_lookup import (
    CountryLookupError,
    CountryLookupService,
    get_country_lookup_service,
)
from app.services.eia_client import EiaService, get_eia_service
from app.services.gasbuddy_client import (
    GASBUDDY_PAGE_SIZE,
    GasBuddyService,
    format_price_like,
    get_gasbuddy_service,
)
from app.services.national_trend import NationalTrend
from app.services.statcan_client import StatCanService, get_statcan_service

# A day-over-day change smaller than this shows as "flat" rather than up
# or down — otherwise a source's own rounding noise (e.g. a fraction of a
# cent) could flip the label between calls without the price meaningfully
# moving.
FLAT_THRESHOLD_PCT = 0.0005  # 0.05%/day

# _fetch_wide_sample below can follow next_cursor across multiple pages of
# GASBUDDY_PAGE_SIZE (see gasbuddy_client.py), but this is deliberately
# kept at 1: py-gasbuddy is an unofficial scraper of GasBuddy's internal
# API (it already has CloudflareBlocked handling for exactly this reason),
# and every extra page here is an extra request against it — multiplied
# further by the mobile client's own call frequency (see
# NotificationsScreen's persisted-forecast caching). One page is the same
# cost as the rest of the app's GasBuddy usage.
STATIONS_SAMPLE_PAGES = 1


def _format_signed_like(sample: str | None, value: float) -> str | None:
    """Same regional convention as format_price_like, but always shows an
    explicit +/- sign — for a day-over-day change, where the sign is the
    whole point, rather than an absolute price.
    """
    if sample is None:
        return None
    stripped = sample.strip()
    sign = "+" if value >= 0 else "-"
    magnitude = abs(value)
    if stripped.startswith("$"):
        return f"{sign}${magnitude:.2f}"
    if stripped.endswith("¢"):
        return f"{sign}{magnitude:.1f}¢"
    return f"{sign}{magnitude:.2f}"


def _change(
    today: float | None, forecasted: float | None
) -> float | None:
    if today is None or forecasted is None:
        return None
    return forecasted - today


def _project(value: float | None, daily_change_pct: float | None) -> float | None:
    if value is None:
        return None
    if daily_change_pct is None:
        return value
    return value * (1 + daily_change_pct)


class ForecastService:
    """Projects tomorrow's local gas price from today's live GasBuddy
    average, adjusted by a national trend's daily-prorated rate of change.

    The trend is a secondary signal, not the headline number — GasBuddy's
    own live average for the area is always what "today" means here, and
    if no trend source is available the forecast is simply "no change".
    """

    def __init__(
        self,
        gasbuddy: GasBuddyService,
        country_lookup: CountryLookupService,
        statcan: StatCanService,
        eia: EiaService,
    ) -> None:
        self._gasbuddy = gasbuddy
        self._country_lookup = country_lookup
        self._statcan = statcan
        self._eia = eia

    async def forecast(self, lat: float, lon: float) -> GasPriceForecast:
        stations = await self._fetch_wide_sample(lat, lon)
        # (price, formatted_price) for every station that actually reported
        # a regular-grade price — pulled out once so the rest of this
        # method never has to re-check station.regular for None.
        priced = [
            (station.regular.price, station.regular.formatted_price)
            for station in stations
            if station.regular is not None and station.regular.price is not None
        ]
        prices = [price for price, _ in priced]
        today_average = sum(prices) / len(prices) if prices else None
        sample_format = next(
            (formatted for _, formatted in priced if formatted is not None),
            None,
        )

        today_lowest = min(prices) if prices else None
        today_highest = max(prices) if prices else None

        trend, source = await self._resolve_trend(lat, lon)

        daily_change_pct: float | None = None
        trend_direction = "flat"
        source_period_end: str | None = None
        if trend is not None:
            daily_change_pct = (
                (trend.latest_value - trend.previous_value)
                / trend.previous_value
                / trend.period_days
            )
            source_period_end = trend.latest_period
            if daily_change_pct > FLAT_THRESHOLD_PCT:
                trend_direction = "up"
            elif daily_change_pct < -FLAT_THRESHOLD_PCT:
                trend_direction = "down"

        # Each end of the range is projected with the same daily rate as
        # the average — a station that's the cheapest/priciest today stays
        # at that same relative position in the forecast, rather than the
        # whole range collapsing toward the average.
        forecasted_price = _project(today_average, daily_change_pct)
        forecasted_lowest = _project(today_lowest, daily_change_pct)
        forecasted_highest = _project(today_highest, daily_change_pct)

        price_change = _change(today_average, forecasted_price)
        lowest_change = _change(today_lowest, forecasted_lowest)
        highest_change = _change(today_highest, forecasted_highest)

        return GasPriceForecast(
            lat=lat,
            lon=lon,
            today_average_price=today_average,
            forecasted_price=forecasted_price,
            today_average_formatted=(
                format_price_like(sample_format, today_average)
                if today_average is not None
                else None
            ),
            forecasted_price_formatted=(
                format_price_like(sample_format, forecasted_price)
                if forecasted_price is not None
                else None
            ),
            price_change=price_change,
            price_change_formatted=(
                _format_signed_like(sample_format, price_change)
                if price_change is not None
                else None
            ),
            trend_direction=trend_direction,
            daily_change_pct=daily_change_pct,
            source=source,
            source_period_end=source_period_end,
            stations_sampled=len(prices),
            today_lowest_price=today_lowest,
            today_highest_price=today_highest,
            today_lowest_formatted=(
                format_price_like(sample_format, today_lowest)
                if today_lowest is not None
                else None
            ),
            today_highest_formatted=(
                format_price_like(sample_format, today_highest)
                if today_highest is not None
                else None
            ),
            forecasted_lowest_price=forecasted_lowest,
            forecasted_highest_price=forecasted_highest,
            forecasted_lowest_formatted=(
                format_price_like(sample_format, forecasted_lowest)
                if forecasted_lowest is not None
                else None
            ),
            forecasted_highest_formatted=(
                format_price_like(sample_format, forecasted_highest)
                if forecasted_highest is not None
                else None
            ),
            lowest_price_change=lowest_change,
            lowest_price_change_formatted=(
                _format_signed_like(sample_format, lowest_change)
                if lowest_change is not None
                else None
            ),
            highest_price_change=highest_change,
            highest_price_change_formatted=(
                _format_signed_like(sample_format, highest_change)
                if highest_change is not None
                else None
            ),
        )

    async def _fetch_wide_sample(self, lat: float, lon: float) -> list[GasStation]:
        """Fetches up to STATIONS_SAMPLE_PAGES pages of nearby stations
        and merges them into one list — currently just 1 page (see that
        constant's own comment on why), so this is equivalent to a single
        fetch today, but keeps the option to widen the sample again
        without restructuring the call site if that's ever worth the
        added GasBuddy load.

        Stops early if a page comes back empty or without a next_cursor —
        there's nothing further out to add.
        """
        stations: list[GasStation] = []
        cursor: str | None = None
        for _ in range(STATIONS_SAMPLE_PAGES):
            result = await self._gasbuddy.search_nearest_stations(
                lat=lat, lon=lon, limit=GASBUDDY_PAGE_SIZE, cursor=cursor
            )
            if not result.stations:
                break
            stations.extend(result.stations)
            cursor = result.next_cursor
            if cursor is None:
                break
        return stations

    # Statistics Canada is free and keyless, so any Canadian location gets
    # a real trend; EIA requires a key (see eia_client.py) — a US location
    # without one configured falls back to "none" the same as an
    # unresolvable country would.
    async def _resolve_trend(
        self, lat: float, lon: float
    ) -> tuple[NationalTrend | None, str]:
        try:
            country_code = await self._country_lookup.resolve_country_code(lat, lon)
        except CountryLookupError:
            country_code = None

        if country_code == "ca":
            trend = await self._statcan.latest_trend()
            return (trend, "statcan") if trend is not None else (None, "none")
        if country_code == "us":
            trend = await self._eia.latest_trend()
            return (trend, "eia") if trend is not None else (None, "none")
        return None, "none"


def get_forecast_service(
    gasbuddy: GasBuddyService = Depends(get_gasbuddy_service),
    country_lookup: CountryLookupService = Depends(get_country_lookup_service),
    statcan: StatCanService = Depends(get_statcan_service),
    eia: EiaService = Depends(get_eia_service),
) -> ForecastService:
    return ForecastService(gasbuddy, country_lookup, statcan, eia)
