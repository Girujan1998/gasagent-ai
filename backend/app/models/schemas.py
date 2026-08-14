from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app_name: str


class FuelPrice(BaseModel):
    price: float | None = None
    formatted_price: str | None = None
    last_updated: str | None = None


class GasStation(BaseModel):
    station_id: str
    name: str
    brand: str | None = None
    brand_logo_url: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    distance_miles: float | None = None
    regular: FuelPrice | None = None
    premium: FuelPrice | None = None
    star_rating: float | None = None
    ratings_count: int | None = None


class StationSearchResponse(BaseModel):
    results: list[GasStation]
    next_cursor: str | None = None
    # The coordinates actually searched (after geocoding, if `query` was
    # used). The client sends these back on subsequent pages instead of
    # re-sending `query`, so pagination doesn't depend on re-geocoding.
    lat: float
    lon: float
