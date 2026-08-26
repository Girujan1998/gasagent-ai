/**
 * @format
 */

import React from 'react';
import {TextInput} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest, beforeEach, afterEach} from '@jest/globals';

import LocationSearchBar, {
  LocationQuery,
} from '../src/components/LocationSearchBar';
import {LocationProvider} from '../src/store/LocationContext';

type FetchResult = {ok: boolean; json: () => Promise<unknown>};
type FetchFn = (...args: unknown[]) => Promise<FetchResult>;

function getFetchMock(): jest.Mock<FetchFn> {
  return global.fetch as unknown as jest.Mock<FetchFn>;
}

// LocationSearchBar reads/writes the app-wide shared-location context (see
// LocationContext.tsx) — every render needs this wrapper, the same as
// App.tsx itself provides it at the top level.
function renderSearchBar(props?: {
  onSearch?: (query: LocationQuery) => void;
  initialQuery?: LocationQuery | null;
}) {
  return create(
    <LocationProvider>
      <LocationSearchBar {...props} />
    </LocationProvider>,
  );
}

// The debounce is 300ms — waiting this out inside act() lets any pending
// timer fire (and its fetch settle) before the test ends, so nothing is
// left running to trip up a later test.
async function flushDebounce() {
  await act(async () => {
    await new Promise(resolve => setTimeout(resolve, 350));
  });
}

beforeEach(() => {
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve({results: []}),
    }),
  ) as unknown as typeof fetch;
});

afterEach(() => {
  jest.restoreAllMocks();
});

it('submits a typed city/postal code search', async () => {
  const onSearch = jest.fn<(query: LocationQuery) => void>();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = renderSearchBar({onSearch});
  });

  const input = renderer!.root.findByType(TextInput);
  await act(async () => {
    input.props.onChangeText('90210');
  });
  await flushDebounce();

  const searchButton = renderer!.root.findByProps({
    accessibilityLabel: 'Search',
  });
  await act(async () => {
    searchButton.props.onPress();
  });

  expect(onSearch).toHaveBeenCalledWith({type: 'text', value: '90210'});
});

it('restores a persisted text query on mount and can clear it', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = renderSearchBar({initialQuery: {type: 'text', value: '60614'}});
  });
  await flushDebounce();

  expect(renderer!.root.findByType(TextInput).props.value).toBe('60614');

  const clearButton = renderer!.root.findByProps({
    accessibilityLabel: 'Clear search',
  });
  await act(async () => {
    clearButton.props.onPress();
  });

  expect(renderer!.root.findByType(TextInput).props.value).toBe('');
  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Clear search'}),
  ).toThrow();
});

it('does not show the autocomplete dropdown just from restoring a persisted query on mount', async () => {
  // Simulates leaving the Home tab and coming back: this component
  // remounts with a non-empty initialQuery from a previous search, but
  // the user hasn't typed or focused anything this time.
  const fetchMock = getFetchMock();
  fetchMock.mockResolvedValue({
    ok: true,
    json: () =>
      Promise.resolve({
        results: [
          {
            label: 'Cambridge, Ontario, Canada',
            value: 'Cambridge, Ontario, Canada',
          },
        ],
      }),
  });

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = renderSearchBar({initialQuery: {type: 'text', value: 'Cambridge'}});
  });
  await flushDebounce();

  expect(fetchMock).not.toHaveBeenCalled();
  expect(() =>
    renderer!.root.findByProps({
      accessibilityLabel: 'Search Cambridge, Ontario, Canada',
    }),
  ).toThrow();
});

it('restores a persisted coordinate query as a location label on mount', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = renderSearchBar({initialQuery: {type: 'coordinates', latitude: 41.85, longitude: -87.65}});
  });

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Clear search'}),
  ).toBeTruthy();
});

it('does not show the clear button when there is nothing to clear', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = renderSearchBar();
  });

  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Clear search'}),
  ).toThrow();
});

it('fetches suggestions once 3 characters have been entered, after a debounce', async () => {
  const fetchMock = getFetchMock();
  fetchMock.mockResolvedValue({
    ok: true,
    json: () =>
      Promise.resolve({
        results: [
          {
            label: 'Cambridge, Ontario, Canada',
            value: 'Cambridge, Ontario, Canada',
          },
        ],
      }),
  });

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = renderSearchBar();
  });

  const input = renderer!.root.findByType(TextInput);

  // Below the 3-character threshold: no request at all.
  await act(async () => {
    input.props.onChangeText('Ca');
  });
  await flushDebounce();
  expect(fetchMock).not.toHaveBeenCalled();

  await act(async () => {
    input.props.onChangeText('Cam');
  });
  await flushDebounce();

  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining('/locations/autocomplete?query=Cam'),
    expect.anything(),
  );
  expect(
    renderer!.root.findByProps({
      accessibilityLabel: 'Search Cambridge, Ontario, Canada',
    }),
  ).toBeTruthy();
});

