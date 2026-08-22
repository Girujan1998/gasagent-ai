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


class GasPriceForecast(BaseModel):
    lat: float
    lon: float
    # The average of nearby stations' current regular-grade price, live
    # from GasBuddy — None if no nearby station reported one.
    today_average_price: float | None = None
    # today_average_price projected one day forward using a national
    # trend's daily-prorated rate of change. None whenever
    # today_average_price itself is None (nothing to project from).
    forecasted_price: float | None = None
    # GasBuddy formats prices differently by region (e.g. "$3.19" in the
    # US vs "167.7¢" in Canada) and neither raw float alone says which —
    # these mirror whichever convention the sampled stations themselves
    # used, so the client can show a correctly-styled price without
    # guessing at units or currency.
    today_average_formatted: str | None = None
    forecasted_price_formatted: str | None = None
    # forecasted_price - today_average_price, with an explicit +/- sign in
    # the formatted version (unlike the absolute prices above, the sign is
    # the whole point here). None under the same condition as
    # forecasted_price itself.
    price_change: float | None = None
    price_change_formatted: str | None = None
    trend_direction: str = "flat"  # "up" | "down" | "flat"
    # The prorated day-over-day rate implied by the trend source (e.g.
    # 0.0023 = +0.23%/day) — None when no trend source was available, in
    # which case forecasted_price just equals today_average_price.
    daily_change_pct: float | None = None
    # Which national data source the trend came from. "none" means the
    # location's country couldn't be resolved, isn't US/Canada, or (for a
    # US location) no EIA API key is configured — the forecast still shows
    # today's average, just with no projected change applied.
    source: str = "none"  # "statcan" | "eia" | "none"
    # The most recent period the trend source's data covers, e.g. "2026-07-01"
    # for Statistics Canada's monthly series or an EIA week-ending date —
    # None when source is "none".
    source_period_end: str | None = None
    # How many nearby stations contributed to today_average_price — shown
    # for transparency about how reliable the local average is.
    stations_sampled: int = 0

    # The spread across nearby stations, not just their average — each end
    # projected forward using the same daily trend rate applied to that
    # station's own current price, so a station that's unusually cheap or
    # expensive today stays unusually cheap or expensive in the forecast
    # rather than reverting toward the mean. None when today_average_price
    # is None (nothing to project from).
    today_lowest_price: float | None = None
    today_highest_price: float | None = None
    today_lowest_formatted: str | None = None
    today_highest_formatted: str | None = None
    forecasted_lowest_price: float | None = None
    forecasted_highest_price: float | None = None
    forecasted_lowest_formatted: str | None = None
    forecasted_highest_formatted: str | None = None
    # Same day-over-day delta concept as price_change, for each end of the
    # range.
    lowest_price_change: float | None = None
    lowest_price_change_formatted: str | None = None
    highest_price_change: float | None = None
    highest_price_change_formatted: str | None = None


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


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatLocation(BaseModel):
    lat: float
    lon: float


class ChatRequest(BaseModel):
    # The whole conversation so far, oldest first — the client resends it
    # in full on every message since this scaffold's chat agent has no
    # server-side session/memory of its own yet.
    messages: list[ChatMessage]
    # The user's current location, if the mobile client has one (freshly
    # shared GPS, or a fallback from the Gas tab's last search) — lets the
    # chat agent's station-lookup tool answer "near me" questions without
    # the model guessing coordinates. None when the client has neither.
    location: ChatLocation | None = None


class ChatResponse(BaseModel):
    message: ChatMessage
