/**
 * @format
 */

import React from 'react';
import {Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import {GasStation} from '../src/api/client';
import ReorderableFavoritesList from '../src/components/ReorderableFavoritesList';

function makeStation(id: string, name: string, address: string): GasStation {
  return {
    station_id: id,
    name,
    brand: name,
    brand_logo_url: null,
    connected_brand: null,
    connected_brand_logo_url: null,
    address,
    latitude: 41.9,
    longitude: -87.6,
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

const stationA = makeStation('a', 'Shell', '1 Main St');
const stationB = makeStation('b', 'Esso', '2 Elm St');

it('renders each station with its name, address, and a labeled drag handle', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ReorderableFavoritesList
        stations={[stationA, stationB]}
        onReorder={jest.fn()}
      />,
    );
  });

  const texts = renderer!.root
    .findAllByType(Text)
    .map(node => node.props.children);
  expect(texts).toContain('Shell');
  expect(texts).toContain('1 Main St');
  expect(texts).toContain('Esso');
  expect(texts).toContain('2 Elm St');

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Drag to reorder Shell'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Drag to reorder Esso'}),
  ).toBeTruthy();
});

it('calls onReorder with the fully reordered list once a drag completes', async () => {
  const onReorder = jest.fn<(stations: GasStation[]) => void>();
  const stationC = makeStation('c', 'Petro-Canada', '3 Oak St');

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ReorderableFavoritesList
        stations={[stationA, stationB, stationC]}
        onReorder={onReorder}
      />,
    );
  });

  const lastRow = () => renderer!.root.findByProps({currentIndex: 2});

  await act(async () => {
    lastRow().props.onDragStart('c');
  });
  await act(async () => {
    lastRow().props.onMove(2, 0);
  });
  await act(async () => {
    lastRow().props.onDragEnd();
  });

  expect(onReorder).toHaveBeenCalledTimes(1);
  expect(
    onReorder.mock.calls[0][0].map((s: GasStation) => s.station_id),
  ).toEqual(['c', 'a', 'b']);
});

it('does not call onReorder while a drag is still in progress', async () => {
  const onReorder = jest.fn<(stations: GasStation[]) => void>();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ReorderableFavoritesList
        stations={[stationA, stationB]}
        onReorder={onReorder}
      />,
    );
  });

  const firstRow = () => renderer!.root.findByProps({currentIndex: 0});

  await act(async () => {
    firstRow().props.onDragStart('a');
  });
  await act(async () => {
    firstRow().props.onMove(0, 1);
  });

  expect(onReorder).not.toHaveBeenCalled();
});

it('resyncs to a freshly-passed station list when not mid-drag', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ReorderableFavoritesList
        stations={[stationA, stationB]}
        onReorder={jest.fn()}
      />,
    );
  });

  const stationC = makeStation('c', 'Petro-Canada', '3 Oak St');
  await act(async () => {
    renderer!.update(
      <ReorderableFavoritesList
        stations={[stationA, stationB, stationC]}
        onReorder={jest.fn()}
      />,
    );
  });

  expect(
    renderer!.root.findByProps({
      accessibilityLabel: 'Drag to reorder Petro-Canada',
    }),
  ).toBeTruthy();
});
