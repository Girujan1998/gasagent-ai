/**
 * @format
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import Geolocation from '@react-native-community/geolocation';
import React from 'react';
import {FlatList} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, beforeEach} from '@jest/globals';

import {GasStation} from '../src/api/client';
import StationCard from '../src/components/StationCard';
import ReorderableFavoritesList from '../src/components/ReorderableFavoritesList';
import FavoritesScreen from '../src/screens/FavoritesScreen';
import {FavoritesProvider} from '../src/store/FavoritesContext';

function makeStation(
  id: string,
  name: string,
  brand: string = name,
): GasStation {
  return {
    station_id: id,
    name,
    brand,
    brand_logo_url: null,
    connected_brand: null,
    connected_brand_logo_url: null,
    address: '1 Main St',
    latitude: 41.9,
    longitude: -87.6,
    distance_miles: 1.5,
    regular: null,
    midgrade: null,
    premium: null,
    diesel: null,
    star_rating: null,
    ratings_count: null,
    amenities: [],
  };
}

const station = makeStation('abc', 'Test Station');

beforeEach(async () => {
  await AsyncStorage.clear();
});

it('adds and removes a station from favorites via the star button', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationCard station={station} />
      </FavoritesProvider>,
    );
  });

  const star = () =>
    renderer!.root.findByProps({accessibilityLabel: 'Add to favorites'});
  const unstar = () =>
    renderer!.root.findByProps({
      accessibilityLabel: 'Remove from favorites',
    });

  expect(star).not.toThrow();

  await act(async () => {
    star().props.onPress();
  });
  expect(unstar).not.toThrow();

  await act(async () => {
    unstar().props.onPress();
  });
  expect(star).not.toThrow();
});

it('hides distance until location is shared, then shows it', async () => {
  await AsyncStorage.setItem('gasaiagent:favorites', JSON.stringify([station]));

  (Geolocation.getCurrentPosition as jest.Mock).mockImplementation(
    (
      success: (pos: {coords: {latitude: number; longitude: number}}) => void,
    ) => {
      success({coords: {latitude: 41.95, longitude: -87.65}});
    },
  );

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <FavoritesScreen />
      </FavoritesProvider>,
    );
  });

  let list = renderer!.root.findByType(FlatList);
  expect(list.props.data).toHaveLength(1);
  expect(list.props.data[0].distance_miles).toBeNull();

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Share your location'})
      .props.onPress();
  });

  list = renderer!.root.findByType(FlatList);
  expect(typeof list.props.data[0].distance_miles).toBe('number');
});

it('hides the Order button when there are fewer than two favorites', async () => {
  await AsyncStorage.setItem('gasaiagent:favorites', JSON.stringify([station]));

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <FavoritesScreen />
      </FavoritesProvider>,
    );
  });

  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Order favorites'}),
  ).toThrow();
});

it('switches to the drag-to-reorder list when Order is pressed, and back on Done', async () => {
  const stationB = makeStation('def', 'Other Station');
  await AsyncStorage.setItem(
    'gasaiagent:favorites',
    JSON.stringify([station, stationB]),
  );

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <FavoritesScreen />
      </FavoritesProvider>,
    );
  });

  expect(renderer!.root.findByType(FlatList)).toBeTruthy();
  expect(renderer!.root.findAllByType(ReorderableFavoritesList)).toHaveLength(
    0,
  );

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Order favorites'})
      .props.onPress();
  });

  expect(renderer!.root.findAllByType(FlatList)).toHaveLength(0);
  expect(renderer!.root.findByType(ReorderableFavoritesList)).toBeTruthy();
  // The location banner doesn't make sense while reordering.
  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Share your location'}),
  ).toThrow();

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Done reordering favorites'})
      .props.onPress();
  });

  expect(renderer!.root.findByType(FlatList)).toBeTruthy();
  expect(renderer!.root.findAllByType(ReorderableFavoritesList)).toHaveLength(
    0,
  );
});

it('persists a drag-to-reorder as the new favorites order', async () => {
  const stationB = makeStation('def', 'Other Station');
  const stationC = makeStation('ghi', 'Third Station');
  await AsyncStorage.setItem(
    'gasaiagent:favorites',
    JSON.stringify([station, stationB, stationC]),
  );

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <FavoritesScreen />
      </FavoritesProvider>,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Order favorites'})
      .props.onPress();
  });

  // Drive the same sequence the real PanResponder handlers call —
  // dragging the first row down past the other two.
  const firstRow = renderer!.root.findByProps({currentIndex: 0});
  await act(async () => {
    firstRow.props.onDragStart(station.station_id);
  });
  await act(async () => {
    firstRow.props.onMove(0, 1);
  });
  await act(async () => {
    firstRow.props.onMove(1, 2);
  });
  await act(async () => {
    firstRow.props.onDragEnd();
  });

  const storedRaw = await AsyncStorage.getItem('gasaiagent:favorites');
  const stored = JSON.parse(storedRaw!);
  expect(stored.map((s: GasStation) => s.station_id)).toEqual([
    'def',
    'ghi',
    'abc',
  ]);

  // Done exits reorder mode and List view reflects the new order too.
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Done reordering favorites'})
      .props.onPress();
  });
  const list = renderer!.root.findByType(FlatList);
  expect(list.props.data.map((s: GasStation) => s.station_id)).toEqual([
    'def',
    'ghi',
    'abc',
  ]);
});

it('shows the same filter button as the Gas tab once there are favorites', async () => {
  await AsyncStorage.setItem('gasaiagent:favorites', JSON.stringify([station]));

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <FavoritesScreen />
      </FavoritesProvider>,
    );
  });

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Open filters'}),
  ).toBeTruthy();
});

it('narrows favorites to the applied brand filter, and shows every brand unfiltered by default', async () => {
  const shell = makeStation('shell-1', 'Shell Station', 'Shell');
  const esso = makeStation('esso-1', 'Esso Station', 'Esso');
  await AsyncStorage.setItem(
    'gasaiagent:favorites',
    JSON.stringify([shell, esso]),
  );

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <FavoritesScreen />
      </FavoritesProvider>,
    );
  });

  expect(renderer!.root.findByType(FlatList).props.data).toHaveLength(2);

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Open filters'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Hide Esso'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Apply brand filters'})
      .props.onPress();
  });

  const list = renderer!.root.findByType(FlatList);
  expect(list.props.data.map((s: GasStation) => s.station_id)).toEqual([
    'shell-1',
  ]);
});

it('shows a fallback message when the applied brand filter excludes every favorite', async () => {
  const shell = makeStation('shell-1', 'Shell Station', 'Shell');
  const esso = makeStation('esso-1', 'Esso Station', 'Esso');
  await AsyncStorage.setItem(
    'gasaiagent:favorites',
    JSON.stringify([shell, esso]),
  );

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <FavoritesScreen />
      </FavoritesProvider>,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Open filters'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Deselect all brands'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Apply brand filters'})
      .props.onPress();
  });

  expect(renderer!.root.findAllByType(FlatList)).toHaveLength(0);
  expect(
    renderer!.root.findByProps({
      children: 'No favorites match the selected brand filters.',
    }),
  ).toBeTruthy();
});

it('hides the filter button while reordering', async () => {
  const stationB = makeStation('def', 'Other Station');
  await AsyncStorage.setItem(
    'gasaiagent:favorites',
    JSON.stringify([station, stationB]),
  );

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <FavoritesScreen />
      </FavoritesProvider>,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Order favorites'})
      .props.onPress();
  });

  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Open filters'}),
  ).toThrow();
});
