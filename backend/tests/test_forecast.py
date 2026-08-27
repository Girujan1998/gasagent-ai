import pytest

from app.models.schemas import FuelPrice, GasStation
from app.services import forecast
from app.services.country_lookup import CountryLookupError
from app.services.forecast import ForecastService
from app.services.gas_price_client import StationSearchResult
from app.services.national_trend import NationalTrend


def make_station(
    station_id: str,
    regular_price: float | None,
    formatted_price: str | None = None,
    brand: str | None = None,
) -> GasStation:
    return GasStation(
        station_id=station_id,
        name=f"Station {station_id}",
        brand=brand,
        regular=(
            FuelPrice(price=regular_price, formatted_price=formatted_price)
            if regular_price is not None
            else None
        ),
    )


class FakeGasPriceService:
    """Simulates the gas-price lookup's own pagination — `pages` is a list of station
    lists, one per page, each fetched in order via next_cursor. Pass plain
    `stations` as shorthand for a single page.
    """

    def __init__(
        self,
        stations: list[GasStation] | None = None,
        pages: list[list[GasStation]] | None = None,
    ):
        self._pages = pages if pages is not None else [stations or []]
        self.calls: list[dict] = []

    async def search_nearest_stations(
        self, *, lat=None, lon=None, limit=10, cursor=None, **_
    ):
        self.calls.append({"lat": lat, "lon": lon, "limit": limit, "cursor": cursor})
        page_index = len(self.calls) - 1
        if page_index >= len(self._pages):
            return StationSearchResult(
                stations=[], next_cursor=None, lat=lat, lon=lon
            )
        stations = self._pages[page_index]
        has_more_pages = page_index + 1 < len(self._pages)
        next_cursor = str(page_index + 1) if has_more_pages else None
        return StationSearchResult(
            stations=stations, next_cursor=next_cursor, lat=lat, lon=lon
        )


class FakeCountryLookupService:
    def __init__(self, country_code: str | None = None, error: Exception | None = None):
        self._country_code = country_code
        self._error = error

    async def resolve_country_code(self, lat, lon):
        if self._error:
            raise self._error
        return self._country_code


class FakeCaTrendService:
    def __init__(self, trend: NationalTrend | None = None):
        self._trend = trend

    async def latest_trend(self):
        return self._trend


class FakeUsTrendService:
    def __init__(self, trend: NationalTrend | None = None):
        self._trend = trend

    async def latest_trend(self):
        return self._trend


def make_service(
    stations=None,
    pages=None,
    gas_price=None,
    country_code=None,
    country_error=None,
    ca_trend=None,
    us_trend=None,
) -> ForecastService:
    return ForecastService(
        gas_price=gas_price
        or FakeGasPriceService(stations or [make_station("1", 1.70)], pages=pages),
        country_lookup=FakeCountryLookupService(country_code, country_error),
        ca_trend=FakeCaTrendService(ca_trend),
        us_trend=FakeUsTrendService(us_trend),
    )


@pytest.mark.asyncio
async def test_forecasts_upward_from_a_ca_trend_for_a_canadian_location():
    service = make_service(
        stations=[make_station("1", 1.70), make_station("2", 1.72)],
        country_code="ca",
        ca_trend=NationalTrend(
            latest_value=175.5, previous_value=169.4, latest_period="2026-07-01", period_days=30
        ),
    )

    result = await service.forecast(43.36, -80.31)

    assert result.today_average_price == pytest.approx(1.71)
    assert result.source == "ca"
    assert result.trend_direction == "up"
    assert result.daily_change_pct == pytest.approx((175.5 - 169.4) / 169.4 / 30)
    assert result.forecasted_price == pytest.approx(
        1.71 * (1 + result.daily_change_pct)
    )
    assert result.source_period_end == "2026-07-01"
    assert result.stations_sampled == 2


@pytest.mark.asyncio
async def test_forecasts_downward_from_a_us_trend_for_a_us_location():
    service = make_service(
        stations=[make_station("1", 3.80)],
        country_code="us",
        us_trend=NationalTrend(
            latest_value=3.75, previous_value=3.85, latest_period="2026-08-11", period_days=7
        ),
    )

    result = await service.forecast(41.85, -87.65)

    assert result.source == "us"
    assert result.trend_direction == "down"
    assert result.daily_change_pct < 0
    assert result.forecasted_price < result.today_average_price


@pytest.mark.asyncio
async def test_falls_back_to_flat_with_no_trend_when_country_cannot_be_resolved():
    service = make_service(country_code=None)

    result = await service.forecast(0, 0)

    assert result.source == "none"
    assert result.trend_direction == "flat"
    assert result.daily_change_pct is None
    assert result.forecasted_price == result.today_average_price


