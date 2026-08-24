/**
 * @format
 */

import React from 'react';
import {
  ActivityIndicator,
  FlatList,
  Keyboard,
  TextInput,
  TouchableWithoutFeedback,
} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';
import WebView from 'react-native-webview';

import FilterControl from '../src/components/FilterControl';
import SortControl from '../src/components/SortControl';
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
          connected_brand: null,
          connected_brand_logo_url: null,
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
          amenities: [],
        })),
        next_cursor: nextCursor,
        lat: 41.85,
        lon: -87.65,
      }),
  };
}

function fullPage(label: string, nextCursor: string | null) {
  return stationsResponse(
    Array.from({length: 20}, (_, i) => `${label}-${i}`),
    nextCursor,
  );
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

it('loads more stations when the Load More button is pressed', async () => {
  mockFetchSequence([
    healthResponse,
    stationsResponse(['Shell'], '20'),
    stationsResponse(['BP'], null),
  ]);

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

  await search(renderer!, 'Chicago');

  let list = renderer!.root.findByType(FlatList);
  expect(list.props.data.map((s: {name: string}) => s.name)).toEqual(['Shell']);

  await pressLoadMore(renderer!);

  list = renderer!.root.findByType(FlatList);
  expect(list.props.data.map((s: {name: string}) => s.name)).toEqual([
    'Shell',
    'BP',
  ]);

  // No more pages left (next_cursor was null), so the button disappears
  // rather than allowing another press.
  expect(hasLoadMoreButton(renderer!)).toBe(false);

  await act(async () => {
    renderer!.unmount();
  });
});

it('pulling to refresh re-runs the same search and replaces the results', async () => {
  mockFetchSequence([
    healthResponse,
    stationsResponse(['Shell'], '20'),
    stationsResponse(['BP', 'Exxon'], null),
  ]);

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

  await search(renderer!, 'Chicago');
  expect(
    renderer!.root
      .findByType(FlatList)
      .props.data.map((s: {name: string}) => s.name),
  ).toEqual(['Shell']);

  const fetchCallsBeforeRefresh = (global.fetch as jest.Mock).mock.calls.length;

  await act(async () => {
    renderer!.root.findByType(FlatList).props.refreshControl.props.onRefresh();
  });

  // Exactly one new request — for the same "Chicago" query, not a
  // continuation (no cursor) of the old page.
  const refreshCalls = (global.fetch as jest.Mock).mock.calls.slice(
    fetchCallsBeforeRefresh,
  );
  expect(refreshCalls).toHaveLength(1);
  expect(refreshCalls[0][0]).toContain('query=Chicago');
  expect(refreshCalls[0][0]).not.toContain('cursor=');

  expect(
    renderer!.root
      .findByType(FlatList)
      .props.data.map((s: {name: string}) => s.name),
  ).toEqual(['BP', 'Exxon']);

  await act(async () => {
    renderer!.unmount();
  });
});

it('keeps showing the existing results, uninterrupted, when a pull-to-refresh fails', async () => {
  mockFetchSequence([healthResponse, stationsResponse(['Shell'], '20')]);

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

  await search(renderer!, 'Chicago');

  global.fetch = jest.fn(() =>
    Promise.reject(new Error('Network down')),
  ) as unknown as typeof fetch;

  await act(async () => {
    renderer!.root.findByType(FlatList).props.refreshControl.props.onRefresh();
  });

  // Still showing the station from before the failed refresh — no error
  // screen took its place.
  expect(
    renderer!.root
      .findByType(FlatList)
      .props.data.map((s: {name: string}) => s.name),
  ).toEqual(['Shell']);
  expect(
    renderer!.root.findByType(FlatList).props.refreshControl.props.refreshing,
  ).toBe(false);

  await act(async () => {
    renderer!.unmount();
  });
});

it('shows a loading spinner while a location search is in flight, then replaces it with results', async () => {
  let resolveSearch: (value: unknown) => void = () => {};
  const searchResponsePromise = new Promise(resolve => {
    resolveSearch = resolve;
  });

  global.fetch = jest.fn((url: unknown) => {
    if (typeof url === 'string' && url.includes('/health')) {
      return Promise.resolve(healthResponse);
    }
    return searchResponsePromise;
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
  // Don't await this one — the search is deliberately left in flight so
  // the spinner can be observed before the response resolves.
  act(() => {
    renderer!.root.findByProps({accessibilityLabel: 'Search'}).props.onPress();
  });

  // While in flight: a spinner is shown, not an empty list or the intro
  // screen (hasSearched is already true at this point).
  expect(renderer!.root.findAllByType(FlatList)).toHaveLength(0);
  expect(renderer!.root.findByType(ActivityIndicator)).toBeTruthy();

  await act(async () => {
    resolveSearch(stationsResponse(['Shell'], null));
    await searchResponsePromise;
  });

  expect(
    renderer!.root
      .findByType(FlatList)
      .props.data.map((s: {name: string}) => s.name),
  ).toEqual(['Shell']);

  await act(async () => {
    renderer!.unmount();
  });
});

it('switches to the map view without making any extra API calls', async () => {
  mockFetchSequence([healthResponse, stationsResponse(['Shell', 'BP'], '20')]);

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

  await search(renderer!, 'Chicago');

  const fetchCallsBeforeToggle = (global.fetch as jest.Mock).mock.calls.length;

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show map view'})
      .props.onPress();
  });

  // The list is gone and the map is showing instead.
  expect(renderer!.root.findAllByType(FlatList)).toHaveLength(0);
  const webview = renderer!.root.findByType(WebView);
  expect(webview).toBeTruthy();

  // Tapping a pin and switching back to List are both purely local — the
  // map only ever displays the fixed pool of stations already fetched for
  // the list (see MAX_TOTAL_STATIONS in HomeScreen.tsx), so neither of
  // these should reach the network.
  await act(async () => {
    webview.props.onMessage({
      nativeEvent: {
        data: JSON.stringify({type: 'selectStation', stationId: 'Shell-0'}),
      },
    });
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show list view'})
      .props.onPress();
  });

  expect((global.fetch as jest.Mock).mock.calls.length).toBe(
    fetchCallsBeforeToggle,
  );

  await act(async () => {
    renderer!.unmount();
  });
});

it('caps the map at 20 stations even when List view has loaded more via Load More', async () => {
  function fullPageWithCoords(label: string, nextCursor: string | null) {
    return {
      ok: true,
      json: () =>
        Promise.resolve({
          results: Array.from({length: 20}, (_, i) => ({
            station_id: `${label}-${i}`,
            name: `${label}-${i}`,
            brand: label,
            brand_logo_url: null,
            connected_brand: null,
            connected_brand_logo_url: null,
            address: null,
            latitude: 41.8 + i * 0.001,
            longitude: -87.6 + i * 0.001,
            distance_miles: 1,
            regular: null,
            midgrade: null,
            premium: null,
            diesel: null,
            star_rating: null,
            ratings_count: null,
            amenities: [],
          })),
          next_cursor: nextCursor,
          lat: 41.85,
          lon: -87.65,
        }),
    };
  }

  mockFetchSequence([
    healthResponse,
    fullPageWithCoords('P1', '20'),
    fullPageWithCoords('P2', null),
  ]);

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

  await search(renderer!, 'Chicago');
  await pressLoadMore(renderer!); // 40 stations now loaded for List view

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show map view'})
      .props.onPress();
  });

  const webview = renderer!.root.findByType(WebView);
  const idMatches = webview.props.source.html.match(/"id":"P[12]-\d+"/g) ?? [];
  expect(idMatches).toHaveLength(20);
  // Specifically the first page loaded, not the second one Load More added.
  expect(webview.props.source.html).toContain('"id":"P1-0"');
  expect(webview.props.source.html).not.toContain('"id":"P2-0"');

  await act(async () => {
    renderer!.unmount();
  });
});

