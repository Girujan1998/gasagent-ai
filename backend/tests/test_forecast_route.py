from fastapi.testclient import TestClient
from py_gasbuddy import CloudflareBlocked

from app.api.routes.forecast import get_forecast_service
from app.main import app
from app.models.schemas import GasPriceForecast

client = TestClient(app)


class FakeForecastService:
    def __init__(self, forecast: GasPriceForecast | None = None, error: Exception | None = None):
        self._forecast = forecast or GasPriceForecast(
            lat=43.36,
            lon=-80.31,
            today_average_price=1.71,
            forecasted_price=1.72,
            trend_direction="up",
            daily_change_pct=0.001,
            source="ca",
            source_period_end="2026-07-01",
            stations_sampled=5,
        )
        self._error = error
        self.last_call_args: tuple | None = None

    async def forecast(self, lat, lon):
        self.last_call_args = (lat, lon)
        if self._error:
            raise self._error
        return self._forecast


def test_requires_lat_and_lon():
    response = client.get("/api/v1/forecast")
    assert response.status_code == 422


def test_returns_the_forecast():
    fake_service = FakeForecastService()
    app.dependency_overrides[get_forecast_service] = lambda: fake_service
    try:
        response = client.get(
            "/api/v1/forecast", params={"lat": 43.36, "lon": -80.31}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["today_average_price"] == 1.71
    assert body["forecasted_price"] == 1.72
    assert body["trend_direction"] == "up"
    assert body["source"] == "ca"
    assert fake_service.last_call_args == (43.36, -80.31)


def test_translates_a_blocked_gas_lookup_into_a_502():
    app.dependency_overrides[get_forecast_service] = lambda: FakeForecastService(
        error=CloudflareBlocked("blocked")
    )
    try:
        response = client.get(
            "/api/v1/forecast", params={"lat": 43.36, "lon": -80.31}
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
