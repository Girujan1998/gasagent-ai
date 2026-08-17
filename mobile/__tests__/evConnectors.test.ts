/**
 * @format
 */

import {it, expect} from '@jest/globals';

import {EvStation} from '../src/api/client';
import {
  chargerCountSummary,
  formatConnectorType,
} from '../src/utils/evConnectors';

function makeStation(overrides: Partial<EvStation>): EvStation {
  return {
    station_id: 'a',
    name: 'Test Station',
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
    date_last_confirmed: null,
    ...overrides,
  };
}

it('maps known AFDC connector codes to driver-recognizable labels', () => {
  expect(formatConnectorType('J1772')).toBe('J1772');
  expect(formatConnectorType('CHADEMO')).toBe('CHAdeMO');
  expect(formatConnectorType('J1772COMBO')).toBe('CCS');
  expect(formatConnectorType('TESLA')).toBe('Tesla');
});

it('passes through an unrecognized connector code as-is', () => {
  expect(formatConnectorType('SOME_NEW_CODE')).toBe('SOME_NEW_CODE');
});

it('summarizes only the charger levels that were actually reported', () => {
  const station = makeStation({level2_count: 4, dc_fast_count: 2});
  expect(chargerCountSummary(station)).toBe('4 Level 2 · 2 DC Fast');
});

it('returns null when no charger counts are reported at all', () => {
  const station = makeStation({});
  expect(chargerCountSummary(station)).toBeNull();
});

it('omits a zero count from the summary rather than showing "0 Level 1"', () => {
  const station = makeStation({level1_count: 0, level2_count: 3});
  expect(chargerCountSummary(station)).toBe('3 Level 2');
});
