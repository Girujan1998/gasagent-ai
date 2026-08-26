/**
 * @format
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import Geolocation from '@react-native-community/geolocation';
import React, {useEffect} from 'react';
import {FlatList} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest, beforeEach} from '@jest/globals';

import {GasStation} from '../src/api/client';
import StationCard from '../src/components/StationCard';
import ReorderableFavoritesList from '../src/components/ReorderableFavoritesList';
import FavoritesScreen from '../src/screens/FavoritesScreen';
import {FavoritesProvider} from '../src/store/FavoritesContext';
import {LocationProvider, useSharedLocation} from '../src/store/LocationContext';

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

function stationSearchResponse(results: GasStation[]) {
  return {
    ok: true,
    json: () =>
      Promise.resolve({
        results,
        next_cursor: null,
        lat: 41.9,
        lon: -87.6,
      }),
  };
}

beforeEach(async () => {
  await AsyncStorage.clear();
});

it('adds and removes a station from favorites via the star button', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
      <LocationProvider>
        <StationCard station={station} />
      </LocationProvider>
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

  jest.mocked(Geolocation.getCurrentPosition).mockImplementation(success => {
    success({
      coords: {
        latitude: 41.95,
        longitude: -87.65,
        altitude: null,
        accuracy: 0,
        altitudeAccuracy: null,
        heading: null,
        speed: null,
      },
      timestamp: 0,
    });
  });

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
      <LocationProvider>
        <FavoritesScreen />
      </LocationProvider>
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

it('already shows distances from a location shared in another tab, without needing to share again here', async () => {
  await AsyncStorage.setItem('gasaiagent:favorites', JSON.stringify([station]));

  function SharesLocationFromAnotherTab() {
    const {setSharedGpsLocation} = useSharedLocation();
    useEffect(() => {
      setSharedGpsLocation({lat: 41.95, lon: -87.65});
    }, [setSharedGpsLocation]);
    return null;
  }

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <LocationProvider>
          <SharesLocationFromAnotherTab />
        </LocationProvider>
      </FavoritesProvider>,
    );
  });

  // Mounted in two steps (like the real app's AppContent, whose
  // LocationProvider survives a tab switch while each screen
  // unmounts/remounts fresh) so Favorites' own first mount already sees
  // the shared location.
  await act(async () => {
    renderer!.update(
      <FavoritesProvider>
        <LocationProvider>
          <SharesLocationFromAnotherTab />
          <FavoritesScreen />
        </LocationProvider>
      </FavoritesProvider>,
    );
  });

  const list = renderer!.root.findByType(FlatList);
  expect(typeof list.props.data[0].distance_miles).toBe('number');
  // No reason to ask again — the banner shouldn't even show.
  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Share your location'}),
  ).toThrow();
});

it('hides the Order button when there are fewer than two favorites', async () => {
  await AsyncStorage.setItem('gasaiagent:favorites', JSON.stringify([station]));

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
      <LocationProvider>
        <FavoritesScreen />
      </LocationProvider>
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
      <LocationProvider>
        <FavoritesScreen />
      </LocationProvider>
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
      <LocationProvider>
        <FavoritesScreen />
      </LocationProvider>
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
      <LocationProvider>
        <FavoritesScreen />
      </LocationProvider>
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
      <LocationProvider>
        <FavoritesScreen />
      </LocationProvider>
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
      <LocationProvider>
        <FavoritesScreen />
      </LocationProvider>
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
      <LocationProvider>
        <FavoritesScreen />
      </LocationProvider>
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

it('pulling to refresh re-queries each favorite and updates its price', async () => {
  await AsyncStorage.setItem('gasaiagent:favorites', JSON.stringify([station]));

  const refreshedStation: GasStation = {
    ...station,
    regular: {
      price: 158.9,
      formatted_price: '158.9¢',
      last_updated: '2026-08-18T00:00:00.000Z',
    },
  };
  global.fetch = jest.fn(() =>
    Promise.resolve(stationSearchResponse([refreshedStation])),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
      <LocationProvider>
        <FavoritesScreen />
      </LocationProvider>
      </FavoritesProvider>,
    );
  });

  expect(renderer!.root.findByType(FlatList).props.data[0].regular).toBeNull();

  await act(async () => {
    await renderer!.root
      .findByType(FlatList)
      .props.refreshControl.props.onRefresh();
  });

  const url = (global.fetch as jest.Mock).mock.calls[0][0] as string;
  expect(url).toContain('lat=41.9');
  expect(url).toContain('lon=-87.6');
  expect(
    renderer!.root.findByType(FlatList).props.data[0].regular.formatted_price,
  ).toBe('158.9¢');

  const stored = JSON.parse(
    (await AsyncStorage.getItem('gasaiagent:favorites'))!,
  );
  expect(stored[0].regular.formatted_price).toBe('158.9¢');
});

it('leaves a favorite unchanged when its refresh lookup finds no matching station', async () => {
  await AsyncStorage.setItem('gasaiagent:favorites', JSON.stringify([station]));

  const unrelatedStation = makeStation('xyz', 'Different Station');
  global.fetch = jest.fn(() =>
    Promise.resolve(stationSearchResponse([unrelatedStation])),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
      <LocationProvider>
        <FavoritesScreen />
      </LocationProvider>
      </FavoritesProvider>,
    );
  });

  await act(async () => {
    await renderer!.root
      .findByType(FlatList)
      .props.refreshControl.props.onRefresh();
  });

  expect(renderer!.root.findByType(FlatList).props.data[0].station_id).toBe(
    'abc',
  );
  expect(renderer!.root.findByType(FlatList).props.data[0].regular).toBeNull();
});

it('skips the network entirely when no favorite has saved coordinates', async () => {
  const stationWithoutCoords: GasStation = {
    ...station,
    latitude: null,
    longitude: null,
  };
  await AsyncStorage.setItem(
    'gasaiagent:favorites',
    JSON.stringify([stationWithoutCoords]),
  );
  const fetchMock = jest.fn();
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
      <LocationProvider>
        <FavoritesScreen />
      </LocationProvider>
      </FavoritesProvider>,
    );
  });

  await act(async () => {
    await renderer!.root
      .findByType(FlatList)
      .props.refreshControl.props.onRefresh();
  });

  expect(fetchMock).not.toHaveBeenCalled();
});
