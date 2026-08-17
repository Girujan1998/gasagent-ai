/**
 * @format
 */

import {it, expect} from '@jest/globals';

import {GasStation} from '../src/api/client';
import {
  brandKey,
  brandOptionsFromStations,
  filterStationsByBrands,
  OTHER_BRAND_KEY,
  OTHER_BRAND_LABEL,
} from '../src/utils/brandFilter';

function makeStation(id: string, brand: string | null): GasStation {
  return {
    station_id: id,
    name: brand ?? id,
    brand,
    brand_logo_url: null,
    connected_brand: null,
    connected_brand_logo_url: null,
    address: null,
    latitude: null,
    longitude: null,
    distance_miles: null,
    regular: null,
    midgrade: null,
    premium: null,
    diesel: null,
    star_rating: null,
    ratings_count: null,
    amenities: [],
  };
}

it('keys a well-known brand by its own name', () => {
  expect(brandKey(makeStation('a', 'Shell'))).toBe('Shell');
});

it('matches a well-known brand case-insensitively', () => {
  expect(brandKey(makeStation('a', 'shell'))).toBe('Shell');
});

it('buckets an unrecognized brand under Other', () => {
  expect(brandKey(makeStation('a', 'Diva Petroleum'))).toBe(OTHER_BRAND_KEY);
});

it('recognizes Canadian Tire as a well-known brand', () => {
  expect(brandKey(makeStation('a', 'Canadian Tire'))).toBe('Canadian Tire');
});

it('treats "Petro Canada" and "Petro-Canada" as the same brand', () => {
  expect(brandKey(makeStation('a', 'Petro-Canada'))).toBe('Petro-Canada');
  expect(brandKey(makeStation('b', 'Petro Canada'))).toBe('Petro-Canada');
});

it('groups Petro Canada and Petro-Canada into a single filter option', () => {
  const options = brandOptionsFromStations([
    makeStation('a', 'Petro-Canada'),
    makeStation('b', 'Petro Canada'),
  ]);

  expect(options.map(o => o.key)).toEqual(['Petro-Canada']);
});

it('buckets a station with no brand under Other', () => {
  expect(brandKey(makeStation('a', null))).toBe(OTHER_BRAND_KEY);
});

it('only offers filter options for brands actually present in the results', () => {
  const options = brandOptionsFromStations([
    makeStation('a', 'Shell'),
    makeStation('b', 'Esso'),
  ]);

  expect(options.map(o => o.key)).toEqual(['Shell', 'Esso']);
});

it('orders well-known brands by the whitelist order, with Other last', () => {
  // Shell appears before Esso in the whitelist ordering used internally,
  // regardless of the order stations were given in.
  const options = brandOptionsFromStations([
    makeStation('a', 'Diva Petroleum'),
    makeStation('b', 'Esso'),
    makeStation('c', 'Shell'),
  ]);

  expect(options.map(o => o.key)).toEqual(['Shell', 'Esso', OTHER_BRAND_KEY]);
  expect(options[options.length - 1].label).toBe(OTHER_BRAND_LABEL);
});

it('deduplicates repeated brands into a single option', () => {
  const options = brandOptionsFromStations([
    makeStation('a', 'Shell'),
    makeStation('b', 'Shell'),
    makeStation('c', 'Diva Petroleum'),
    makeStation('d', 'PetroKing'),
  ]);

  expect(options.map(o => o.key)).toEqual(['Shell', OTHER_BRAND_KEY]);
});

it('returns every station unfiltered when no allowlist is applied (null)', () => {
  const stations = [makeStation('a', 'Shell'), makeStation('b', 'Esso')];

  expect(filterStationsByBrands(stations, null)).toEqual(stations);
});

it('shows only stations whose brand key is in the allowlist', () => {
  const stations = [
    makeStation('a', 'Shell'),
    makeStation('b', 'Esso'),
    makeStation('c', 'Diva Petroleum'),
  ];

  const filtered = filterStationsByBrands(stations, new Set(['Shell']));

  expect(filtered.map(s => s.station_id)).toEqual(['a']);
});

it('shows only small/independent brands when the allowlist is just Other', () => {
  const stations = [
    makeStation('a', 'Shell'),
    makeStation('b', 'Diva Petroleum'),
    makeStation('c', 'PetroKing'),
  ];

  const filtered = filterStationsByBrands(stations, new Set([OTHER_BRAND_KEY]));

  expect(filtered.map(s => s.station_id)).toEqual(['b', 'c']);
});

it('hides everything when the allowlist is empty', () => {
  const stations = [makeStation('a', 'Shell'), makeStation('b', 'Esso')];

  expect(filterStationsByBrands(stations, new Set())).toEqual([]);
});

it('hides a brand discovered later (e.g. via pagination) that was never added to the allowlist', () => {
  // Regression test: this is the exact bug reported — applying a 2-brand
  // filter, then loading more results that include a third brand nobody
  // selected. It must stay hidden, not silently show up because it's
  // "new" and was never explicitly excluded.
  const stations = [
    makeStation('a', 'Shell'),
    makeStation('b', 'Esso'),
    makeStation('c', 'Petro-Canada'), // arrives later via "load more"
  ];

  const filtered = filterStationsByBrands(stations, new Set(['Shell', 'Esso']));

  expect(filtered.map(s => s.station_id)).toEqual(['a', 'b']);
});
