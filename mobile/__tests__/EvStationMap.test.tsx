/**
 * @format
 */

import React from 'react';
import {ActivityIndicator, Modal, Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';
import WebView from 'react-native-webview';
import {mockInjectJavaScript} from '../__mocks__/react-native-webview';

import {EvStation} from '../src/api/client';
import EvStationMap from '../src/components/EvStationMap';

const station: EvStation = {
  station_id: 'a',
  name: 'Downtown Charging Hub',
  network: 'ChargePoint Network',
  network_web: null,
  address: '1 Main St',
  latitude: 41.9,
  longitude: -87.6,
  distance_miles: 1.5,
  phone: null,
  access_hours: null,
  access_code: 'public',
  status_code: 'E',
  level1_count: null,
  level2_count: 2,
  dc_fast_count: null,
  connector_types: ['J1772'],
  date_last_confirmed: null,
};

const CENTER = {lat: 41.85, lon: -87.65};

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

it('shows a spinner while loading, instead of the map', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationMap
        stations={[]}
        center={null}
        loading
        error={null}
        recenterSignal={0}
        onSearchArea={() => {}}
      />,
    );
  });

  expect(renderer!.root.findByType(ActivityIndicator)).toBeTruthy();
  expect(renderer!.root.findAllByType(WebView)).toHaveLength(0);
});

it('shows the error message instead of the map when the search failed', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationMap
        stations={[]}
        center={null}
        loading={false}
        error="Search failed."
        recenterSignal={0}
        onSearchArea={() => {}}
      />,
    );
  });

  expect(joinedTexts(renderer!)).toContain('⚠️ Search failed.');
  expect(renderer!.root.findAllByType(WebView)).toHaveLength(0);
});

it('shows the empty message instead of the map when there are no stations', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationMap
        stations={[]}
        center={null}
        loading={false}
        error={null}
        recenterSignal={0}
        onSearchArea={() => {}}
      />,
    );
  });

  expect(joinedTexts(renderer!)).toContain('No EV chargers found nearby.');
  expect(renderer!.root.findAllByType(WebView)).toHaveLength(0);
});

it('renders a WebView with the station data embedded once results are ready', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationMap
        stations={[station]}
        center={CENTER}
        loading={false}
        error={null}
        recenterSignal={0}
        onSearchArea={() => {}}
      />,
    );
  });

  const webview = renderer!.root.findByType(WebView);
  expect(webview.props.source.html).toContain('"id":"a"');
  // The pin is icon-only — no name/network text embedded per-pin, unlike
  // the gas map's price bubbles.
  expect(webview.props.source.html).not.toContain('Downtown Charging Hub');
  expect(webview.props.source.html).toContain('ev-marker-drop');
});

it('patches new pins into the already-loaded page instead of reloading the whole map when results change, e.g. after "Search this area"', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationMap
        stations={[station]}
        center={CENTER}
        loading={false}
        error={null}
        recenterSignal={0}
        onSearchArea={() => {}}
      />,
    );
  });

  const originalHtml = renderer!.root.findByType(WebView).props.source.html;
  mockInjectJavaScript.mockClear();

  const newStation: EvStation = {...station, station_id: 'b'};
  const newCenter = {lat: 41.86, lon: -87.66};
  await act(async () => {
    renderer!.update(
      <EvStationMap
        stations={[newStation]}
        center={newCenter}
        loading={false}
        error={null}
        recenterSignal={0}
        onSearchArea={() => {}}
      />,
    );
  });

  // The WebView's source HTML is untouched — no page reload, so the
  // user's current pan/zoom on the already-loaded map survives.
  expect(renderer!.root.findByType(WebView).props.source.html).toBe(
    originalHtml,
  );
  // The new data was pushed into the loaded page instead.
  expect(mockInjectJavaScript).toHaveBeenCalledTimes(1);
  const script = mockInjectJavaScript.mock.calls[0][0] as string;
  expect(script).toContain('window.updateMapData');
  expect(script).toContain('\\"id\\":\\"b\\"');
  expect(script).toContain('41.86');
  // A "Search this area" refinement never recenters/rezooms the map.
  expect(mockInjectJavaScript).not.toHaveBeenCalledWith(
    expect.stringContaining('window.recenterMap'),
  );
});