@pytest.mark.asyncio
async def test_falls_back_to_flat_for_a_us_location_with_no_us_trend_available():
    # e.g. no trend API key configured — us_trend_client already returns
    # None for this, forecast.py must not treat "us" as a signal on its own.
    service = make_service(country_code="us", us_trend=None)

    result = await service.forecast(41.85, -87.65)

    assert result.source == "none"
    assert result.daily_change_pct is None


@pytest.mark.asyncio
async def test_a_failed_country_lookup_falls_back_to_no_trend_rather_than_raising():
    service = make_service(country_error=CountryLookupError("boom"))

    result = await service.forecast(43.36, -80.31)

    assert result.source == "none"
    assert result.today_average_price is not None


@pytest.mark.asyncio
async def test_returns_none_prices_when_no_station_has_a_regular_price():
    service = make_service(
        stations=[make_station("1", None), make_station("2", None)],
        country_code="ca",
        ca_trend=NationalTrend(
            latest_value=175.5, previous_value=169.4, latest_period="2026-07-01", period_days=30
        ),
    )

    result = await service.forecast(43.36, -80.31)

    assert result.today_average_price is None
    assert result.forecasted_price is None
    assert result.stations_sampled == 0
    # The trend itself was still resolved even though there's no local
    # price to apply it to.
    assert result.source == "ca"


@pytest.mark.asyncio
async def test_treats_a_tiny_change_as_flat_but_still_reports_it():
    service = make_service(
        country_code="ca",
        ca_trend=NationalTrend(
            # 0.01% total change over 30 days is well under the "flat"
            # labeling threshold, but should still be a real (tiny) number,
            # not silently dropped to None.
            latest_value=100.03, previous_value=100.0, latest_period="2026-07-01", period_days=30
        ),
    )

    result = await service.forecast(43.36, -80.31)

    assert result.trend_direction == "flat"
    assert result.daily_change_pct is not None
    assert result.daily_change_pct > 0


@pytest.mark.asyncio
async def test_averages_only_stations_that_reported_a_regular_price():
    service = make_service(
        stations=[
            make_station("1", 1.60),
            make_station("2", None),
            make_station("3", 1.80),
        ],
        country_code=None,
    )

    result = await service.forecast(0, 0)

    assert result.today_average_price == pytest.approx(1.70)
    assert result.stations_sampled == 2


@pytest.mark.asyncio
async def test_formats_the_average_and_forecast_like_a_canadian_stations_own_price():
    service = make_service(
        stations=[make_station("1", 167.7, formatted_price="167.7¢")],
        country_code="ca",
        ca_trend=NationalTrend(
            latest_value=175.5, previous_value=169.4, latest_period="2026-07-01", period_days=30
        ),
    )

    result = await service.forecast(43.36, -80.31)

    assert result.today_average_formatted == "167.7¢"
    assert result.forecasted_price_formatted is not None
    assert result.forecasted_price_formatted.endswith("¢")


@pytest.mark.asyncio
async def test_formats_the_average_and_forecast_like_a_us_stations_own_price():
    service = make_service(
        stations=[make_station("1", 3.19, formatted_price="$3.19")],
        country_code="us",
        us_trend=NationalTrend(
            latest_value=3.75, previous_value=3.85, latest_period="2026-08-11", period_days=7
        ),
    )

    result = await service.forecast(41.85, -87.65)

    assert result.today_average_formatted == "$3.19"
    assert result.forecasted_price_formatted is not None
    assert result.forecasted_price_formatted.startswith("$")


@pytest.mark.asyncio
async def test_leaves_formatted_prices_none_when_no_station_reported_a_regular_price():
    service = make_service(stations=[make_station("1", None)], country_code=None)

    result = await service.forecast(0, 0)

    assert result.today_average_formatted is None
    assert result.forecasted_price_formatted is None


@pytest.mark.asyncio
async def test_identifies_the_cheapest_and_priciest_price_in_the_sample():
    service = make_service(
        stations=[
            make_station("1", 1.70, formatted_price="$1.70"),
            make_station("2", 1.60, formatted_price="$1.60"),
            make_station("3", 1.85, formatted_price="$1.85"),
        ],
        country_code=None,
    )

    result = await service.forecast(0, 0)

    assert result.today_lowest_price == pytest.approx(1.60)
    assert result.today_highest_price == pytest.approx(1.85)
    assert result.today_lowest_formatted == "$1.60"
    assert result.today_highest_formatted == "$1.85"