it('only fetches for the map\'s new area when "Search this area" is pressed, not just from panning', async () => {
  mockFetchSequence([
    healthResponse,
    stationsResponse(['Shell'], null),
    stationsResponse(['Exxon'], null),
  ]);

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

  await search(renderer!, 'Chicago');
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show map view'})
      .props.onPress();
  });

  const fetchCallsBeforePan = (global.fetch as jest.Mock).mock.calls.length;

  // Panning the map alone — reported via the embedded page's centerChanged
  // message — must never fetch anything on its own.
  const webview = renderer!.root.findByType(WebView);
  const newCenter = {lat: 47.6, lon: -122.3};
  await act(async () => {
    webview.props.onMessage({
      nativeEvent: {
        data: JSON.stringify({type: 'centerChanged', ...newCenter}),
      },
    });
  });
  expect((global.fetch as jest.Mock).mock.calls.length).toBe(
    fetchCallsBeforePan,
  );

  // Only the explicit "Search this area" press should fetch — exactly
  // once, for the coordinates the map reported.
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Search this area'})
      .props.onPress();
  });

  const searchAreaCalls = (global.fetch as jest.Mock).mock.calls
    .map(call => call[0] as string)
    .slice(fetchCallsBeforePan);
  expect(searchAreaCalls).toHaveLength(1);
  expect(searchAreaCalls[0]).toContain(`lat=${newCenter.lat}`);
  expect(searchAreaCalls[0]).toContain(`lon=${newCenter.lon}`);

  await act(async () => {
    renderer!.unmount();
  });
});

