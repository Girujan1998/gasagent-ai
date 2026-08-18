/**
 * @format
 */

import React, {useState} from 'react';
import {ActivityIndicator, ScrollView, Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import {LocationQuery} from '../src/components/LocationSearchBar';
import NotificationsScreen, {
  INITIAL_PERSISTED_FORECAST,
  PersistedForecast,
} from '../src/screens/NotificationsScreen';

type Location = {lat: number; lon: number};

const CAMBRIDGE_QUERY: LocationQuery = {
  type: 'text',
  value: 'Cambridge, Ontario, Canada',
};

function forecastResponse(overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    json: () =>
      Promise.resolve({
        lat: 43.36,
        lon: -80.31,
        today_average_price: 167.7,
        forecasted_price: 168.9,
        today_average_formatted: '167.7¢',
        forecasted_price_formatted: '168.9¢',
        price_change: 1.2,
        price_change_formatted: '+1.2¢',
        trend_direction: 'up',
        daily_change_pct: 0.0023,
        source: 'statcan',
        source_period_end: '2026-07-01',
        stations_sampled: 8,
        today_lowest_price: 158.9,
        today_highest_price: 175.9,
        today_lowest_formatted: '158.9¢',
        today_highest_formatted: '175.9¢',
        forecasted_lowest_price: 159.1,
        forecasted_highest_price: 176.1,
        forecasted_lowest_formatted: '159.1¢',
        forecasted_highest_formatted: '176.1¢',
        lowest_price_change: 0.2,
        lowest_price_change_formatted: '+0.2¢',
        highest_price_change: 0.2,
        highest_price_change_formatted: '+0.2¢',
        ...overrides,
      }),
  };
}

function texts(renderer: ReactTestRenderer): string[] {
  return renderer.root.findAllByType(Text).map(node =>
    ([] as unknown[])
      .concat(node.props.children)
      .filter(value => typeof value === 'string' || typeof value === 'number')
      .join(''),
  );
}

// Stands in for App.tsx: holds persistedForecast in a PARENT component, so
// it survives NotificationsScreen unmounting/remounting the same way it
// would when switching tabs away and back in the real app.
function Harness({
  mounted,
  searchLocation,
  locationQuery = CAMBRIDGE_QUERY,
}: {
  mounted: boolean;
  searchLocation: Location | null;
  locationQuery?: LocationQuery | null;
}): React.JSX.Element | null {
  const [persistedForecast, setPersistedForecast] = useState<PersistedForecast>(
    INITIAL_PERSISTED_FORECAST,
  );

  if (!mounted) {
    return null;
  }
  return (
    <NotificationsScreen
      searchLocation={searchLocation}
      locationQuery={locationQuery}
      persistedForecast={persistedForecast}
      onForecastComplete={setPersistedForecast}
    />
  );
}

it('prompts to search the Gas tab first when there is no location yet', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <NotificationsScreen
        searchLocation={null}
        locationQuery={null}
        persistedForecast={INITIAL_PERSISTED_FORECAST}
        onForecastComplete={jest.fn()}
      />,
    );
  });

  expect(texts(renderer!).join(' ')).toContain(
    'Search for gas stations on the Gas tab',
  );
  expect(renderer!.root.findAllByType(ActivityIndicator)).toHaveLength(0);
});

it('shows a loading spinner while the forecast is being fetched', async () => {
  let resolveFetch: (value: unknown) => void = () => {};
  global.fetch = jest.fn(
    () => new Promise(resolve => (resolveFetch = resolve)),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <NotificationsScreen
        searchLocation={{lat: 43.36, lon: -80.31}}
        locationQuery={CAMBRIDGE_QUERY}
        persistedForecast={INITIAL_PERSISTED_FORECAST}
        onForecastComplete={jest.fn()}
      />,
    );
  });

  expect(renderer!.root.findByType(ActivityIndicator)).toBeTruthy();

  await act(async () => {
    resolveFetch(forecastResponse());
  });
});

it('fetches and shows the forecast for the given search location', async () => {
  const fetchMock = jest.fn(() => Promise.resolve(forecastResponse()));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <NotificationsScreen
        searchLocation={{lat: 43.36, lon: -80.31}}
        locationQuery={CAMBRIDGE_QUERY}
        persistedForecast={INITIAL_PERSISTED_FORECAST}
        onForecastComplete={jest.fn()}
      />,
    );
  });

  expect(texts(renderer!)).toContain('168.9¢');
  const url = (fetchMock.mock.calls[0] as unknown[])[0] as string;
  expect(url).toContain('lat=43.36');
  expect(url).toContain('lon=-80.31');
  expect(url).toContain('/forecast');
});

it('shows the search location as a label', async () => {
  global.fetch = jest.fn(() =>
    Promise.resolve(forecastResponse()),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <NotificationsScreen
        searchLocation={{lat: 43.36, lon: -80.31}}
        locationQuery={CAMBRIDGE_QUERY}
        persistedForecast={INITIAL_PERSISTED_FORECAST}
        onForecastComplete={jest.fn()}
      />,
    );
  });

  expect(texts(renderer!)).toContain('Cambridge, Ontario, Canada');
});

it('shows coordinates as the label for a current-location search', async () => {
  global.fetch = jest.fn(() =>
    Promise.resolve(forecastResponse()),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <NotificationsScreen
        searchLocation={{lat: 43.36, lon: -80.31}}
        locationQuery={{
          type: 'coordinates',
          latitude: 43.36,
          longitude: -80.31,
        }}
        persistedForecast={INITIAL_PERSISTED_FORECAST}
        onForecastComplete={jest.fn()}
      />,
    );
  });

  expect(texts(renderer!).join(' ')).toContain('43.3600, -80.3100');
});