@pytest.mark.asyncio
async def test_projects_the_range_using_the_same_daily_trend_as_the_average():
    service = make_service(
        stations=[
            make_station("1", 1.60),
            make_station("2", 1.80),
        ],
        country_code="ca",
        ca_trend=NationalTrend(
            latest_value=175.5,
            previous_value=169.4,
            latest_period="2026-07-01",
            period_days=30,
        ),
    )

    result = await service.forecast(43.36, -80.31)

    daily_change_pct = result.daily_change_pct
    assert daily_change_pct is not None
    assert result.forecasted_lowest_price == pytest.approx(
        1.60 * (1 + daily_change_pct)
    )
    assert result.forecasted_highest_price == pytest.approx(
        1.80 * (1 + daily_change_pct)
    )
    # The range shouldn't collapse toward the average — the cheapest
    # station stays cheaper than the priciest one in the forecast too.
    assert result.forecasted_lowest_price < result.forecasted_highest_price


@pytest.mark.asyncio
async def test_the_forecasted_range_equals_todays_range_when_no_trend_is_available():
    service = make_service(
        stations=[
            make_station("1", 1.60),
            make_station("2", 1.80),
        ],
        country_code=None,
    )

    result = await service.forecast(0, 0)

    assert result.daily_change_pct is None
    assert result.forecasted_lowest_price == pytest.approx(1.60)
    assert result.forecasted_highest_price == pytest.approx(1.80)


@pytest.mark.asyncio
async def test_range_fields_are_none_when_no_station_reported_a_price():
    service = make_service(stations=[make_station("1", None)], country_code=None)

    result = await service.forecast(0, 0)

    assert result.today_lowest_price is None
    assert result.today_highest_price is None
    assert result.forecasted_lowest_price is None
    assert result.forecasted_highest_price is None


@pytest.mark.asyncio
async def test_low_and_high_collapse_to_the_same_price_when_only_one_station_reports_one():
    service = make_service(
        stations=[make_station("1", 1.70)], country_code=None
    )

    result = await service.forecast(0, 0)

    assert result.today_lowest_price == result.today_highest_price == pytest.approx(
        1.70
    )


@pytest.mark.asyncio
async def test_computes_the_average_price_change_between_today_and_the_forecast():
    service = make_service(
        stations=[make_station("1", 100.0, formatted_price="100.0¢")],
        country_code="ca",
        ca_trend=NationalTrend(
            latest_value=103.0, previous_value=100.0, latest_period="2026-07-01", period_days=30
        ),
    )

    result = await service.forecast(43.36, -80.31)

    assert result.price_change == pytest.approx(
        result.forecasted_price - result.today_average_price
    )
    assert result.price_change > 0
    assert result.price_change_formatted == "+" + f"{result.price_change:.1f}¢"


@pytest.mark.asyncio
async def test_price_change_is_negative_and_signed_when_the_forecast_is_lower():
    service = make_service(
        stations=[make_station("1", 3.85, formatted_price="$3.85")],
        country_code="us",
        us_trend=NationalTrend(
            latest_value=3.75, previous_value=3.85, latest_period="2026-08-11", period_days=7
        ),
    )

    result = await service.forecast(41.85, -87.65)

    assert result.price_change < 0
    assert result.price_change_formatted is not None
    assert result.price_change_formatted.startswith("-$")


@pytest.mark.asyncio
async def test_price_change_is_none_when_there_is_no_price_to_project_from():
    service = make_service(stations=[make_station("1", None)], country_code=None)

    result = await service.forecast(0, 0)

    assert result.price_change is None
    assert result.price_change_formatted is None


@pytest.mark.asyncio
async def test_computes_signed_changes_for_both_ends_of_the_range():
    service = make_service(
        stations=[make_station("1", 1.60), make_station("2", 1.80)],
        country_code="ca",
        ca_trend=NationalTrend(
            latest_value=175.5, previous_value=169.4, latest_period="2026-07-01", period_days=30
        ),
    )

    result = await service.forecast(43.36, -80.31)

    assert result.lowest_price_change == pytest.approx(
        result.forecasted_lowest_price - result.today_lowest_price
    )
    assert result.highest_price_change == pytest.approx(
        result.forecasted_highest_price - result.today_highest_price
    )
    assert result.lowest_price_change > 0
    assert result.highest_price_change > 0


@pytest.mark.asyncio
async def test_range_changes_are_zero_but_not_none_when_there_is_no_trend():
    service = make_service(
        stations=[make_station("1", 1.60), make_station("2", 1.80)],
        country_code=None,
    )

    result = await service.forecast(0, 0)

    assert result.lowest_price_change == pytest.approx(0)
    assert result.highest_price_change == pytest.approx(0)


