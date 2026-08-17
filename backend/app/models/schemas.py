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
    # A second brand on the same station (e.g. an Esso-fuel station
    # operating under a Circle K storefront) — shown as a connected/
    # secondary brand, never as the primary one.
    connected_brand: str | None = None
    connected_brand_logo_url: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    distance_miles: float | None = None
    regular: FuelPrice | None = None
    midgrade: FuelPrice | None = None
    premium: FuelPrice | None = None
    diesel: FuelPrice | None = None
    star_rating: float | None = None
    ratings_count: int | None = None
    amenities: list[str] = []


class LocationSuggestion(BaseModel):
    label: str
    value: str


class LocationAutocompleteResponse(BaseModel):
    results: list[LocationSuggestion]


class StationSearchResponse(BaseModel):
    results: list[GasStation]
    next_cursor: str | None = None
    # The coordinates actually searched (after geocoding, if `query` was
    # used). The client sends these back on subsequent pages instead of
    # re-sending `query`, so pagination doesn't depend on re-geocoding.
    lat: float
    lon: float


class EvStationComment(BaseModel):
    author: str
    text: str
    date: str | None = None
    # OCM's own signal for whether this comment confirms the charger
    # actually worked when the commenter visited — e.g. "Charged
    # Successfully" vs "Failed to Charge (Equipment Not Operational)" —
    # a stronger, more specific signal than the free-text comment alone.
    # Only OCM has this; always None for a comment sourced any other way.
    checkin_status: str | None = None
    # OCM's own True/False/unset flag for whether checkin_status counts as
    # a good or bad report — lets the UI color-code a comment without
    # having to pattern-match checkin_status's own text.
    checkin_is_positive: bool | None = None


class EvConnectorDetail(BaseModel):
    connector_type: str
    quantity: int | None = None
    amps: float | None = None
    voltage: float | None = None
    power_kw: float | None = None


class EvStation(BaseModel):
    station_id: str
    name: str
    network: str | None = None
    network_web: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    distance_miles: float | None = None
    phone: str | None = None
    access_hours: str | None = None
    # "public" or "private".
    access_code: str | None = None
    # AFDC's own codes: "E" (available), "P" (planned), "T" (temporarily
    # unavailable). Only "E" stations are requested, but the field is kept
    # in case that ever changes.
    status_code: str | None = None
    level1_count: int | None = None
    level2_count: int | None = None
    dc_fast_count: int | None = None
    connector_types: list[str] = []
    # Per-connector electrical specs — OCM-only, AFDC has no equivalent
    # fields at all. Kept separate from connector_types (a deduplicated
    # list of codes) since a station can have multiple connectors of the
    # same type with different specs (e.g. two J1772s at different power).
    connector_details: list[EvConnectorDetail] = []
    date_last_confirmed: str | None = None
    # OCM-only — AFDC has no community layer at all. Comments with no
    # actual text (a check-in with no written note) are dropped rather
    # than shown as an empty entry.
    comments: list[EvStationComment] = []
    # OCM-only — user-submitted photos of the station.
    photo_urls: list[str] = []


class EvStationSearchResponse(BaseModel):
    results: list[EvStation]
    # How many stations actually matched, versus how many were returned
    # (bounded by the request's `limit`) — lets the client tell whether
    # "load more" would actually get anything new.
    total_results: int
    # The coordinates actually searched (after geocoding, if `query` was
    # used) — same purpose as StationSearchResponse.lat/lon.
    lat: float
    lon: float
