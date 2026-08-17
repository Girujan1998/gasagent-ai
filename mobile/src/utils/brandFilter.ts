import {GasStation} from '../api/client';

// Recognized chains get their own filter option; anything else (small
// independents, regional brands not in this list) is grouped under
// "Other" so the filter list doesn't grow unbounded. Extend this list as
// more well-known brands come up in results.
const WELL_KNOWN_BRANDS = [
  'Shell',
  'Esso',
  'Exxon',
  'Mobil',
  'Chevron',
  'BP',
  'Costco',
  'Circle K',
  'Sunoco',
  'Marathon',
  'Valero',
  'Speedway',
  '7-Eleven',
  'Petro-Canada',
  'Canadian Tire',
  'Husky',
  'Ultramar',
  'Pioneer',
];

// Hyphen vs. space is the only variation seen in practice (e.g. GasBuddy
// sometimes returns "Petro Canada" instead of "Petro-Canada") — normalize
// both sides of the comparison so those collapse into one filter option
// instead of two.
function normalizeBrandName(name: string): string {
  return name
    .toLowerCase()
    .replace(/[-\s]+/g, ' ')
    .trim();
}

const WELL_KNOWN_BRANDS_NORMALIZED = WELL_KNOWN_BRANDS.map(normalizeBrandName);

export const OTHER_BRAND_KEY = '__other__';
export const OTHER_BRAND_LABEL = 'Other';

export type BrandOption = {key: string; label: string};

// The well-known chain's canonical name (from the list above, regardless
// of which spelling variant the API returned) if it's a recognized chain,
// otherwise the shared "Other" bucket key.
export function brandKey(station: GasStation): string {
  const name = station.brand || station.name;
  if (!name) {
    return OTHER_BRAND_KEY;
  }
  const index = WELL_KNOWN_BRANDS_NORMALIZED.indexOf(normalizeBrandName(name));
  return index === -1 ? OTHER_BRAND_KEY : WELL_KNOWN_BRANDS[index];
}

// Only the brands actually present in the given stations become filter
// options — no point offering to filter out a brand with nothing nearby.
// Well-known brands are ordered as in the list above; Other sorts last.
export function brandOptionsFromStations(
  stations: GasStation[],
): BrandOption[] {
  const present = new Set(stations.map(brandKey));

  const wellKnown = WELL_KNOWN_BRANDS.filter(brand => present.has(brand)).map(
    brand => ({key: brand, label: brand}),
  );

  const options = [...wellKnown];
  if (present.has(OTHER_BRAND_KEY)) {
    options.push({key: OTHER_BRAND_KEY, label: OTHER_BRAND_LABEL});
  }
  return options;
}

// `selectedKeys` is an allowlist, not a blacklist: null means no filter is
// applied (show everything, including brands not seen yet), and a Set
// means show only those exact brand keys — including for stations
// discovered later via pagination. A blacklist ("hide these") would let a
// brand nobody explicitly asked for sneak back in the moment "load more"
// turns up a station for a brand that didn't exist in the results yet.
export function filterStationsByBrands(
  stations: GasStation[],
  selectedKeys: Set<string> | null,
): GasStation[] {
  if (selectedKeys === null) {
    return stations;
  }
  return stations.filter(station => selectedKeys.has(brandKey(station)));
}