it('does not fetch again just because a brand filter narrows the visible results', async () => {
  // A filter only ever narrows what's shown from stations already fetched
  // — it must never trigger its own fetch, even though the filtered list
  // (Shell only) is far shorter than the full page.
  mockFetchSequence([
    healthResponse,
    stationsResponse(['Shell', 'BP', 'BP', 'BP', 'BP'], '20'),
  ]);

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

  await search(renderer!, 'Chicago');

  const fetchCallsBeforeFilter = (global.fetch as jest.Mock).mock.calls.length;

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Open filters'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Hide BP'}).props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Apply brand filters'})
      .props.onPress();
  });

  expect((global.fetch as jest.Mock).mock.calls.length).toBe(
    fetchCallsBeforeFilter,
  );
  expect(
    renderer!.root
      .findByType(FlatList)
      .props.data.map((s: {name: string}) => s.name),
  ).toEqual(['Shell']);

  // A page is still available from the API (next_cursor '20'), so the
  // filter narrowing the visible list doesn't hide the button either —
  // the user can still choose to fetch more of the unfiltered pool.
  expect(hasLoadMoreButton(renderer!)).toBe(true);

  await act(async () => {
    renderer!.unmount();
  });
});

it('caps total fetched stations at 40, requesting at most 20 per page, then hides Load More', async () => {
  mockFetchSequence([
    healthResponse,
    fullPage('P1', '20'),
    fullPage('P2', '40'),
    fullPage('P3', '60'), // API still has more, but the 40 cap stops us first
  ]);

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

  await search(renderer!, 'Chicago');
  expect(renderer!.root.findByType(FlatList).props.data).toHaveLength(20);
  expect(hasLoadMoreButton(renderer!)).toBe(true);

  await pressLoadMore(renderer!);
  expect(renderer!.root.findByType(FlatList).props.data).toHaveLength(40);
  // Cap reached — button hidden even though the API had another page.
  expect(hasLoadMoreButton(renderer!)).toBe(false);

  // Every request (initial search + 1 load-more) asked for at most 20.
  const searchCalls = (global.fetch as jest.Mock).mock.calls
    .map(call => call[0] as string)
    .filter(url => url.includes('/stations/search'));
  expect(searchCalls).toHaveLength(2);
  searchCalls.forEach(url => expect(url).toContain('limit=20'));

  await act(async () => {
    renderer!.unmount();
  });
});

