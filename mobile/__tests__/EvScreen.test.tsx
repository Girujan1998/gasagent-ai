/**
 * @format
 */

import React from 'react';
import {ActivityIndicator, FlatList, TextInput} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';
import WebView from 'react-native-webview';

import EvStationMap from '../src/components/EvStationMap';
import EvScreen, {
  INITIAL_PERSISTED_EV_SEARCH,
  PersistedEvSearch,
} from '../src/screens/EvScreen';

function evStationsResponse(names: string[], totalResults: number) {
  return {
    ok: true,
    json: () =>
      Promise.resolve({
        results: names.map((name, index) => ({
          station_id: `${name}-${index}`,
          name,
          network: name,
          network_web: null,
          address: null,
          latitude: 41.8 + index * 0.001,
          longitude: -87.6 + index * 0.001,
          distance_miles: 1,
          phone: null,
          access_hours: null,
          access_code: null,
          status_code: 'E',
          level1_count: null,
          level2_count: null,
          dc_fast_count: null,
          connector_types: [],
          date_last_confirmed: null,
        })),
        total_results: totalResults,
        lat: 41.85,
        lon: -87.65,
      }),
  };
}

// Unlike mockFetchSequence, this actually honors the `limit` query param —
// needed for the load-more cap test below, where the assertion depends on
// the server returning as many stations as requested (up to what's
// actually available), the same way the real AFDC endpoint does.
function mockLimitAwareFetch(totalAvailable: number) {
  global.fetch = jest.fn((url: unknown) => {
    const urlStr = url as string;
    const limitMatch = urlStr.match(/limit=(\d+)/);
    const limit = limitMatch ? parseInt(limitMatch[1], 10) : 20;
    const count = Math.min(limit, totalAvailable);
    return Promise.resolve(
      evStationsResponse(
        Array.from({length: count}, (_, i) => `P-${i}`),
        totalAvailable,
      ),
    );
  }) as unknown as typeof fetch;
}

function mockFetchSequence(responses: object[]) {
  let call = 0;
  global.fetch = jest.fn(() => {
    const response = responses[Math.min(call, responses.length - 1)];
    call += 1;
    return Promise.resolve(response);
  }) as unknown as typeof fetch;
}

async function search(renderer: ReactTestRenderer, query: string) {
  await act(async () => {
    renderer.root.findByType(TextInput).props.onChangeText(query);
  });
  await act(async () => {
    renderer.root.findByProps({accessibilityLabel: 'Search'}).props.onPress();
  });
}

async function pressLoadMore(renderer: ReactTestRenderer) {
  await act(async () => {
    renderer.root
      .findByProps({accessibilityLabel: 'Load more stations'})
      .props.onPress();
  });
}

function hasLoadMoreButton(renderer: ReactTestRenderer): boolean {
  return (
    renderer.root.findAllByProps({accessibilityLabel: 'Load more stations'})
      .length > 0
  );
}

it('loads more stations when the Load More button is pressed, replacing rather than appending', async () => {
  mockFetchSequence([
    evStationsResponse(['Zap'], 2), // initial list search
    evStationsResponse(['Zap'], 2), // initial map-radius fetch (unused here)
    evStationsResponse(['Zap', 'Volt'], 2), // load more (list only)
  ]);

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvScreen
        persistedSearch={INITIAL_PERSISTED_EV_SEARCH}
        onSearchComplete={() => {}}
      />,
    );
  });

  await search(renderer!, 'Chicago');

  let list = renderer!.root.findByType(FlatList);
  expect(list.props.data.map((s: {name: string}) => s.name)).toEqual(['Zap']);

  await pressLoadMore(renderer!);

  list = renderer!.root.findByType(FlatList);
  expect(list.props.data.map((s: {name: string}) => s.name)).toEqual([
    'Zap',
    'Volt',
  ]);

  // total_results (2) has now been fully satisfied — button disappears.
  expect(hasLoadMoreButton(renderer!)).toBe(false);

  // Load More targets stations.length + EV_STATIONS_PER_PAGE (1 + 20) as
  // the new total to fetch, not a fixed page size — there's no cursor to
  // continue from, so this asks for "1 more than currently shown, plus a
  // full page" in one shot. Load More never touches the map-radius fetch,
  // so this is the third call overall (list, map, then this).
  const searchCalls = (global.fetch as jest.Mock).mock.calls.map(
    call => call[0] as string,
  );
  expect(searchCalls[2]).toContain('limit=21');
});

