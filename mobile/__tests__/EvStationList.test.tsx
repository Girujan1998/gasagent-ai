/**
 * @format
 */

import React from 'react';
import {ActivityIndicator, FlatList, Linking, Modal, Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import {EvStation} from '../src/api/client';
import EvStationList from '../src/components/EvStationList';

const station: EvStation = {
  station_id: 'abc',
  name: 'Downtown Charging Hub',
  network: 'ChargePoint Network',
  network_web: 'https://www.chargepoint.com',
  address: '1 Main St, Springfield, IL',
  latitude: 41.9,
  longitude: -87.6,
  distance_miles: 1.5,
  phone: '888-758-4389',
  access_hours: '24 hours daily',
  access_code: 'public',
  status_code: 'E',
  level1_count: null,
  level2_count: 2,
  dc_fast_count: 1,
  connector_types: ['J1772', 'J1772COMBO'],
  date_last_confirmed: '2026-08-16T00:00:00.000Z',
};

it('opens a detail modal on tap, and closes it via the close button', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList stations={[station]} loading={false} error={null} />,
    );
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);

  const joinedTexts = () =>
    renderer!.root.findAllByType(Text).map(node =>
      ([] as unknown[])
        .concat(node.props.children)
        .filter(value => typeof value === 'string')
        .join(''),
    );

  // The card itself (before opening anything) shows distance in
  // kilometers, not miles — 1.5 miles.
  expect(joinedTexts()).toContain('2.4 km');
  expect(joinedTexts()).toContain('ChargePoint Network');

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(true);
  const textNodes = joinedTexts();

  expect(textNodes).toContain('2.4 km away');
  expect(textNodes).toContain('CCS');
  expect(textNodes).toEqual(expect.arrayContaining(['J1772', 'CCS']));

  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Close'}).props.onPress();
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);
});

it('hides the connector chips section for a station with none reported', async () => {
  const stationWithNoConnectors: EvStation = {...station, connector_types: []};

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[stationWithNoConnectors]}
        loading={false}
        error={null}
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });

  expect(
    renderer!.root.findAllByProps({children: 'Connector Types'}),
  ).toHaveLength(0);
});

it('opens the device maps app with the station location when Navigate is pressed', async () => {
  const openURLSpy = jest
    .spyOn(Linking, 'openURL')
    .mockResolvedValue(undefined as never);

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList stations={[station]} loading={false} error={null} />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Navigate to this station'})
      .props.onPress();
  });

  expect(openURLSpy).toHaveBeenCalledTimes(1);
  const url = openURLSpy.mock.calls[0][0];
  expect(url).toContain('41.9');
  expect(url).toContain('-87.6');

  openURLSpy.mockRestore();
});

it('shows a Load More button when canLoadMore is true, and calls onLoadMore when pressed', async () => {
  const onLoadMore = jest.fn();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[station]}
        loading={false}
        error={null}
        canLoadMore
        onLoadMore={onLoadMore}
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Load more stations'})
      .props.onPress();
  });

  expect(onLoadMore).toHaveBeenCalledTimes(1);
});

it('shows a spinner instead of the Load More button while loadingMore is true', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[station]}
        loading={false}
        error={null}
        canLoadMore
        loadingMore
      />,
    );
  });

  expect(
    renderer!.root.findAllByProps({accessibilityLabel: 'Load more stations'}),
  ).toHaveLength(0);
  expect(renderer!.root.findByType(ActivityIndicator)).toBeTruthy();
});

it('hides the Load More button when canLoadMore is false', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[station]}
        loading={false}
        error={null}
        canLoadMore={false}
      />,
    );
  });

  expect(
    renderer!.root.findAllByProps({accessibilityLabel: 'Load more stations'}),
  ).toHaveLength(0);
});

it("wires refreshing and onRefresh into the list's pull-to-refresh control", async () => {
  const onRefresh = jest.fn();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[station]}
        loading={false}
        error={null}
        refreshing
        onRefresh={onRefresh}
      />,
    );
  });

  const refreshControl =
    renderer!.root.findByType(FlatList).props.refreshControl;
  expect(refreshControl.props.refreshing).toBe(true);

  refreshControl.props.onRefresh();
  expect(onRefresh).toHaveBeenCalledTimes(1);
});

it('shows the default empty message when there are no stations', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList stations={[]} loading={false} error={null} />,
    );
  });

  const texts = renderer!.root
    .findAllByType(Text)
    .map(node => node.props.children);
  expect(texts).toContain('No EV chargers found nearby.');
});
