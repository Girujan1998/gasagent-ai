/**
 * @format
 */

import {it, expect} from '@jest/globals';

import {GasStation} from '../src/api/client';
import {FuelKey} from '../src/config/fuelDisplay';
import {freshnessColor} from '../src/utils/freshness';
import {
  buildStationMapData,
  buildStationMapHtml,
} from '../src/utils/stationMapHtml';

function makeStation(
  overrides: Partial<GasStation> & {station_id: string},
): GasStation {
  return {
    name: overrides.station_id,
    brand: null,
    brand_logo_url: null,
    connected_brand: null,
    connected_brand_logo_url: null,
    address: null,
    latitude: null,
    longitude: null,
    distance_miles: null,
    regular: null,
    midgrade: null,
    premium: null,
    diesel: null,
    star_rating: null,
    ratings_count: null,
    amenities: [],
    ...overrides,
  };
}

const NOW = new Date().toISOString();

it('turns a station with coordinates into a pin with both requested fuel prices', () => {
  const station = makeStation({
    station_id: 'a',
    brand: 'Shell',
    brand_logo_url: 'https://example.com/shell.png',
    latitude: 41.9,
    longitude: -87.6,
    regular: {price: 3.19, formatted_price: '$3.19', last_updated: null},
    premium: {price: 3.79, formatted_price: '$3.79', last_updated: null},
  });

  const data = buildStationMapData([station], 'regular', 'premium', {
    lat: 41.85,
    lon: -87.65,
  });

  expect(data.pins).toEqual([
    {
      id: 'a',
      lat: 41.9,
      lon: -87.6,
      brand: 'Shell',
      logoUrl: 'https://example.com/shell.png',
      prices: [
        {label: 'R', price: '$3.19', color: null},
        {label: 'P', price: '$3.79', color: null},
      ],
      rank: 1,
    },
  ]);
  expect(data.center).toEqual({lat: 41.85, lon: -87.65});
});

const FUEL_KEY_INITIALS: [FuelKey, string][] = [
  ['regular', 'R'],
  ['midgrade', 'M'],
  ['premium', 'P'],
  ['diesel', 'D'],
];

it.each(FUEL_KEY_INITIALS)(
  'labels the %s price with the initial "%s"',
  (key, initial) => {
    const station = makeStation({
      station_id: 'a',
      latitude: 41.9,
      longitude: -87.6,
      [key]: {price: 3.0, formatted_price: '$3.00', last_updated: null},
    });

    const data = buildStationMapData([station], key, key, null);

    expect(data.pins[0].prices[0].label).toBe(initial);
  },
);

it('colors a price by how long ago it was reported, the same way the list view does', () => {
  const station = makeStation({
    station_id: 'a',
    latitude: 41.9,
    longitude: -87.6,
    regular: {price: 3.19, formatted_price: '$3.19', last_updated: NOW},
  });

  const data = buildStationMapData([station], 'regular', 'regular', null);

  expect(data.pins[0].prices[0].color).toBe(freshnessColor(0));
});

it('leaves the color null when a price has no reported time, instead of guessing a freshness', () => {
  const station = makeStation({
    station_id: 'a',
    latitude: 41.9,
    longitude: -87.6,
    regular: {price: 3.19, formatted_price: '$3.19', last_updated: null},
  });

  const data = buildStationMapData([station], 'regular', 'regular', null);

  expect(data.pins[0].prices[0].color).toBeNull();
});

