/**
 * @format
 */

import {it, expect} from '@jest/globals';

import {EvStation} from '../src/api/client';
import {
  CHARGER_LEVEL_OPTIONS,
  connectorOptionsFromStations,
  filterStationsByChargerLevels,
  filterStationsByConnectors,
  filterStationsByNetworks,
  networkOptionsFromStations,
  UNKNOWN_CONNECTOR_KEY,
  UNKNOWN_CONNECTOR_LABEL,
  UNKNOWN_NETWORK_KEY,
  UNKNOWN_NETWORK_LABEL,
} from '../src/utils/evFilters';

function makeStation(
  id: string,
  overrides: Partial<EvStation> = {},
): EvStation {
  return {
    station_id: id,
    name: id,
    network: null,
    network_web: null,
    address: null,
    latitude: null,
    longitude: null,
    distance_miles: null,
    phone: null,
    access_hours: null,
    access_code: null,
    status_code: null,
    level1_count: null,
    level2_count: null,
    dc_fast_count: null,
    connector_types: [],
    connector_details: [],
    date_last_confirmed: null,
    comments: [],
    photo_urls: [],
    ...overrides,
  };
}

it('only offers network filter options for networks actually present in the results', () => {
  const options = networkOptionsFromStations([
    makeStation('a', {network: 'ChargePoint'}),
    makeStation('b', {network: 'EVgo'}),
  ]);

  expect(options.map(o => o.key)).toEqual(['ChargePoint', 'EVgo']);
});

it('sorts network options alphabetically', () => {
  const options = networkOptionsFromStations([
    makeStation('a', {network: 'EVgo'}),
    makeStation('b', {network: 'ChargePoint'}),
  ]);

  expect(options.map(o => o.key)).toEqual(['ChargePoint', 'EVgo']);
});

it('deduplicates repeated networks into a single option', () => {
  const options = networkOptionsFromStations([
    makeStation('a', {network: 'ChargePoint'}),
    makeStation('b', {network: 'ChargePoint'}),
  ]);

  expect(options.map(o => o.key)).toEqual(['ChargePoint']);
});

it('buckets a station with no network under Unknown Network, sorted last', () => {
  const options = networkOptionsFromStations([
    makeStation('a', {network: 'EVgo'}),
    makeStation('b', {network: null}),
  ]);

  expect(options.map(o => o.key)).toEqual(['EVgo', UNKNOWN_NETWORK_KEY]);
  expect(options[options.length - 1].label).toBe(UNKNOWN_NETWORK_LABEL);
});

it('returns every station unfiltered when no network allowlist is applied (null)', () => {
  const stations = [
    makeStation('a', {network: 'ChargePoint'}),
    makeStation('b', {network: 'EVgo'}),
  ];

  expect(filterStationsByNetworks(stations, null)).toEqual(stations);
});

it('shows only stations whose network is in the allowlist', () => {
  const stations = [
    makeStation('a', {network: 'ChargePoint'}),
    makeStation('b', {network: 'EVgo'}),
  ];

  const filtered = filterStationsByNetworks(stations, new Set(['ChargePoint']));

  expect(filtered.map(s => s.station_id)).toEqual(['a']);
});

it('shows only networkless stations when the allowlist is just Unknown Network', () => {
  const stations = [
    makeStation('a', {network: 'ChargePoint'}),
    makeStation('b', {network: null}),
  ];

  const filtered = filterStationsByNetworks(
    stations,
    new Set([UNKNOWN_NETWORK_KEY]),
  );

  expect(filtered.map(s => s.station_id)).toEqual(['b']);
});

it('hides every station when the network allowlist is empty', () => {
  const stations = [makeStation('a', {network: 'ChargePoint'})];

  expect(filterStationsByNetworks(stations, new Set())).toEqual([]);
});

it('only offers connector filter options for types actually present in the results', () => {
  const options = connectorOptionsFromStations([
    makeStation('a', {connector_types: ['J1772']}),
    makeStation('b', {connector_types: ['J1772COMBO']}),
  ]);

  expect(options.map(o => o.key)).toEqual(['J1772COMBO', 'J1772']);
  expect(options.map(o => o.label)).toEqual(['CCS', 'J1772']);
});

it('buckets a station with no reported connector types under Unknown, sorted last', () => {
  const options = connectorOptionsFromStations([
    makeStation('a', {connector_types: ['J1772']}),
    makeStation('b', {connector_types: []}),
  ]);

  expect(options.map(o => o.key)).toEqual(['J1772', UNKNOWN_CONNECTOR_KEY]);
  expect(options[options.length - 1].label).toBe(UNKNOWN_CONNECTOR_LABEL);
});

it('returns every station unfiltered when no connector allowlist is applied (null)', () => {
  const stations = [makeStation('a', {connector_types: ['J1772']})];

  expect(filterStationsByConnectors(stations, null)).toEqual(stations);
});

it('matches a station offering multiple connector types if any is in the allowlist', () => {
  const stations = [
    makeStation('a', {connector_types: ['J1772', 'CHADEMO']}),
    makeStation('b', {connector_types: ['J1772COMBO']}),
  ];

  const filtered = filterStationsByConnectors(stations, new Set(['CHADEMO']));

  expect(filtered.map(s => s.station_id)).toEqual(['a']);
});

it('shows only stations with no reported connectors when the allowlist is just Unknown', () => {
  const stations = [
    makeStation('a', {connector_types: ['J1772']}),
    makeStation('b', {connector_types: []}),
  ];

  const filtered = filterStationsByConnectors(
    stations,
    new Set([UNKNOWN_CONNECTOR_KEY]),
  );

  expect(filtered.map(s => s.station_id)).toEqual(['b']);
});

it('offers a fixed set of charger level options regardless of what is nearby', () => {
  expect(CHARGER_LEVEL_OPTIONS.map(o => o.key)).toEqual([
    'level1',
    'level2',
    'dc_fast',
  ]);
});

it('returns every station unfiltered when no charger level allowlist is applied (null)', () => {
  const stations = [makeStation('a', {dc_fast_count: 2})];

  expect(filterStationsByChargerLevels(stations, null)).toEqual(stations);
});

it('matches a station offering multiple charger levels if any is in the allowlist', () => {
  const stations = [
    makeStation('a', {level2_count: 2, dc_fast_count: 1}),
    makeStation('b', {level1_count: 1}),
  ];

  const filtered = filterStationsByChargerLevels(
    stations,
    new Set(['dc_fast']),
  );

  expect(filtered.map(s => s.station_id)).toEqual(['a']);
});

it('treats a zero count the same as no charger of that level at all', () => {
  const stations = [makeStation('a', {level2_count: 0})];

  const filtered = filterStationsByChargerLevels(stations, new Set(['level2']));

  expect(filtered).toEqual([]);
});

it('hides every station when the charger level allowlist is empty', () => {
  const stations = [makeStation('a', {dc_fast_count: 2})];

  expect(filterStationsByChargerLevels(stations, new Set())).toEqual([]);
});
