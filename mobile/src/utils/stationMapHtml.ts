import {GasStation} from '../api/client';
import {FUEL_INITIALS, FuelKey, fuelByKey} from '../config/fuelDisplay';
import {freshnessColor} from './freshness';
import {minutesSince} from './time';

export type MapPinPrice = {
  label: string;
  price: string;
  // A CSS color string when the price has an age to grade freshness by,
  // null when it doesn't (the pin then just uses its default text color)
  // — mirrors StationCard's PriceColumn, which highlights only when
  // last_updated is known.
  color: string | null;
};
export type MapPin = {
  id: string;
  lat: number;
  lon: number;
  brand: string;
  logoUrl: string | null;
  prices: MapPinPrice[];
  // 1st/2nd/3rd cheapest by primaryFuelKey among the pinned stations, map
  // view only — null otherwise (including for stations without a price for
  // that fuel, which can't be ranked at all).
  rank: 1 | 2 | 3 | null;
};
export type MapCenter = {lat: number; lon: number};
export type StationMapData = {pins: MapPin[]; center: MapCenter | null};

function hasCoordinates(
  station: GasStation,
): station is GasStation & {latitude: number; longitude: number} {
  return station.latitude != null && station.longitude != null;
}

function formatPrice(station: GasStation, key: FuelKey): string {
  const fuel = fuelByKey(station, key);
  if (fuel?.formatted_price) {
    return fuel.formatted_price;
  }
  if (fuel?.price != null) {
    return `$${fuel.price.toFixed(2)}`;
  }
  return '—';
}

function pinPrice(station: GasStation, key: FuelKey): MapPinPrice {
  const fuel = fuelByKey(station, key);
  const minutesAgo = minutesSince(fuel?.last_updated);
  return {
    label: FUEL_INITIALS[key],
    price: formatPrice(station, key),
    color: minutesAgo != null ? freshnessColor(minutesAgo) : null,
  };
}

// The brand ends up concatenated directly into a pin's HTML on the JS side
// (see buildStationMapHtml), so it's escaped here — once, at the source —
// rather than trusting every place that touches it later not to break the
// markup on an unusual station name.
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// The three cheapest stations by primaryFuelKey's raw price — ties keep
// array order, and a station with no price for that fuel can't be ranked
// at all (rather than sorting it as if it were free).
function rankByPrimaryPrice(
  stations: GasStation[],
  primaryFuelKey: FuelKey,
): Map<string, 1 | 2 | 3> {
  const priced = stations
    .map(station => ({
      id: station.station_id,
      price: fuelByKey(station, primaryFuelKey)?.price ?? null,
    }))
    .filter(
      (entry): entry is {id: string; price: number} => entry.price != null,
    )
    .sort((a, b) => a.price - b.price);

  const ranks = new Map<string, 1 | 2 | 3>();
  priced.slice(0, 3).forEach((entry, index) => {
    ranks.set(entry.id, (index + 1) as 1 | 2 | 3);
  });
  return ranks;
}

// Stations without coordinates (GasBuddy occasionally omits them) can't be
// placed on the map, so they're silently dropped here rather than shown in
// the list — there's no pin position to give them.
export function buildStationMapData(
  stations: GasStation[],
  primaryFuelKey: FuelKey,
  secondaryFuelKey: FuelKey,
  center: MapCenter | null,
): StationMapData {
  const pinnedStations = stations.filter(hasCoordinates);
  const ranks = rankByPrimaryPrice(pinnedStations, primaryFuelKey);

  const pins = pinnedStations.map(station => ({
    id: station.station_id,
    lat: station.latitude,
    lon: station.longitude,
    brand: escapeHtml(station.brand || station.name),
    logoUrl: station.brand_logo_url ? escapeHtml(station.brand_logo_url) : null,
    prices: [
      pinPrice(station, primaryFuelKey),
      pinPrice(station, secondaryFuelKey),
    ],
    rank: ranks.get(station.station_id) ?? null,
  }));
  return {pins, center};
}

// JSON.stringify never escapes `<`, so a value containing the literal
// sequence `</script>` (e.g. an unusual station id) would otherwise close
// the embedding <script> tag early and break the page. Escaping every `<`
// neutralizes that regardless of where it appears in the data.
function escapeForInlineScript(json: string): string {
  return json.replace(/</g, '\\u003c');
}

