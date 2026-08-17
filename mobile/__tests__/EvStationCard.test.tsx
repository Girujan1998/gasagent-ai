/**
 * @format
 */

import React from 'react';
import {Image, Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import {EvStation} from '../src/api/client';
import EvStationCard from '../src/components/EvStationCard';

const station: EvStation = {
  station_id: 'a',
  name: 'Downtown Charging Hub',
  network: 'ChargePoint Network',
  network_web: 'https://www.chargepoint.com',
  address: '1 Main St',
  latitude: 41.9,
  longitude: -87.6,
  distance_miles: 1.5,
  phone: null,
  access_hours: null,
  access_code: 'public',
  status_code: 'E',
  level1_count: null,
  level2_count: 2,
  dc_fast_count: null,
  connector_types: ['J1772'],
  connector_details: [],
  date_last_confirmed: null,
  comments: [],
  photo_urls: [],
};

it("shows a logo derived from the network's own site when one is reported", async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<EvStationCard station={station} onPress={() => {}} />);
  });

  const image = renderer!.root.findByType(Image);
  expect(image.props.source.uri).toBe(
    'https://www.google.com/s2/favicons?sz=64&domain=www.chargepoint.com',
  );
});

it('falls back to the bolt icon when the station has no network website', async () => {
  const stationWithNoNetwork: EvStation = {...station, network_web: null};

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationCard station={stationWithNoNetwork} onPress={() => {}} />,
    );
  });

  expect(renderer!.root.findAllByType(Image)).toHaveLength(0);
  const texts = renderer!.root
    .findAllByProps({children: '⚡'})
    .map(node => node.props.children);
  expect(texts).toContain('⚡');
});

it('falls back to the bolt icon when the logo image fails to load', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<EvStationCard station={station} onPress={() => {}} />);
  });

  expect(renderer!.root.findAllByType(Image)).toHaveLength(1);

  await act(async () => {
    renderer!.root.findByType(Image).props.onError();
  });

  expect(renderer!.root.findAllByType(Image)).toHaveLength(0);
  const texts = renderer!.root
    .findAllByProps({children: '⚡'})
    .map(node => node.props.children);
  expect(texts).toContain('⚡');
});

it('opens the detail view when pressed, labeled by the station name', async () => {
  const onPress = jest.fn();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<EvStationCard station={station} onPress={onPress} />);
  });

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });

  expect(onPress).toHaveBeenCalledTimes(1);
});

it('shows per-connector Amps/Voltage/PowerKW specs when reported', async () => {
  const stationWithSpecs: EvStation = {
    ...station,
    connector_details: [
      {
        connector_type: 'J1772COMBO',
        quantity: 4,
        amps: 125,
        voltage: 400,
        power_kw: 50,
      },
      {
        connector_type: 'CHADEMO',
        quantity: 1,
        amps: null,
        voltage: null,
        power_kw: null,
      },
    ],
  };

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationCard station={stationWithSpecs} onPress={() => {}} />,
    );
  });

  const texts = renderer!.root
    .findAllByType(Text)
    .map(node => node.props.children);
  expect(texts).toContain('CCS ×4');
  expect(texts).toContain('50 kW · 400 V · 125 A');
  // CHAdeMO has no reported specs, so its row is omitted entirely.
  expect(texts).not.toContain('CHAdeMO');
});

it('omits the specs section when the station has no connector details', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<EvStationCard station={station} onPress={() => {}} />);
  });

  const joinedText = renderer!.root
    .findAllByType(Text)
    .map(node => node.props.children)
    .flat()
    .filter(value => typeof value === 'string')
    .join(' ');
  expect(joinedText).not.toContain('kW');
});