it('selects a suggestion by filling the input and searching immediately', async () => {
  const fetchMock = getFetchMock();
  fetchMock.mockResolvedValue({
    ok: true,
    json: () =>
      Promise.resolve({
        results: [{label: 'N1T · Cambridge East, ON', value: 'N1T'}],
      }),
  });
  const onSearch = jest.fn<(query: LocationQuery) => void>();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = renderSearchBar({onSearch});
  });

  const input = renderer!.root.findByType(TextInput);
  await act(async () => {
    input.props.onChangeText('N1T');
  });
  await flushDebounce();

  const suggestionRow = renderer!.root.findByProps({
    accessibilityLabel: 'Search N1T · Cambridge East, ON',
  });
  await act(async () => {
    suggestionRow.props.onPress();
  });

  expect(onSearch).toHaveBeenCalledWith({type: 'text', value: 'N1T'});
  expect(renderer!.root.findByType(TextInput).props.value).toBe('N1T');
  expect(() =>
    renderer!.root.findByProps({
      accessibilityLabel: 'Search N1T · Cambridge East, ON',
    }),
  ).toThrow();
});

it('hides the suggestions dropdown after clearing the search', async () => {
  const fetchMock = getFetchMock();
  fetchMock.mockResolvedValue({
    ok: true,
    json: () =>
      Promise.resolve({
        results: [
          {label: 'Chicago, Illinois, United States', value: 'Chicago'},
        ],
      }),
  });

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = renderSearchBar();
  });

  const input = renderer!.root.findByType(TextInput);
  await act(async () => {
    input.props.onChangeText('Chi');
  });
  await flushDebounce();

  expect(
    renderer!.root.findByProps({
      accessibilityLabel: 'Search Chicago, Illinois, United States',
    }),
  ).toBeTruthy();

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Clear search'})
      .props.onPress();
  });

  expect(() =>
    renderer!.root.findByProps({
      accessibilityLabel: 'Search Chicago, Illinois, United States',
    }),
  ).toThrow();
});

it('searches with a restored coordinate query in one tap, without a fresh GPS fix', async () => {
  // Mirrors a prefill from a location shared in another tab: the search
  // bar mounts already showing a location (via initialQuery), but the
  // user still has to press search once to actually run it here — the
  // whole point being that pressing search reuses these coordinates
  // rather than triggering Geolocation again.
  const onSearch = jest.fn<(query: LocationQuery) => void>();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = renderSearchBar({
      onSearch,
      initialQuery: {type: 'coordinates', latitude: 43.36, longitude: -80.31},
    });
  });

  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Search'}).props.onPress();
  });

  expect(onSearch).toHaveBeenCalledWith({
    type: 'coordinates',
    latitude: 43.36,
    longitude: -80.31,
  });
});

it('does not let a stale autocomplete response reopen the dropdown after a manual search', async () => {
  const fetchMock = getFetchMock();
  fetchMock.mockResolvedValue({
    ok: true,
    json: () =>
      Promise.resolve({
        results: [
          {
            label: 'Cambridge, Ontario, Canada',
            value: 'Cambridge, Ontario, Canada',
          },
        ],
      }),
  });
  const onSearch = jest.fn<(query: LocationQuery) => void>();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = renderSearchBar({onSearch});
  });

  const input = renderer!.root.findByType(TextInput);
  await act(async () => {
    input.props.onChangeText('Cambridge');
  });

  // Search right away — the debounced autocomplete fetch scheduled by the
  // typing above is still pending, not yet resolved.
  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Search'}).props.onPress();
  });

  expect(onSearch).toHaveBeenCalledWith({type: 'text', value: 'Cambridge'});

  // Wait out the debounce window that pending request was scheduled on —
  // it must not repopulate the dropdown once it resolves.
  await flushDebounce();

  expect(() =>
    renderer!.root.findByProps({
      accessibilityLabel: 'Search Cambridge, Ontario, Canada',
    }),
  ).toThrow();
});