it('shows no location label before a search has happened', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <NotificationsScreen
        searchLocation={null}
        locationQuery={null}
        persistedForecast={INITIAL_PERSISTED_FORECAST}
        onForecastComplete={jest.fn()}
      />,
    );
  });

  expect(texts(renderer!)).not.toContain('Cambridge, Ontario, Canada');
});

it('shows both the average forecast card and the price range card from a single fetch', async () => {
  const fetchMock = jest.fn(() => Promise.resolve(forecastResponse()));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <NotificationsScreen
        searchLocation={{lat: 43.36, lon: -80.31}}
        locationQuery={CAMBRIDGE_QUERY}
        persistedForecast={INITIAL_PERSISTED_FORECAST}
        onForecastComplete={jest.fn()}
      />,
    );
  });

  const allTexts = texts(renderer!);
  expect(allTexts).toContain("Tomorrow's Gas Price Forecast");
  expect(allTexts).toContain("Tomorrow's Price Range");
  expect(allTexts).toContain('159.1¢');
  expect(allTexts).toContain('176.1¢');
  // One fetch drives both cards — no second request for the range.
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('shows an error message when the forecast request fails', async () => {
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok: false,
      status: 502,
      json: () => Promise.resolve({detail: 'GasBuddy lookup failed'}),
    }),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <NotificationsScreen
        searchLocation={{lat: 43.36, lon: -80.31}}
        locationQuery={CAMBRIDGE_QUERY}
        persistedForecast={INITIAL_PERSISTED_FORECAST}
        onForecastComplete={jest.fn()}
      />,
    );
  });

  expect(texts(renderer!).join(' ')).toContain('GasBuddy lookup failed');
});

it('refetches when the search location changes', async () => {
  const fetchMock = jest.fn(() => Promise.resolve(forecastResponse()));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <Harness mounted searchLocation={{lat: 43.36, lon: -80.31}} />,
    );
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);

  await act(async () => {
    renderer!.update(
      <Harness mounted searchLocation={{lat: 41.85, lon: -87.65}} />,
    );
  });

  expect(fetchMock).toHaveBeenCalledTimes(2);
  const secondUrl = (fetchMock.mock.calls[1] as unknown[])[0] as string;
  expect(secondUrl).toContain('lat=41.85');
});

it('does not refetch when the same tab is left and revisited with an unchanged location', async () => {
  const fetchMock = jest.fn(() => Promise.resolve(forecastResponse()));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <Harness mounted searchLocation={{lat: 43.36, lon: -80.31}} />,
    );
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);

  // Switch away (unmount) and back (remount) — same searchLocation as
  // before, standing in for the user tapping to another tab and back.
  await act(async () => {
    renderer!.update(
      <Harness mounted={false} searchLocation={{lat: 43.36, lon: -80.31}} />,
    );
  });
  await act(async () => {
    renderer!.update(
      <Harness mounted searchLocation={{lat: 43.36, lon: -80.31}} />,
    );
  });

  expect(fetchMock).toHaveBeenCalledTimes(1);
  // The cached forecast is shown immediately, no loading spinner.
  expect(renderer!.root.findAllByType(ActivityIndicator)).toHaveLength(0);
  expect(texts(renderer!)).toContain('168.9¢');
});

it('refetches on remount if the search location changed while the tab was away', async () => {
  const fetchMock = jest.fn(() => Promise.resolve(forecastResponse()));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <Harness mounted searchLocation={{lat: 43.36, lon: -80.31}} />,
    );
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);

  await act(async () => {
    renderer!.update(
      <Harness mounted={false} searchLocation={{lat: 43.36, lon: -80.31}} />,
    );
  });
  // A new search happened on the Gas tab while Notifications was unmounted.
  await act(async () => {
    renderer!.update(
      <Harness mounted searchLocation={{lat: 41.85, lon: -87.65}} />,
    );
  });

  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it('pulling to refresh re-fetches the forecast for the same location', async () => {
  const fetchMock = jest.fn(() => Promise.resolve(forecastResponse()));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <NotificationsScreen
        searchLocation={{lat: 43.36, lon: -80.31}}
        locationQuery={CAMBRIDGE_QUERY}
        persistedForecast={INITIAL_PERSISTED_FORECAST}
        onForecastComplete={jest.fn()}
      />,
    );
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);

  await act(async () => {
    await renderer!.root
      .findByType(ScrollView)
      .props.refreshControl.props.onRefresh();
  });

  expect(fetchMock).toHaveBeenCalledTimes(2);
  const secondUrl = (fetchMock.mock.calls[1] as unknown[])[0] as string;
  expect(secondUrl).toContain('lat=43.36');
  expect(secondUrl).toContain('lon=-80.31');
});

it('keeps showing the existing forecast, uninterrupted, when a pull-to-refresh fails', async () => {
  const fetchMock: jest.Mock = jest.fn(() =>
    Promise.resolve(forecastResponse()),
  );
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <NotificationsScreen
        searchLocation={{lat: 43.36, lon: -80.31}}
        locationQuery={CAMBRIDGE_QUERY}
        persistedForecast={INITIAL_PERSISTED_FORECAST}
        onForecastComplete={jest.fn()}
      />,
    );
  });

  fetchMock.mockImplementationOnce(() =>
    Promise.resolve({
      ok: false,
      status: 502,
      json: () => Promise.resolve({detail: 'GasBuddy lookup failed'}),
    }),
  );

  await act(async () => {
    await renderer!.root
      .findByType(ScrollView)
      .props.refreshControl.props.onRefresh();
  });

  expect(texts(renderer!)).toContain('168.9¢');
  expect(texts(renderer!).join(' ')).not.toContain('GasBuddy lookup failed');
});