it('pulling to refresh re-runs the same search and replaces the results', async () => {
  mockFetchSequence([
    evStationsResponse(['Zap'], 2), // initial list search
    evStationsResponse(['Zap'], 2), // initial map-radius fetch
    evStationsResponse(['Volt', 'Bolt'], 2), // refresh list search
    evStationsResponse(['Volt', 'Bolt'], 2), // refresh map-radius fetch
  ]);

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvScreen
        persistedSearch={INITIAL_PERSISTED_EV_SEARCH}
        onSearchComplete={() => {}}
      />,
    );
  });

  await search(renderer!, 'Chicago');
  expect(
    renderer!.root
      .findByType(FlatList)
      .props.data.map((s: {name: string}) => s.name),
  ).toEqual(['Zap']);

  const fetchCallsBeforeRefresh = (global.fetch as jest.Mock).mock.calls.length;

  await act(async () => {
    renderer!.root.findByType(FlatList).props.refreshControl.props.onRefresh();
  });

  // A refresh re-runs both the list search and the map-radius fetch, the
  // same way a fresh search does — two calls, not one.
  const refreshCalls = (global.fetch as jest.Mock).mock.calls.slice(
    fetchCallsBeforeRefresh,
  );
  expect(refreshCalls).toHaveLength(2);
  expect(refreshCalls[0][0]).toContain('query=Chicago');

  expect(
    renderer!.root
      .findByType(FlatList)
      .props.data.map((s: {name: string}) => s.name),
  ).toEqual(['Volt', 'Bolt']);
});

it('keeps showing the existing results, uninterrupted, when a pull-to-refresh fails', async () => {
  mockFetchSequence([evStationsResponse(['Zap'], 2)]);

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvScreen
        persistedSearch={INITIAL_PERSISTED_EV_SEARCH}
        onSearchComplete={() => {}}
      />,
    );
  });

  await search(renderer!, 'Chicago');

  global.fetch = jest.fn(() =>
    Promise.reject(new Error('Network down')),
  ) as unknown as typeof fetch;

  await act(async () => {
    renderer!.root.findByType(FlatList).props.refreshControl.props.onRefresh();
  });

  expect(
    renderer!.root
      .findByType(FlatList)
      .props.data.map((s: {name: string}) => s.name),
  ).toEqual(['Zap']);
  expect(
    renderer!.root.findByType(FlatList).props.refreshControl.props.refreshing,
  ).toBe(false);
});

it('shows a loading spinner while a location search is in flight, then replaces it with results', async () => {
  let resolveSearch: (value: unknown) => void = () => {};
  const searchResponsePromise = new Promise(resolve => {
    resolveSearch = resolve;
  });

  global.fetch = jest.fn(
    () => searchResponsePromise,
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvScreen
        persistedSearch={INITIAL_PERSISTED_EV_SEARCH}
        onSearchComplete={() => {}}
      />,
    );
  });

  await act(async () => {
    renderer!.root.findByType(TextInput).props.onChangeText('Chicago');
  });
  act(() => {
    renderer!.root.findByProps({accessibilityLabel: 'Search'}).props.onPress();
  });

  expect(renderer!.root.findAllByType(FlatList)).toHaveLength(0);
  expect(renderer!.root.findByType(ActivityIndicator)).toBeTruthy();

  await act(async () => {
    resolveSearch(evStationsResponse(['Zap'], 1));
    await searchResponsePromise;
  });

  expect(
    renderer!.root
      .findByType(FlatList)
      .props.data.map((s: {name: string}) => s.name),
  ).toEqual(['Zap']);
});

