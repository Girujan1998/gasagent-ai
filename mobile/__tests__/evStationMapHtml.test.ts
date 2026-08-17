/**
 * @format
 */

import {it, expect} from '@jest/globals';

import {EvStation} from '../src/api/client';
import {
  buildEvStationMapData,
  buildEvStationMapHtml,
} from '../src/utils/evStationMapHtml';

function makeStation(
  overrides: Partial<EvStation> & {station_id: string},
): EvStation {
  return {
    name: overrides.station_id,
    network: null,
    network_web: null,
    address: null,
    latitude: null,
    longitude: null,
    distance_miles: null,
    phone: null,
    access_hours: null,
    access_code: null,
    status_code: null,
    level1_count: null,
    level2_count: null,
    dc_fast_count: null,
    connector_types: [],
    date_last_confirmed: null,
    ...overrides,
  };
}

it('turns a station with coordinates into a pin with just its id and location', () => {
  const station = makeStation({
    station_id: 'a',
    name: 'Downtown Charging Hub',
    network: 'ChargePoint Network',
    latitude: 41.9,
    longitude: -87.6,
  });

  const data = buildEvStationMapData([station], {lat: 41.85, lon: -87.65});

  // No name/network/etc — the pin is icon-only, so the detail modal (which
  // looks the full station up by id from the app's own station list) is
  // the only place that text is shown.
  expect(data.pins).toEqual([{id: 'a', lat: 41.9, lon: -87.6}]);
  expect(data.center).toEqual({lat: 41.85, lon: -87.65});
});

it('drops stations that have no coordinates, since they have nowhere to be pinned', () => {
  const withCoords = makeStation({
    station_id: 'a',
    latitude: 41.9,
    longitude: -87.6,
  });
  const noLat = makeStation({
    station_id: 'b',
    latitude: null,
    longitude: -87.6,
  });
  const noLon = makeStation({station_id: 'c', latitude: 41.9, longitude: null});

  const data = buildEvStationMapData([withCoords, noLat, noLon], null);

  expect(data.pins.map(p => p.id)).toEqual(['a']);
});

it('embeds the pin and center data as HTML the page can parse', () => {
  const html = buildEvStationMapHtml({
    pins: [{id: 'a', lat: 41.9, lon: -87.6}],
    center: {lat: 41.85, lon: -87.65},
  });

  expect(html).toContain('"id":"a"');
  expect(html).toContain('"lat":41.85');
  // Leaflet + OpenStreetMap load with no API key required, same as the gas
  // map.
  expect(html).toContain('leaflet');
  expect(html).toContain('tile.openstreetmap.org');
  // A pin-shaped marker (classic teardrop) with just the charging icon —
  // no name/network text bubble like the gas map's price pins.
  expect(html).toContain('ev-marker-drop');
  expect(html).toContain('⚡');
  // The teardrop's point (not its visual center) is anchored to the
  // station's coordinate, so iconAnchor must be the bottom-center of the
  // icon box, matching iconSize.
  expect(html).toMatch(/iconSize:\s*\[30,\s*37\]/);
  expect(html).toMatch(/iconAnchor:\s*\[15,\s*37\]/);
  // Exposed so the native side can patch in new pins/center later (e.g.
  // after "Search this area") without reloading the page.
  expect(html).toContain('window.updateMapData');
  // Exposed so the native side can re-frame the map on a fresh search's
  // location, at the same fixed "slightly zoomed in" level as the initial
  // load, without reloading the page.
  expect(html).toContain('window.recenterMap');
  expect(html).toMatch(/map\.setView\(\[lat, lon\], 13\)/);
});

it('centers on the searched location at a fixed zoom, rather than fitting bounds to every pin', () => {
  // A 30km search radius can spread pins far apart — fitBounds()ing to all
  // of them (like the gas map does) would zoom out to fit the whole
  // radius. The EV map instead always frames the searched location itself.
  const html = buildEvStationMapHtml({
    pins: [
      {id: 'a', lat: 41.9, lon: -87.6},
      {id: 'b', lat: 42.5, lon: -88.9},
      {id: 'c', lat: 41.2, lon: -87.0},
    ],
    center: {lat: 41.85, lon: -87.65},
  });

  // fitBounds still exists as a fallback for the (normally unreachable)
  // case where there's no center at all, but this locks in that the
  // center-based setView is checked first, so it always wins whenever a
  // center is present, however many/far-flung the pins are.
  expect(html).toMatch(
    /if \(DATA\.center\) \{\s*map\.setView\(\[DATA\.center\.lat, DATA\.center\.lon\], 13\);\s*\} else if/,
  );
});

it('never emits a literal </script> from station data, which would break out of the embedding tag', () => {
  const html = buildEvStationMapHtml({
    pins: [{id: '</script><script>alert(1)</script>', lat: 0, lon: 0}],
    center: null,
  });

  const scriptCloseTags = html.match(/<\/script>/g) ?? [];
  // Exactly the two real closing tags (leaflet's <script src> and the
  // inline logic <script>) — none contributed by the malicious pin id,
  // even though it's still embedded in the inline JSON data blob.
  expect(scriptCloseTags).toHaveLength(2);
});
