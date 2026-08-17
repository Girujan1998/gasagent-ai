/**
 * @format
 */

import {it, expect} from '@jest/globals';

import {EvConnectorDetail, EvStation} from '../src/api/client';
import {
  chargerCountSummary,
  formatConnectorSpecs,
  formatConnectorType,
  networkLogoUrl,
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
    connector_details: [],
    date_last_confirmed: null,
    comments: [],
    photo_urls: [],
    ...overrides,
  };
}

function makeConnectorDetail(
  overrides: Partial<EvConnectorDetail>,
): EvConnectorDetail {
  return {
    connector_type: 'J1772',
    quantity: null,
    amps: null,
    voltage: null,
    power_kw: null,
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

it("derives a logo from the network's own site, since AFDC has no logo URL of its own", () => {
  expect(networkLogoUrl('https://www.chargepoint.com')).toBe(
    'https://www.google.com/s2/favicons?sz=64&domain=www.chargepoint.com',
  );
});

it('strips the path off network_web before using it as the favicon domain', () => {
  expect(networkLogoUrl('https://www.evgo.com/find-charger/')).toBe(
    'https://www.google.com/s2/favicons?sz=64&domain=www.evgo.com',
  );
});

it('returns null when the station has no network website at all', () => {
  expect(networkLogoUrl(null)).toBeNull();
});

it('formats a connector spec with power, voltage, and amperage', () => {
  const detail = makeConnectorDetail({power_kw: 50, voltage: 400, amps: 125});
  expect(formatConnectorSpecs(detail)).toBe('50 kW · 400 V · 125 A');
});

it('omits whichever specs are not reported', () => {
  const detail = makeConnectorDetail({power_kw: 3.7});
  expect(formatConnectorSpecs(detail)).toBe('3.7 kW');
});

it('returns null when a connector has no specs at all, as with an AFDC-sourced connector', () => {
  expect(formatConnectorSpecs(makeConnectorDetail({}))).toBeNull();
});