it('fetches map data for a 30km radius using the resolved coordinates, not a second geocode', async () => {
  mockFetchSequence([
    evStationsResponse(['Zap'], 1), // list search
    evStationsResponse(['Zap', 'Volt', 'Bolt'], 3), // map-radius fetch
  ]);

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvScreen
        persistedSearch={INITIAL_PERSISTED_EV_SEARCH}
        onSearchComplete={() => {}}
      />,
    );
  });

  await search(renderer!, 'Chicago');

  const calls = (global.fetch as jest.Mock).mock.calls.map(
    call => call[0] as string,
  );
  expect(calls).toHaveLength(2);
  // The list call geocodes via `query`...
  expect(calls[0]).toContain('query=Chicago');
  // ...but the map call reuses the coordinates the list call resolved,
  // requesting NREL's own max (200, "no cap of our own") over a 30km
  // radius rather than List view's small per-page limit.
  expect(calls[1]).toContain('lat=41.85');
  expect(calls[1]).toContain('lon=-87.65');
  expect(calls[1]).toContain('limit=200');
  expect(calls[1]).toContain('radius_km=30');
  expect(calls[1]).not.toContain('query=');

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show map view'})
      .props.onPress();
  });

  const webview = renderer!.root.findByType(WebView);
  const idMatches = webview.props.source.html.match(/"id":"[^"]+"/g) ?? [];
  // All 3 map-radius results are shown — not capped down to the list's
  // own small page, since "no maximum" applies to the map specifically.
  expect(idMatches).toHaveLength(3);
});

it('keeps showing the existing map pins, uninterrupted, when the map-radius fetch fails on refresh', async () => {
  mockFetchSequence([
    evStationsResponse(['Zap'], 1), // initial list search
    evStationsResponse(['Zap', 'Volt'], 2), // initial map-radius fetch
  ]);

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvScreen
        persistedSearch={INITIAL_PERSISTED_EV_SEARCH}
        onSearchComplete={() => {}}
      />,
    );
  });

  await search(renderer!, 'Chicago');
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show map view'})
      .props.onPress();
  });

  const pinsBeforeFailedRefresh =
    renderer!.root
      .findByType(WebView)
      .props.source.html.match(/"id":"[^"]+"/g) ?? [];
  expect(pinsBeforeFailedRefresh).toHaveLength(2);

  global.fetch = jest.fn(() =>
    Promise.reject(new Error('Network down')),
  ) as unknown as typeof fetch;

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show list view'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root.findByType(FlatList).props.refreshControl.props.onRefresh();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show map view'})
      .props.onPress();
  });

  const pinsAfterFailedRefresh =
    renderer!.root
      .findByType(WebView)
      .props.source.html.match(/"id":"[^"]+"/g) ?? [];
  expect(pinsAfterFailedRefresh).toHaveLength(2);
});

it('recenters the map on a fresh search, but not on "Search this area"', async () => {
  mockFetchSequence([
    evStationsResponse(['Zap'], 1), // initial list search
    evStationsResponse(['Zap'], 1), // initial map-radius fetch
    evStationsResponse(['Volt'], 1), // "Search this area" list search
    evStationsResponse(['Volt'], 1), // "Search this area" map-radius fetch
    evStationsResponse(['Bolt'], 1), // second fresh search (list)
    evStationsResponse(['Bolt'], 1), // second fresh search (map-radius)
  ]);

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvScreen
        persistedSearch={INITIAL_PERSISTED_EV_SEARCH}
        onSearchComplete={() => {}}
      />,
    );
  });

  await search(renderer!, 'Chicago');
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show map view'})
      .props.onPress();
  });

  expect(renderer!.root.findByType(EvStationMap).props.recenterSignal).toBe(1);

  // Pan far away and tap "Search this area" — this resolves a new center
  // too, but must not recenter/rezoom the map away from where the user
  // just panned it.
  const webview = renderer!.root.findByType(WebView);
  await act(async () => {
    webview.props.onMessage({
      nativeEvent: {
        data: JSON.stringify({type: 'centerChanged', lat: 50, lon: -100}),
      },
    });
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Search this area'})
      .props.onPress();
  });

  expect(renderer!.root.findByType(EvStationMap).props.recenterSignal).toBe(1);

  // A brand new search via the search bar, though, should recenter again.
  await search(renderer!, 'Cambridge');
  expect(renderer!.root.findByType(EvStationMap).props.recenterSignal).toBe(2);
});

