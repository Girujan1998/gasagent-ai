/**
 * @format
 */

import {it, expect} from '@jest/globals';

import {GasStation} from '../src/api/client';
import {sortStations} from '../src/utils/sortStations';

function makeStation(
  id: string,
  distanceMiles: number | null,
  regularPrice: number | null,
  premiumPrice: number | null,
): GasStation {
  return {
    station_id: id,
    name: id,
    brand: id,
    brand_logo_url: null,
    connected_brand: null,
    connected_brand_logo_url: null,
    address: null,
    latitude: null,
    longitude: null,
    distance_miles: distanceMiles,
    regular:
      regularPrice == null
        ? null
        : {price: regularPrice, formatted_price: null, last_updated: null},
    midgrade: null,
    premium:
      premiumPrice == null
        ? null
        : {price: premiumPrice, formatted_price: null, last_updated: null},
    diesel: null,
    star_rating: null,
    ratings_count: null,
    amenities: [],
  };
}

it('sorts by distance ascending, with unknown distances last', () => {
  const stations = [
    makeStation('far', 5, 3.0, 3.5),
    makeStation('unknown', null, 3.0, 3.5),
    makeStation('near', 1, 3.0, 3.5),
  ];

  const sorted = sortStations(stations, 'distance', 'regular', 'premium');

  expect(sorted.map(s => s.station_id)).toEqual(['near', 'far', 'unknown']);
});

it('sorts by price #1 (the primary displayed fuel) ascending, with missing prices last', () => {
  const stations = [
    makeStation('expensive', 1, 4.5, 3.5),
    makeStation('no-price', 1, null, 3.5),
    makeStation('cheap', 1, 3.0, 3.5),
  ];

  const sorted = sortStations(stations, 'price1', 'regular', 'premium');

  expect(sorted.map(s => s.station_id)).toEqual([
    'cheap',
    'expensive',
    'no-price',
  ]);
});

it('sorts by price #2 (the secondary displayed fuel) ascending, with missing prices last', () => {
  const stations = [
    makeStation('expensive', 1, 3.0, 4.5),
    makeStation('no-price', 1, 3.0, null),
    makeStation('cheap', 1, 3.0, 3.0),
  ];

  const sorted = sortStations(stations, 'price2', 'regular', 'premium');

  expect(sorted.map(s => s.station_id)).toEqual([
    'cheap',
    'expensive',
    'no-price',
  ]);
});

it('for price #1 and distance, sorts only the closer half by price #1 and leaves the rest in distance order', () => {
  // regular (price #1) and premium (price #2) deliberately diverge here,
  // so this only passes if the closer-half sort actually keys off #1.
  const stations = [
    makeStation('near-expensive', 1, 4.0, 1.0),
    makeStation('near-cheap', 2, 3.0, 2.0),
    makeStation('far-cheapest', 3, 1.0, 4.0),
    makeStation('farther', 4, 2.0, 3.0),
  ];

  const sorted = sortStations(
    stations,
    'price1AndDistance',
    'regular',
    'premium',
  );

  // Closest half (near-expensive, near-cheap) re-ordered by regular
  // price; the farther half stays in distance order even though
  // far-cheapest has the cheapest regular price overall.
  expect(sorted.map(s => s.station_id)).toEqual([
    'near-cheap',
    'near-expensive',
    'far-cheapest',
    'farther',
  ]);
});

it('for price #2 and distance, sorts only the closer half by price #2 and leaves the rest in distance order', () => {
  const stations = [
    makeStation('near-expensive', 1, 4.0, 1.0),
    makeStation('near-cheap', 2, 3.0, 2.0),
    makeStation('far-cheapest', 3, 1.0, 4.0),
    makeStation('farther', 4, 2.0, 3.0),
  ];

  const sorted = sortStations(
    stations,
    'price2AndDistance',
    'regular',
    'premium',
  );

  // Same closer half, but ordered by premium price instead — the
  // opposite order from the price #1 case above, since premium runs in
  // reverse of regular for these two stations.
  expect(sorted.map(s => s.station_id)).toEqual([
    'near-expensive',
    'near-cheap',
    'far-cheapest',
    'farther',
  ]);
});

it('sorts by whichever fuel key is passed in, not a fixed regular/premium pair', () => {
  const stationA: GasStation = {
    station_id: 'a',
    name: 'a',
    brand: 'a',
    brand_logo_url: null,
    connected_brand: null,
    connected_brand_logo_url: null,
    address: null,
    latitude: null,
    longitude: null,
    distance_miles: 1,
    regular: {price: 1.0, formatted_price: null, last_updated: null},
    midgrade: {price: 4.0, formatted_price: null, last_updated: null},
    premium: null,
    diesel: {price: 2.0, formatted_price: null, last_updated: null},
    star_rating: null,
    ratings_count: null,
    amenities: [],
  };
  const stationB: GasStation = {
    ...stationA,
    station_id: 'b',
    name: 'b',
    regular: {price: 4.0, formatted_price: null, last_updated: null},
    midgrade: {price: 1.0, formatted_price: null, last_updated: null},
    diesel: {price: 4.0, formatted_price: null, last_updated: null},
  };

  // By regular (a=1.0 cheaper than b=4.0): a first.
  expect(
    sortStations([stationB, stationA], 'price1', 'regular', 'premium').map(
      s => s.station_id,
    ),
  ).toEqual(['a', 'b']);

  // Same two stations, but Price 1 reassigned to midgrade (b=1.0 cheaper
  // than a=4.0) — the order flips, proving the key is actually used.
  expect(
    sortStations([stationB, stationA], 'price1', 'midgrade', 'premium').map(
      s => s.station_id,
    ),
  ).toEqual(['b', 'a']);
});

it('does not mutate the input array', () => {
  const stations = [makeStation('a', 2, 1, 1), makeStation('b', 1, 1, 1)];
  const original = [...stations];

  sortStations(stations, 'distance', 'regular', 'premium');

  expect(stations).toEqual(original);
});