it('restores the first page from persisted state without refetching, dropping any loaded extra pages', async () => {
  mockFetchSequence([
    healthResponse,
    stationsResponse(['Shell'], '20'),
    stationsResponse(['BP'], null),
  ]);

  let persisted: PersistedSearch = INITIAL_PERSISTED_SEARCH;
  const onSearchComplete = (
    next: PersistedSearch | ((prev: PersistedSearch) => PersistedSearch),
  ) => {
    persisted = typeof next === 'function' ? next(persisted) : next;
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

  await search(renderer!, 'Chicago');
  // Simulate the user loading a second page before leaving the tab.
  await pressLoadMore(renderer!);
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

  // Unmount so LocationSearchBar's debounced autocomplete timer (queued by
  // the persisted "Chicago" query on this second mount) is cancelled
  // rather than firing later against a subsequent test's fetch mock.
  await act(async () => {
    renderer!.unmount();
  });
});

it('persists sort order and filter selections immediately, independent of any search', async () => {
  mockFetchSequence([healthResponse, stationsResponse(['Shell', 'BP'], null)]);

  let persisted: PersistedSearch = INITIAL_PERSISTED_SEARCH;
  const onSearchComplete = (
    next: PersistedSearch | ((prev: PersistedSearch) => PersistedSearch),
  ) => {
    persisted = typeof next === 'function' ? next(persisted) : next;
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

  await search(renderer!, 'Chicago');

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Change sort order'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'Sort by Price (Regular) and Distance',
      })
      .props.onPress();
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Open filters'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show Midgrade as Price 1'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Hide BP'}).props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Apply brand filters'})
      .props.onPress();
  });

  // Persisted immediately on each change — not deferred until another
  // search runs.
  expect(persisted.sortBy).toBe('price1AndDistance');
  expect(persisted.primaryFuelKey).toBe('midgrade');
  expect(persisted.selectedBrandKeys).toEqual(new Set(['Shell']));

  // Leaving the Home tab unmounts it; coming back mounts a fresh instance
  // seeded from persisted state, same as HomeScreen's search results.
  await act(async () => {
    renderer!.unmount();
  });
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

  expect(renderer!.root.findByType(SortControl).props.value).toBe(
    'price1AndDistance',
  );
  const filterProps = renderer!.root.findByType(FilterControl).props;
  expect(filterProps.primaryFuelKey).toBe('midgrade');
  expect(filterProps.selectedBrandKeys).toEqual(new Set(['Shell']));

  // The brand filter is also actually applied to the list, not just
  // restored as an unused selection.
  expect(
    renderer!.root
      .findByType(FlatList)
      .props.data.map((s: {name: string}) => s.name),
  ).toEqual(['Shell']);

  await act(async () => {
    renderer!.unmount();
  });
});

it('dismisses the keyboard when tapping outside the search bar, without requiring a search', async () => {
  mockFetchSequence([healthResponse]);
  const dismissSpy = jest.spyOn(Keyboard, 'dismiss');

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <HomeScreen
          persistedSearch={INITIAL_PERSISTED_SEARCH}
          onSearchComplete={jest.fn()}
        />
      </FavoritesProvider>,
    );
  });

  // Both the top search-bar section and the (currently shown, since no
  // search has run yet) intro section have their own dismiss wrapper —
  // either one tapped should close the keyboard.
  await act(async () => {
    renderer!.root
      .findAllByType(TouchableWithoutFeedback)
      .forEach(instance => instance.props.onPress());
  });

  expect(dismissSpy).toHaveBeenCalled();
  dismissSpy.mockRestore();
});
