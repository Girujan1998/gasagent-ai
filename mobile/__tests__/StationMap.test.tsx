/**
 * @format
 */

import React from 'react';
import {ActivityIndicator, Modal, Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';
import WebView from 'react-native-webview';
// Imported from the mock's own path (not the bare specifier) so this
// resolves at the type level too — tsc has no notion of Jest's automatic
// mock substitution, so `mockInjectJavaScript` doesn't exist on the real
// package's types. Both imports resolve to the same file on disk, so this
// is still the same singleton the component's WebView ref uses.
import {mockInjectJavaScript} from '../__mocks__/react-native-webview';

import {GasStation} from '../src/api/client';
import StationMap from '../src/components/StationMap';
import {FavoritesProvider} from '../src/store/FavoritesContext';

const station: GasStation = {
  station_id: 'a',
  name: 'Test Station',
  brand: 'Shell',
  brand_logo_url: 'https://example.com/shell.png',
  connected_brand: null,
  connected_brand_logo_url: null,
  address: '1 Main St',
  latitude: 41.9,
  longitude: -87.6,
  distance_miles: 1.5,
  regular: {price: 3.19, formatted_price: '$3.19', last_updated: null},
  midgrade: null,
  premium: {price: 3.79, formatted_price: '$3.79', last_updated: null},
  diesel: null,
  star_rating: null,
  ratings_count: null,
  amenities: [],
};

const CENTER = {lat: 41.85, lon: -87.65};

// Mirrors each Text node's children joined into one string — a Text like
// `⚠️ {error}` renders as two separate children, not one string.
function joinedTexts(renderer: ReactTestRenderer): string[] {
  return renderer.root.findAllByType(Text).map(node =>
    ([] as unknown[])
      .concat(node.props.children)
      .filter(value => typeof value === 'string')
      .join(''),
  );
}

function postMessage(
  webview: ReturnType<ReactTestRenderer['root']['findByType']>,
  message: object,
) {
  return act(async () => {
    webview.props.onMessage({nativeEvent: {data: JSON.stringify(message)}});
  });
}

// Reads a given pin's embedded "rank" value out of the rendered HTML —
// non-greedy so it stops at that pin's own field, not a later pin's.
function rankFor(html: string, stationId: string): string | undefined {
  return html.match(
    new RegExp(`"id":"${stationId}"[\\s\\S]*?"rank":(null|\\d)`),
  )?.[1];
}

it('shows a spinner while loading, instead of the map', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationMap
          stations={[]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={null}
          loading
          error={null}
          onSearchArea={() => {}}
        />
      </FavoritesProvider>,
    );
  });

  expect(renderer!.root.findByType(ActivityIndicator)).toBeTruthy();
  expect(renderer!.root.findAllByType(WebView)).toHaveLength(0);
});

it('shows the error message instead of the map when the search failed', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationMap
          stations={[]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={null}
          loading={false}
          error="Search failed."
          onSearchArea={() => {}}
        />
      </FavoritesProvider>,
    );
  });

  expect(joinedTexts(renderer!)).toContain('⚠️ Search failed.');
  expect(renderer!.root.findAllByType(WebView)).toHaveLength(0);
});

it('shows the empty message instead of the map when there are no stations', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationMap
          stations={[]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={null}
          loading={false}
          error={null}
          onSearchArea={() => {}}
          emptyMessage="No stations match the selected brand filters."
        />
      </FavoritesProvider>,
    );
  });

  expect(joinedTexts(renderer!)).toContain(
    'No stations match the selected brand filters.',
  );
  expect(renderer!.root.findAllByType(WebView)).toHaveLength(0);
});

it('renders a WebView with the station data embedded once results are ready', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationMap
          stations={[station]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={CENTER}
          loading={false}
          error={null}
          onSearchArea={() => {}}
        />
      </FavoritesProvider>,
    );
  });

  const webview = renderer!.root.findByType(WebView);
  expect(webview.props.source.html).toContain('"id":"a"');
  // Both the primary (Regular) and secondary (Premium) prices, each
  // labeled with its fuel grade's initial — matching list view's two
  // price columns.
  expect(webview.props.source.html).toContain('"label":"R"');
  expect(webview.props.source.html).toContain('"price":"$3.19"');
  expect(webview.props.source.html).toContain('"label":"P"');
  expect(webview.props.source.html).toContain('"price":"$3.79"');
  expect(webview.props.source.html).toContain('"brand":"Shell"');
  expect(webview.props.source.html).toContain(
    '"logoUrl":"https://example.com/shell.png"',
  );
  // The only station shown is trivially the cheapest.
  expect(webview.props.source.html).toContain('"rank":1');
});

it('ranks the cheapest of several stations, a map-only affordance not shown in list view', async () => {
  const cheap: GasStation = {
    ...station,
    station_id: 'cheap',
    regular: {price: 2.5, formatted_price: '$2.50', last_updated: null},
  };
  const pricier: GasStation = {
    ...station,
    station_id: 'pricier',
    regular: {price: 4.5, formatted_price: '$4.50', last_updated: null},
  };

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationMap
          stations={[pricier, cheap]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={CENTER}
          loading={false}
          error={null}
          onSearchArea={() => {}}
        />
      </FavoritesProvider>,
    );
  });

  const html = renderer!.root.findByType(WebView).props.source.html;
  expect(rankFor(html, 'cheap')).toBe('1');
  expect(rankFor(html, 'pricier')).toBe('2');
});