it('recenters and rezooms the map on the new location when recenterSignal changes, e.g. for a fresh search', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationMap
        stations={[station]}
        center={CENTER}
        loading={false}
        error={null}
        recenterSignal={0}
        onSearchArea={() => {}}
      />,
    );
  });

  const originalHtml = renderer!.root.findByType(WebView).props.source.html;
  mockInjectJavaScript.mockClear();

  const newStation: EvStation = {...station, station_id: 'b'};
  const newCenter = {lat: 41.86, lon: -87.66};
  await act(async () => {
    renderer!.update(
      <EvStationMap
        stations={[newStation]}
        center={newCenter}
        loading={false}
        error={null}
        recenterSignal={1}
        onSearchArea={() => {}}
      />,
    );
  });

  // Still no full page reload — recentering is also just an in-place
  // patch to the already-loaded map, not a WebView reload.
  expect(renderer!.root.findByType(WebView).props.source.html).toBe(
    originalHtml,
  );
  expect(mockInjectJavaScript).toHaveBeenCalledWith(
    expect.stringContaining('window.updateMapData'),
  );
  expect(mockInjectJavaScript).toHaveBeenCalledWith(
    `window.recenterMap(${newCenter.lat}, ${newCenter.lon}); true;`,
  );
});

it('does not recenter again on a later data-only change once recenterSignal has already been consumed', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationMap
        stations={[station]}
        center={CENTER}
        loading={false}
        error={null}
        recenterSignal={1}
        onSearchArea={() => {}}
      />,
    );
  });

  mockInjectJavaScript.mockClear();

  const newStation: EvStation = {...station, station_id: 'b'};
  const newCenter = {lat: 41.86, lon: -87.66};
  await act(async () => {
    renderer!.update(
      <EvStationMap
        stations={[newStation]}
        center={newCenter}
        loading={false}
        error={null}
        recenterSignal={1}
        onSearchArea={() => {}}
      />,
    );
  });

  expect(mockInjectJavaScript).not.toHaveBeenCalledWith(
    expect.stringContaining('window.recenterMap'),
  );
});

it('keeps showing the already-loaded map with its current pins while a background refresh is in flight, instead of replacing it with a spinner', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationMap
        stations={[station]}
        center={CENTER}
        loading={false}
        error={null}
        recenterSignal={0}
        onSearchArea={() => {}}
      />,
    );
  });

  // A background refresh (e.g. from "Search this area") sets loading
  // true, but the stations prop stays as the old, still-valid data until
  // the new fetch resolves — the map must stay visible, not get replaced.
  await act(async () => {
    renderer!.update(
      <EvStationMap
        stations={[station]}
        center={CENTER}
        loading
        error={null}
        recenterSignal={0}
        onSearchArea={() => {}}
      />,
    );
  });

  expect(renderer!.root.findAllByType(ActivityIndicator)).toHaveLength(0);
  expect(renderer!.root.findByType(WebView)).toBeTruthy();
});

it('opens the station detail modal for the tapped pin when the page posts a message', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationMap
        stations={[station]}
        center={CENTER}
        loading={false}
        error={null}
        recenterSignal={0}
        onSearchArea={() => {}}
      />,
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
      <EvStationMap
        stations={[station]}
        center={CENTER}
        loading={false}
        error={null}
        recenterSignal={0}
        onSearchArea={() => {}}
      />,
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
      <EvStationMap
        stations={[station]}
        center={CENTER}
        loading={false}
        error={null}
        recenterSignal={0}
        onSearchArea={() => {}}
      />,
    );
  });

  mockInjectJavaScript.mockClear();

  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Zoom in'}).props.onPress();
  });
  expect(mockInjectJavaScript).toHaveBeenCalledWith(
    expect.stringContaining('zoomIn'),
  );
});

it('shows "Search this area" once the map is panned far away, and calls onSearchArea with the new center when pressed', async () => {
  const onSearchArea = jest.fn();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationMap
        stations={[station]}
        center={CENTER}
        loading={false}
        error={null}
        recenterSignal={0}
        onSearchArea={onSearchArea}
      />,
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
});
