/**
 * @format
 */

import React from 'react';
import {FlatList, TextInput} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import HomeScreen, {
  INITIAL_PERSISTED_SEARCH,
  PersistedSearch,
} from '../src/screens/HomeScreen';
import {FavoritesProvider} from '../src/store/FavoritesContext';

const healthResponse = {
  ok: true,
  json: () => Promise.resolve({status: 'ok', app_name: 'GasAgent.ai API'}),
};

function stationsResponse(names: string[], nextCursor: string | null) {
  return {
    ok: true,
    json: () =>
      Promise.resolve({
        results: names.map((name, index) => ({
          station_id: `${name}-${index}`,
          name,
          brand: name,
          brand_logo_url: null,
          address: null,
          latitude: null,
          longitude: null,
          distance_miles: 1,
          regular: null,
          midgrade: null,
          premium: null,
          diesel: null,
          star_rating: null,
          ratings_count: null,
        })),
        next_cursor: nextCursor,
        lat: 41.85,
        lon: -87.65,
      }),
  };
}

it('loads 10 more stations when the list is scrolled to the end', async () => {
  const responses = [
    healthResponse,
    stationsResponse(['Shell'], '20'),
    stationsResponse(['BP'], null),
  ];
  let call = 0;
  global.fetch = jest.fn(() => {
    const response = responses[Math.min(call, responses.length - 1)];
    call += 1;
    return Promise.resolve(response);
  }) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <HomeScreen
          persistedSearch={INITIAL_PERSISTED_SEARCH}
          onSearchComplete={() => {}}
        />
      </FavoritesProvider>,
    );
  });

  await act(async () => {
    renderer!.root.findByType(TextInput).props.onChangeText('Chicago');
  });
  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Search'}).props.onPress();
  });

  let list = renderer!.root.findByType(FlatList);
  expect(list.props.data.map((s: {name: string}) => s.name)).toEqual(['Shell']);

  await act(async () => {
    list.props.onEndReached();
  });

  list = renderer!.root.findByType(FlatList);
  expect(list.props.data.map((s: {name: string}) => s.name)).toEqual([
    'Shell',
    'BP',
  ]);
});

it('restores the first page from persisted state without refetching, dropping any loaded extra pages', async () => {
  const responses = [
    healthResponse,
    stationsResponse(['Shell'], '20'),
    stationsResponse(['BP'], null),
  ];
  let call = 0;
  global.fetch = jest.fn(() => {
    const response = responses[Math.min(call, responses.length - 1)];
    call += 1;
    return Promise.resolve(response);
  }) as unknown as typeof fetch;

  let persisted: PersistedSearch = INITIAL_PERSISTED_SEARCH;
  const onSearchComplete = (next: PersistedSearch) => {
    persisted = next;
  };

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <HomeScreen
          persistedSearch={persisted}
          onSearchComplete={onSearchComplete}
        />
      </FavoritesProvider>,
    );
  });

  await act(async () => {
    renderer!.root.findByType(TextInput).props.onChangeText('Chicago');
  });
  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Search'}).props.onPress();
  });
  // Simulate the user scrolling to load a second page before leaving the tab.
  await act(async () => {
    renderer!.root.findByType(FlatList).props.onEndReached();
  });
  expect(
    renderer!.root
      .findByType(FlatList)
      .props.data.map((s: {name: string}) => s.name),
  ).toEqual(['Shell', 'BP']);

  // Leaving the Home tab unmounts it (App.tsx renders screens
  // conditionally); coming back mounts a fresh instance seeded from
  // whatever HomeScreen last reported via onSearchComplete.
  await act(async () => {
    renderer!.unmount();
  });

  const fetchCallsBeforeRemount = (global.fetch as jest.Mock).mock.calls.length;

  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <HomeScreen
          persistedSearch={persisted}
          onSearchComplete={onSearchComplete}
        />
      </FavoritesProvider>,
    );
  });

  // Only the health check refetches on mount — no new stations search,
  // since the first page came back purely from props.
  expect((global.fetch as jest.Mock).mock.calls.length).toBe(
    fetchCallsBeforeRemount + 1,
  );

  const list = renderer!.root.findByType(FlatList);
  expect(list.props.data.map((s: {name: string}) => s.name)).toEqual(['Shell']);

  // The search bar itself should also show the persisted query, not just
  // the results list — same "search a location once" experience.
  expect(renderer!.root.findByType(TextInput).props.value).toBe('Chicago');
});