it("colors each price by how long ago it was reported, the same way list view's cards do", async () => {
  const stationWithFreshPrice: GasStation = {
    ...station,
    regular: {
      price: 3.19,
      formatted_price: '$3.19',
      last_updated: new Date().toISOString(),
    },
  };

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationMap
          stations={[stationWithFreshPrice]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={CENTER}
          loading={false}
          error={null}
          onSearchArea={() => {}}
        />
      </FavoritesProvider>,
    );
  });

  const webview = renderer!.root.findByType(WebView);
  // A fresh (just-reported) price gets a color; premium here has no
  // last_updated at all, so it stays uncolored rather than guessing.
  expect(webview.props.source.html).toContain(
    '"label":"R","price":"$3.19","color":"rgb(',
  );
  expect(webview.props.source.html).toContain(
    '"label":"P","price":"$3.79","color":null',
  );
});

it('opens the station detail modal for the tapped pin when the page posts a message', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationMap
          stations={[station]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={CENTER}
          loading={false}
          error={null}
          onSearchArea={() => {}}
        />
      </FavoritesProvider>,
    );
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);

  const webview = renderer!.root.findByType(WebView);
  await postMessage(webview, {type: 'selectStation', stationId: 'a'});

  expect(renderer!.root.findByType(Modal).props.visible).toBe(true);
});

it('ignores a message for a station id that is not in the current results', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationMap
          stations={[station]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={CENTER}
          loading={false}
          error={null}
          onSearchArea={() => {}}
        />
      </FavoritesProvider>,
    );
  });

  const webview = renderer!.root.findByType(WebView);
  await postMessage(webview, {
    type: 'selectStation',
    stationId: 'does-not-exist',
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);
});

it('pressing the zoom buttons drives the embedded Leaflet map directly, not a re-render', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationMap
          stations={[station]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={CENTER}
          loading={false}
          error={null}
          onSearchArea={() => {}}
        />
      </FavoritesProvider>,
    );
  });

  mockInjectJavaScript.mockClear();

  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Zoom in'}).props.onPress();
  });
  expect(mockInjectJavaScript).toHaveBeenCalledWith(
    expect.stringContaining('zoomIn'),
  );

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Zoom out'})
      .props.onPress();
  });
  expect(mockInjectJavaScript).toHaveBeenCalledWith(
    expect.stringContaining('zoomOut'),
  );
});

it('does not show "Search this area" until the map is reported to have moved meaningfully', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationMap
          stations={[station]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={CENTER}
          loading={false}
          error={null}
          onSearchArea={() => {}}
        />
      </FavoritesProvider>,
    );
  });

  expect(
    renderer!.root.findAllByProps(
      {accessibilityLabel: 'Search this area'},
      {deep: false},
    ),
  ).toHaveLength(0);

  const webview = renderer!.root.findByType(WebView);

  // A tiny nudge — well within the "just looking around" threshold —
  // should not surface the button.
  await postMessage(webview, {
    type: 'centerChanged',
    lat: CENTER.lat + 0.0001,
    lon: CENTER.lon,
  });
  expect(
    renderer!.root.findAllByProps(
      {accessibilityLabel: 'Search this area'},
      {deep: false},
    ),
  ).toHaveLength(0);
});

it('shows "Search this area" once the map is panned far away, and calls onSearchArea with the new center when pressed', async () => {
  const onSearchArea = jest.fn();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationMap
          stations={[station]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={CENTER}
          loading={false}
          error={null}
          onSearchArea={onSearchArea}
        />
      </FavoritesProvider>,
    );
  });

  const webview = renderer!.root.findByType(WebView);
  const farAway = {lat: CENTER.lat + 5, lon: CENTER.lon + 5};
  await postMessage(webview, {type: 'centerChanged', ...farAway});

  const button = renderer!.root.findByProps({
    accessibilityLabel: 'Search this area',
  });

  await act(async () => {
    button.props.onPress();
  });

  expect(onSearchArea).toHaveBeenCalledWith(farAway);

  // Pressed once — it shouldn't linger asking to be pressed again for the
  // same move.
  expect(
    renderer!.root.findAllByProps(
      {accessibilityLabel: 'Search this area'},
      {deep: false},
    ),
  ).toHaveLength(0);
});

it('hides "Search this area" again once a fresh search changes the center prop', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationMap
          stations={[station]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={CENTER}
          loading={false}
          error={null}
          onSearchArea={() => {}}
        />
      </FavoritesProvider>,
    );
  });

  const webview = renderer!.root.findByType(WebView);
  await postMessage(webview, {
    type: 'centerChanged',
    lat: CENTER.lat + 5,
    lon: CENTER.lon + 5,
  });
  expect(
    renderer!.root.findAllByProps(
      {accessibilityLabel: 'Search this area'},
      {deep: false},
    ),
  ).toHaveLength(1);

  await act(async () => {
    renderer!.update(
      <FavoritesProvider>
        <StationMap
          stations={[station]}
          primaryFuelKey="regular"
          secondaryFuelKey="premium"
          center={{lat: CENTER.lat + 5, lon: CENTER.lon + 5}}
          loading={false}
          error={null}
          onSearchArea={() => {}}
        />
      </FavoritesProvider>,
    );
  });

  expect(
    renderer!.root.findAllByProps(
      {accessibilityLabel: 'Search this area'},
      {deep: false},
    ),
  ).toHaveLength(0);
});
