import {Platform} from 'react-native';

// Android emulator maps host machine's localhost to 10.0.2.2.
// iOS simulator can reach the host directly via localhost.
// For a physical device, replace this with your machine's LAN IP.
const DEV_HOST = Platform.OS === 'android' ? '10.0.2.2' : 'localhost';

export const API_BASE_URL = `http://${DEV_HOST}:8001/api/v1`;

export type HealthResponse = {
  status: string;
  app_name: string;
};

export type FuelPrice = {
  price: number | null;
  formatted_price: string | null;
  last_updated: string | null;
};

export type GasStation = {
  station_id: string;
  name: string;
  brand: string | null;
  brand_logo_url: string | null;
  connected_brand: string | null;
  connected_brand_logo_url: string | null;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  distance_miles: number | null;
  regular: FuelPrice | null;
  midgrade: FuelPrice | null;
  premium: FuelPrice | null;
  diesel: FuelPrice | null;
  star_rating: number | null;
  ratings_count: number | null;
  amenities: string[];
};

export type StationSearchResponse = {
  results: GasStation[];
  next_cursor: string | null;
  lat: number;
  lon: number;
};

export type LocationSuggestion = {
  label: string;
  value: string;
};

export type LocationAutocompleteResponse = {
  results: LocationSuggestion[];
};

export type StationSearchParams = {query: string} | {lat: number; lon: number};

export type EvStationComment = {
  author: string;
  text: string;
  date: string | null;
  // OCM-only signal for whether this comment confirms the charger actually
  // worked when the commenter visited, e.g. "Charged Successfully" vs
  // "Failed to Charge (Equipment Not Operational)".
  checkin_status: string | null;
  checkin_is_positive: boolean | null;
};

// OCM-only — AFDC has no equivalent per-connector electrical spec data at
// all. A station can have multiple connectors of the same type with
// different specs, so this is a flat list, not keyed by connector type.
export type EvConnectorDetail = {
  connector_type: string;
  quantity: number | null;
  amps: number | null;
  voltage: number | null;
  power_kw: number | null;
};

export type EvStation = {
  station_id: string;
  name: string;
  network: string | null;
  network_web: string | null;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  distance_miles: number | null;
  phone: string | null;
  access_hours: string | null;
  access_code: string | null;
  status_code: string | null;
  level1_count: number | null;
  level2_count: number | null;
  dc_fast_count: number | null;
  connector_types: string[];
  connector_details: EvConnectorDetail[];
  date_last_confirmed: string | null;
  comments: EvStationComment[];
  photo_urls: string[];
};

export type EvStationSearchResponse = {
  results: EvStation[];
  total_results: number;
  lat: number;
  lon: number;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {'Content-Type': 'application/json'},
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body && typeof body === 'object' ? body.detail : null;
    throw new Error(
      detail || `Request to ${path} failed with status ${response.status}`,
    );
  }
  return response.json() as Promise<T>;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

export function getLocationAutocomplete(
  query: string,
): Promise<LocationAutocompleteResponse> {
  return request<LocationAutocompleteResponse>(
    `/locations/autocomplete?query=${encodeURIComponent(query)}`,
  );
}

export function searchNearestStations(
  params: StationSearchParams,
  limit: number = 10,
  cursor?: string | null,
): Promise<StationSearchResponse> {
  // Hermes's URLSearchParams polyfill doesn't implement `.set()`, so the
  // query string is built by hand rather than via URLSearchParams.
  const queryParts = [`limit=${encodeURIComponent(limit)}`];
  if ('query' in params) {
    queryParts.push(`query=${encodeURIComponent(params.query)}`);
  } else {
    queryParts.push(
      `lat=${encodeURIComponent(params.lat)}`,
      `lon=${encodeURIComponent(params.lon)}`,
    );
  }
  if (cursor) {
    queryParts.push(`cursor=${encodeURIComponent(cursor)}`);
  }
  return request<StationSearchResponse>(
    `/stations/search?${queryParts.join('&')}`,
  );
}

// NREL AFDC has no cursor-based pagination — `limit` is the total number of
// nearest stations to return in one call, already sorted by distance, so
// "load more" means re-requesting with a bigger limit and replacing the
// results, not appending a new page.
export function searchNearestEvStations(
  params: StationSearchParams,
  limit: number = 20,
  radiusKm?: number,
): Promise<EvStationSearchResponse> {
  const queryParts = [`limit=${encodeURIComponent(limit)}`];
  if ('query' in params) {
    queryParts.push(`query=${encodeURIComponent(params.query)}`);
  } else {
    queryParts.push(
      `lat=${encodeURIComponent(params.lat)}`,
      `lon=${encodeURIComponent(params.lon)}`,
    );
  }
  if (radiusKm != null) {
    queryParts.push(`radius_km=${encodeURIComponent(radiusKm)}`);
  }
  return request<EvStationSearchResponse>(
    `/ev-stations/search?${queryParts.join('&')}`,
  );
}