it('switches to the map view without making any extra API calls', async () => {
  mockFetchSequence([evStationsResponse(['Zap', 'Volt'], 2)]);

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvScreen
        persistedSearch={INITIAL_PERSISTED_EV_SEARCH}
        onSearchComplete={() => {}}
      />,
    );
  });

  await search(renderer!, 'Chicago');

  const fetchCallsBeforeToggle = (global.fetch as jest.Mock).mock.calls.length;

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show map view'})
      .props.onPress();
  });

  expect(renderer!.root.findAllByType(FlatList)).toHaveLength(0);
  expect(renderer!.root.findByType(WebView)).toBeTruthy();

  expect((global.fetch as jest.Mock).mock.calls.length).toBe(
    fetchCallsBeforeToggle,
  );
});

it('caps total fetched stations at 40, targeting 20 more at a time, then hides Load More', async () => {
  mockLimitAwareFetch(60);

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvScreen
        persistedSearch={INITIAL_PERSISTED_EV_SEARCH}
        onSearchComplete={() => {}}
      />,
    );
  });

  await search(renderer!, 'Chicago');
  expect(renderer!.root.findByType(FlatList).props.data).toHaveLength(20);
  expect(hasLoadMoreButton(renderer!)).toBe(true);

  await pressLoadMore(renderer!);
  expect(renderer!.root.findByType(FlatList).props.data).toHaveLength(40);
  // Cap reached — button hidden even though the API reports more (60) exist.
  expect(hasLoadMoreButton(renderer!)).toBe(false);

  // Excludes the map-radius fetch (identifiable by radius_km) that also
  // fires alongside the initial search — this only checks List view's own
  // limit/cap behavior.
  const searchCalls = (global.fetch as jest.Mock).mock.calls
    .map(call => call[0] as string)
    .filter(
      url => url.includes('/ev-stations/search') && !url.includes('radius_km'),
    );
  expect(searchCalls).toHaveLength(2);
  expect(searchCalls[0]).toContain('limit=20');
  expect(searchCalls[1]).toContain('limit=40');
});

it('restores the first page from persisted state without refetching, dropping any loaded extra pages', async () => {
  mockFetchSequence([
    evStationsResponse(['Zap'], 2), // initial list search
    evStationsResponse(['Zap'], 2), // initial map-radius fetch
    evStationsResponse(['Zap', 'Volt'], 2), // load more (list only)
  ]);

  let persisted: PersistedEvSearch = INITIAL_PERSISTED_EV_SEARCH;
  const onSearchComplete = (next: PersistedEvSearch) => {
    persisted = next;
  };

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvScreen
        persistedSearch={persisted}
        onSearchComplete={onSearchComplete}
      />,
    );
  });

  await search(renderer!, 'Chicago');
  await pressLoadMore(renderer!);
  expect(
    renderer!.root
      .findByType(FlatList)
      .props.data.map((s: {name: string}) => s.name),
  ).toEqual(['Zap', 'Volt']);

  await act(async () => {
    renderer!.unmount();
  });

  const fetchCallsBeforeRemount = (global.fetch as jest.Mock).mock.calls.length;

  await act(async () => {
    renderer = create(
      <EvScreen
        persistedSearch={persisted}
        onSearchComplete={onSearchComplete}
      />,
    );
  });

  // Nothing refetches on mount — EvScreen (unlike HomeScreen) has no health
  // check of its own, so a fresh mount from persisted state alone should
  // make zero requests.
  expect((global.fetch as jest.Mock).mock.calls.length).toBe(
    fetchCallsBeforeRemount,
  );

  const list = renderer!.root.findByType(FlatList);
  expect(list.props.data.map((s: {name: string}) => s.name)).toEqual(['Zap']);
  expect(renderer!.root.findByType(TextInput).props.value).toBe('Chicago');

  await act(async () => {
    renderer!.unmount();
  });
});