@pytest.mark.asyncio
async def test_range_changes_are_none_when_no_station_reported_a_price():
    service = make_service(stations=[make_station("1", None)], country_code=None)

    result = await service.forecast(0, 0)

    assert result.lowest_price_change is None
    assert result.highest_price_change is None
    assert result.lowest_price_change_formatted is None
    assert result.highest_price_change_formatted is None


@pytest.mark.asyncio
async def test_fetches_only_one_page_by_default():
    # Deliberately tuned down to 1 (see forecast.py's own comment on why:
    # the underlying lookup is an unofficial scrape, and every extra page is an
    # extra request against it) — this pins that current behavior so a
    # future change back to widening the sample is a deliberate,
    # visible edit here too, not a silent regression.
    assert forecast.STATIONS_SAMPLE_PAGES == 1

    gas_price = FakeGasPriceService(
        pages=[[make_station("1", 1.70)], [make_station("2", 1.60)]]
    )
    service = make_service(gas_price=gas_price, country_code=None)

    await service.forecast(0, 0)

    assert len(gas_price.calls) == 1


# The tests below exercise _fetch_wide_sample's actual pagination
# mechanism — still real code (kept in case the sample is ever widened
# again) — independent of the number it happens to be tuned to right now.
@pytest.mark.asyncio
async def test_merges_multiple_pages_into_one_wider_sample(monkeypatch):
    monkeypatch.setattr(forecast, "STATIONS_SAMPLE_PAGES", 3)
    # The cheapest and priciest prices each live on a different page —
    # a single-page sample would miss one of them entirely.
    gas_price = FakeGasPriceService(
        pages=[
            [make_station("1", 1.70)],
            [make_station("2", 1.50)],
            [make_station("3", 1.90)],
        ]
    )
    service = make_service(gas_price=gas_price, country_code=None)

    result = await service.forecast(0, 0)

    assert result.stations_sampled == 3
    assert result.today_lowest_price == pytest.approx(1.50)
    assert result.today_highest_price == pytest.approx(1.90)


@pytest.mark.asyncio
async def test_stops_paging_once_a_page_has_no_next_cursor(monkeypatch):
    monkeypatch.setattr(forecast, "STATIONS_SAMPLE_PAGES", 3)
    gas_price = FakeGasPriceService(
        pages=[[make_station("1", 1.70)], [make_station("2", 1.60)]]
    )
    service = make_service(gas_price=gas_price, country_code=None)

    await service.forecast(0, 0)

    # Only 2 pages were ever available — the loop must not call a third
    # time just because it's allowed up to STATIONS_SAMPLE_PAGES.
    assert len(gas_price.calls) == 2


@pytest.mark.asyncio
async def test_caps_the_number_of_pages_fetched_even_if_more_are_available(
    monkeypatch,
):
    monkeypatch.setattr(forecast, "STATIONS_SAMPLE_PAGES", 3)
    gas_price = FakeGasPriceService(
        pages=[
            [make_station(str(i), 1.70)] for i in range(10)
        ]  # far more pages available than should ever be fetched
    )
    service = make_service(gas_price=gas_price, country_code=None)

    await service.forecast(0, 0)

    assert len(gas_price.calls) == 3


@pytest.mark.asyncio
async def test_stops_paging_if_a_page_returns_no_stations_at_all(monkeypatch):
    monkeypatch.setattr(forecast, "STATIONS_SAMPLE_PAGES", 3)
    gas_price = FakeGasPriceService(pages=[[make_station("1", 1.70)], []])
    service = make_service(gas_price=gas_price, country_code=None)

    await service.forecast(0, 0)

    assert len(gas_price.calls) == 2


@pytest.mark.asyncio
async def test_passes_the_same_coordinates_to_every_page_request(monkeypatch):
    monkeypatch.setattr(forecast, "STATIONS_SAMPLE_PAGES", 3)
    gas_price = FakeGasPriceService(
        pages=[[make_station("1", 1.70)], [make_station("2", 1.60)]]
    )
    service = make_service(gas_price=gas_price, country_code=None)

    await service.forecast(43.36, -80.31)

    assert all(
        call["lat"] == 43.36 and call["lon"] == -80.31 for call in gas_price.calls
    )
    # The second call must continue from the first page's cursor, not
    # restart from scratch.
    assert gas_price.calls[0]["cursor"] is None
    assert gas_price.calls[1]["cursor"] is not None
