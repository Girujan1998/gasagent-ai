import {GasStation} from '../api/client';
import {fuelByKey, FuelKey} from '../config/fuelDisplay';

export type SortOption =
  | 'distance'
  | 'price1'
  | 'price2'
  | 'price1AndDistance'
  | 'price2AndDistance';

type Comparator = (a: GasStation, b: GasStation) => number;

function byDistanceAsc(a: GasStation, b: GasStation): number {
  const da = a.distance_miles;
  const db = b.distance_miles;
  if (da == null && db == null) {
    return 0;
  }
  if (da == null) {
    return 1;
  }
  if (db == null) {
    return -1;
  }
  return da - db;
}

function byPriceAsc(
  getPrice: (station: GasStation) => number | null,
): Comparator {
  return (a, b) => {
    const pa = getPrice(a);
    const pb = getPrice(b);
    if (pa == null && pb == null) {
      return 0;
    }
    if (pa == null) {
      return 1;
    }
    if (pb == null) {
      return -1;
    }
    return pa - pb;
  };
}

function priceGetter(fuelKey: FuelKey): (station: GasStation) => number | null {
  return station => fuelByKey(station, fuelKey)?.price ?? null;
}

// Nearest gas stations, cheapest first among those — not the same as
// sorting the whole list by price, which could rank a far-away bargain
// above stations that are actually close by. "Nearest" here is the
// closer half of whatever's currently loaded, so it scales with the
// result set instead of a fixed distance cutoff.
function closestHalfByPrice(
  stations: GasStation[],
  getPrice: (station: GasStation) => number | null,
): GasStation[] {
  const byDistance = [...stations].sort(byDistanceAsc);
  const closestCount = Math.max(1, Math.ceil(byDistance.length / 2));
  const closest = byDistance.slice(0, closestCount).sort(byPriceAsc(getPrice));
  const rest = byDistance.slice(closestCount);
  return [...closest, ...rest];
}

export function sortStations(
  stations: GasStation[],
  sortBy: SortOption,
  primaryFuelKey: FuelKey,
  secondaryFuelKey: FuelKey,
): GasStation[] {
  const price1 = priceGetter(primaryFuelKey);
  const price2 = priceGetter(secondaryFuelKey);

  switch (sortBy) {
    case 'distance':
      return [...stations].sort(byDistanceAsc);
    case 'price1':
      return [...stations].sort(byPriceAsc(price1));
    case 'price2':
      return [...stations].sort(byPriceAsc(price2));
    case 'price1AndDistance':
      return closestHalfByPrice(stations, price1);
    case 'price2AndDistance':
      return closestHalfByPrice(stations, price2);
    default:
      return stations;
  }
}