// Renders a self-contained Leaflet + OpenStreetMap page (no API key
// required) into a WebView. Panning, zooming, and tapping a pin are all
// handled by this embedded page's own JavaScript — none of it calls back
// into the app to fetch more stations on its own. The one exception is the
// native "Search this area" button (driven by the centerChanged messages
// below): that's a deliberate, single, user-initiated request, not
// something this page triggers by itself.
export function buildStationMapHtml(data: StationMapData): string {
  const dataJson = escapeForInlineScript(JSON.stringify(data));

  return `<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  html, body, #map { height: 100%; margin: 0; padding: 0; background: #eef1f4; }
  .marker-stack {
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  .price-pin {
    display: flex;
    align-items: center;
    background: #fff;
    /* Default price color when a price has no freshness color of its own
       — matches StationCard's own default price color. */
    color: #1565c0;
    font-family: -apple-system, sans-serif;
    padding: 4px 10px 4px 4px;
    border-radius: 14px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.35);
    border: 2px solid #eee;
  }
  /* Map-only cheapest/2nd/3rd-cheapest indicator (by the selected primary
     fuel) — list view has no equivalent. A small flag above the pin
     rather than a colored border, so it reads as "cheapest" without
     relying on the viewer recognizing medal colors. */
  .flag {
    display: flex;
    align-items: center;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 6px;
    margin-bottom: 4px;
    white-space: nowrap;
    position: relative;
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
  }
  /* A small pointer tying the flag back to its pin — currentColor picks
     up each rank's own color set below, matching the flag's background. */
  .flag::after {
    content: '';
    position: absolute;
    bottom: -4px;
    left: 50%;
    transform: translateX(-50%);
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 4px solid currentColor;
  }
  .flag span { color: #fff; }
  .flag.rank-1 { background: #d4af37; color: #d4af37; }
  .flag.rank-2 { background: #71797e; color: #71797e; }
  .flag.rank-3 { background: #b5651d; color: #b5651d; }
  .pin-logo {
    width: 22px;
    height: 22px;
    border-radius: 6px;
    margin-right: 6px;
    flex-shrink: 0;
    background: #f2f2f2;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    font-size: 13px;
  }
  .pin-logo img {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  .pin-prices {
    display: flex;
    flex-direction: column;
    line-height: 1.2;
  }
  .pin-price-row {
    font-size: 12px;
    font-weight: 700;
    white-space: nowrap;
  }
  .pin-price-label {
    color: #888;
    font-weight: 600;
    margin-right: 3px;
  }
  .center-pin {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: #c62828;
    border: 2px solid #fff;
    box-shadow: 0 1px 4px rgba(0,0,0,0.35);
  }
</style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  var DATA = ${dataJson};
  // Exposed globally so the native side can drive zoom via
  // WebView.injectJavaScript (window.map.zoomIn()/zoomOut()) without a
  // round-trip through postMessage.
  var map = L.map('map', {zoomControl: false, attributionControl: false});
  window.map = map;
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
  }).addTo(map);

  var bounds = [];

  if (DATA.center) {
    L.marker([DATA.center.lat, DATA.center.lon], {
      icon: L.divIcon({
        className: '',
        html: '<div class="center-pin"></div>',
        iconSize: [14, 14],
      }),
      interactive: false,
    }).addTo(map);
    bounds.push([DATA.center.lat, DATA.center.lon]);
  }

  // Falls back to a gas-pump icon (matching the app's own BrandLogo
  // fallback) rather than the brand name — the logo is what's meant to be
  // shown here, not text standing in for it. this.parentNode is always
  // the fixed-size .pin-logo box, so removing the broken <img> and
  // showing the emoji next to it is enough; nothing needs re-measuring.
  window.handleLogoError = function (img) {
    img.style.display = 'none';
    img.parentNode.textContent = '⛽';
  };

  function priceRowHtml(price) {
    var style = price.color ? ' style="color:' + price.color + '"' : '';
    return (
      '<div class="pin-price-row"' +
      style +
      '><span class="pin-price-label">' +
      price.label +
      '</span>' +
      price.price +
      '</div>'
    );
  }

  var RANK_LABELS = {1: 'Cheapest', 2: '2nd cheapest', 3: '3rd cheapest'};

  function flagHtml(rank) {
    if (!rank) {
      return '';
    }
    return (
      '<div class="flag rank-' +
      rank +
      '"><span>' +
      RANK_LABELS[rank] +
      '</span></div>'
    );
  }

  function pinHtml(pin) {
    var logo = pin.logoUrl
      ? '<img src="' +
        pin.logoUrl +
        '" onerror="handleLogoError(this)" alt="' +
        pin.brand +
        '" />'
      : '⛽';
    return (
      '<div class="marker-stack">' +
      flagHtml(pin.rank) +
      '<div class="price-pin"><div class="pin-logo">' +
      logo +
      '</div><div class="pin-prices">' +
      pin.prices.map(priceRowHtml).join('') +
      '</div></div>' +
      '</div>'
    );
  }

  DATA.pins.forEach(function (pin) {
    var marker = L.marker([pin.lat, pin.lon], {
      icon: L.divIcon({
        className: '',
        html: pinHtml(pin),
        iconSize: null,
      }),
    }).addTo(map);
    marker.on('click', function () {
      window.ReactNativeWebView.postMessage(
        JSON.stringify({type: 'selectStation', stationId: pin.id}),
      );
    });
    bounds.push([pin.lat, pin.lon]);
  });

  // The initial fitBounds/setView below fires its own moveend — that's
  // framing the search results, not the user moving the map, so it must
  // not be reported as one. Skipping exactly the first occurrence (rather
  // than a timer) is safe regardless of whether Leaflet animates it.
  var skipNextMoveEnd = true;
  map.on('moveend', function () {
    if (skipNextMoveEnd) {
      skipNextMoveEnd = false;
      return;
    }
    var c = map.getCenter();
    window.ReactNativeWebView.postMessage(
      JSON.stringify({type: 'centerChanged', lat: c.lat, lon: c.lng}),
    );
  });

  if (bounds.length > 1) {
    map.fitBounds(bounds, {padding: [40, 40]});
  } else if (bounds.length === 1) {
    map.setView(bounds[0], 13);
  } else {
    map.setView([0, 0], 2);
  }
</script>
</body>
</html>`;
}