it('ranks the three cheapest stations by the primary fuel price, cheapest first', () => {
  const stations = [
    makeStation({
      station_id: 'third',
      latitude: 41.9,
      longitude: -87.6,
      regular: {price: 3.5, formatted_price: '$3.50', last_updated: null},
    }),
    makeStation({
      station_id: 'cheapest',
      latitude: 41.9,
      longitude: -87.6,
      regular: {price: 2.99, formatted_price: '$2.99', last_updated: null},
    }),
    makeStation({
      station_id: 'unranked-1',
      latitude: 41.9,
      longitude: -87.6,
      regular: {price: 3.6, formatted_price: '$3.60', last_updated: null},
    }),
    makeStation({
      station_id: 'second',
      latitude: 41.9,
      longitude: -87.6,
      regular: {price: 3.1, formatted_price: '$3.10', last_updated: null},
    }),
    makeStation({
      station_id: 'unranked-2',
      latitude: 41.9,
      longitude: -87.6,
      regular: {price: 3.99, formatted_price: '$3.99', last_updated: null},
    }),
  ];

  const data = buildStationMapData(stations, 'regular', 'regular', null);
  const rankById = Object.fromEntries(data.pins.map(p => [p.id, p.rank]));

  expect(rankById).toEqual({
    cheapest: 1,
    second: 2,
    third: 3,
    'unranked-1': null,
    'unranked-2': null,
  });
});

it('ranks by the primary fuel even when a different fuel is shown second', () => {
  const cheaperOnSecondary = makeStation({
    station_id: 'a',
    latitude: 41.9,
    longitude: -87.6,
    regular: {price: 3.5, formatted_price: '$3.50', last_updated: null},
    premium: {price: 3.0, formatted_price: '$3.00', last_updated: null},
  });
  const cheaperOnPrimary = makeStation({
    station_id: 'b',
    latitude: 41.9,
    longitude: -87.6,
    regular: {price: 3.1, formatted_price: '$3.10', last_updated: null},
    premium: {price: 4.5, formatted_price: '$4.50', last_updated: null},
  });

  const data = buildStationMapData(
    [cheaperOnSecondary, cheaperOnPrimary],
    'regular',
    'premium',
    null,
  );

  expect(data.pins.find(p => p.id === 'b')!.rank).toBe(1);
  expect(data.pins.find(p => p.id === 'a')!.rank).toBe(2);
});

it('leaves a station unranked when it has no price for the primary fuel at all', () => {
  const noPrimaryPrice = makeStation({
    station_id: 'a',
    latitude: 41.9,
    longitude: -87.6,
    regular: null,
  });

  const data = buildStationMapData(
    [noPrimaryPrice],
    'regular',
    'premium',
    null,
  );

  expect(data.pins[0].rank).toBeNull();
});

it('has a null logo when the station has no brand logo', () => {
  const station = makeStation({
    station_id: 'a',
    brand_logo_url: null,
    latitude: 41.9,
    longitude: -87.6,
  });

  const data = buildStationMapData([station], 'regular', 'premium', null);

  expect(data.pins[0].logoUrl).toBeNull();
});

it('escapes HTML-sensitive characters in the logo URL so it cannot break out of the src attribute', () => {
  const station = makeStation({
    station_id: 'a',
    brand_logo_url:
      'https://example.com/logo.png?a="><script>alert(1)</script>',
    latitude: 41.9,
    longitude: -87.6,
  });

  const data = buildStationMapData([station], 'regular', 'premium', null);

  expect(data.pins[0].logoUrl).not.toContain('"');
});

it("falls back to the station's name when it has no brand", () => {
  const station = makeStation({
    station_id: 'a',
    brand: null,
    latitude: 41.9,
    longitude: -87.6,
  });
  station.name = 'Independent Fuel Stop';

  const data = buildStationMapData([station], 'regular', 'premium', null);

  expect(data.pins[0].brand).toBe('Independent Fuel Stop');
});

it('escapes HTML-sensitive characters in the brand so a malformed name cannot break the pin markup', () => {
  const station = makeStation({
    station_id: 'a',
    brand: '<b>Shell</b> & "Friends"',
    latitude: 41.9,
    longitude: -87.6,
  });

  const data = buildStationMapData([station], 'regular', 'premium', null);

  expect(data.pins[0].brand).toBe(
    '&lt;b&gt;Shell&lt;/b&gt; &amp; &quot;Friends&quot;',
  );
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

  const data = buildStationMapData(
    [withCoords, noLat, noLon],
    'regular',
    'premium',
    null,
  );

  expect(data.pins.map(p => p.id)).toEqual(['a']);
});

