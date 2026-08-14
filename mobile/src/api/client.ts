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
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  distance_miles: number | null;
  regular: FuelPrice | null;
  premium: FuelPrice | null;
  star_rating: number | null;
  ratings_count: number | null;
};

export type StationSearchResponse = {
  results: GasStation[];
  next_cursor: string | null;
  lat: number;
  lon: number;
};

export type StationSearchParams = {query: string} | {lat: number; lon: number};

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
