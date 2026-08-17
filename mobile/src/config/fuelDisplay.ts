import {FuelPrice, GasStation} from '../api/client';

export type FuelKey = 'regular' | 'midgrade' | 'premium' | 'diesel';

export const FUEL_KEYS: FuelKey[] = [
  'regular',
  'midgrade',
  'premium',
  'diesel',
];

export const FUEL_LABELS: Record<FuelKey, string> = {
  regular: 'Regular',
  midgrade: 'Midgrade',
  premium: 'Premium',
  diesel: 'Diesel',
};

// Single-letter form used where space is tight (e.g. map pins).
export const FUEL_INITIALS: Record<FuelKey, string> = {
  regular: 'R',
  midgrade: 'M',
  premium: 'P',
  diesel: 'D',
};

// What a station card shows before the user opens the filter and changes
// it — Price 1 defaults to Regular, Price 2 to Premium.
export const DEFAULT_PRIMARY_FUEL_KEY: FuelKey = 'regular';
export const DEFAULT_SECONDARY_FUEL_KEY: FuelKey = 'premium';

export function fuelByKey(station: GasStation, key: FuelKey): FuelPrice | null {
  return station[key];
}