it('falls back to a formatted dollar price when formatted_price is missing', () => {
  const station = makeStation({
    station_id: 'a',
    latitude: 41.9,
    longitude: -87.6,
    regular: {price: 3.5, formatted_price: null, last_updated: null},
  });

  const data = buildStationMapData([station], 'regular', 'premium', null);

  expect(data.pins[0].prices[0].price).toBe('$3.50');
});

it('shows a dash when the requested fuel grade has no price at all', () => {
  const station = makeStation({
    station_id: 'a',
    latitude: 41.9,
    longitude: -87.6,
    regular: null,
  });

  const data = buildStationMapData([station], 'regular', 'premium', null);

  expect(data.pins[0].prices[0].price).toBe('—');
});

it('embeds the pin and center data as HTML the page can parse', () => {
  const html = buildStationMapHtml({
    pins: [
      {
        id: 'a',
        lat: 41.9,
        lon: -87.6,
        brand: 'Shell',
        logoUrl: 'https://example.com/shell.png',
        prices: [
          {label: 'R', price: '$3.19', color: 'rgb(27, 122, 61)'},
          {label: 'P', price: '$3.79', color: null},
        ],
        rank: 1,
      },
    ],
    center: {lat: 41.85, lon: -87.65},
  });

  expect(html).toContain('"id":"a"');
  expect(html).toContain('"label":"R"');
  expect(html).toContain('"price":"$3.19"');
  expect(html).toContain('"color":"rgb(27, 122, 61)"');
  expect(html).toContain('"brand":"Shell"');
  expect(html).toContain('"logoUrl":"https://example.com/shell.png"');
  expect(html).toContain('"rank":1');
  expect(html).toContain('"lat":41.85');
  // Leaflet + OpenStreetMap load with no API key required.
  expect(html).toContain('leaflet');
  expect(html).toContain('tile.openstreetmap.org');
  // The pin markup shows the logo (falling back to a gas-pump icon when
  // there isn't one) alongside both prices, not the brand as text.
  expect(html).toContain('pin-logo');
  expect(html).toContain('pin-price-row');
  expect(html).toContain('pin-price-label');
  expect(html).toContain('handleLogoError');
  // Bubble background reads white (not the old solid blue fill) so the
  // freshness-colored price text stays legible.
  expect(html).toMatch(/\.price-pin\s*{[^}]*background:\s*#fff/);
  // Cheapest/2nd/3rd-cheapest is a labeled flag above the pin, not a
  // colored border — a map-only affordance with no list-view equivalent.
  expect(html).toContain('.flag.rank-1');
  expect(html).toContain('.flag.rank-2');
  expect(html).toContain('.flag.rank-3');
  expect(html).toContain('Cheapest');
  expect(html).toContain('2nd cheapest');
  expect(html).toContain('3rd cheapest');
});

it('embeds a null rank for an unranked pin, for the page-side class logic to act on', () => {
  const html = buildStationMapHtml({
    pins: [
      {
        id: 'a',
        lat: 41.9,
        lon: -87.6,
        brand: 'Shell',
        logoUrl: null,
        prices: [{label: 'R', price: '$3.19', color: null}],
        rank: null,
      },
    ],
    center: null,
  });

  expect(html).toContain('"rank":null');
});

it('never emits a literal </script> from station data, which would break out of the embedding tag', () => {
  // A pin id is attacker/GasBuddy-controlled data as far as this function
  // is concerned — it must not be able to prematurely close the <script>
  // tag it's embedded in.
  const html = buildStationMapHtml({
    pins: [
      {
        id: '</script><script>alert(1)</script>',
        lat: 0,
        lon: 0,
        brand: 'Shell',
        logoUrl: null,
        prices: [{label: 'R', price: '$1.00', color: null}],
        rank: null,
      },
    ],
    center: null,
  });

  const scriptCloseTags = html.match(/<\/script>/g) ?? [];
  // Exactly the two real closing tags (leaflet's <script src> and the
  // inline logic <script>) — none contributed by the malicious pin id.
  expect(scriptCloseTags).toHaveLength(2);
});
