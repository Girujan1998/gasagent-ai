import {EvStation} from '../api/client';
import {networkLogoUrl} from './evConnectors';

export type EvMapPin = {
  id: string;
  lat: number;
  lon: number;
  logoUrl: string | null;
};
export type EvMapCenter = {lat: number; lon: number};
export type EvStationMapData = {pins: EvMapPin[]; center: EvMapCenter | null};

function hasCoordinates(
  station: EvStation,
): station is EvStation & {latitude: number; longitude: number} {
  return station.latitude != null && station.longitude != null;
}

// A pin's logo URL ends up concatenated directly into an <img src="...">
// on the JS side (see buildEvStationMapHtml), so it's escaped here — once,
// at the source — the same way stationMapHtml.ts escapes a gas station's
// brand_logo_url.
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Stations without coordinates can't be placed on the map, so they're
// silently dropped here rather than shown in the list — mirrors
// stationMapHtml.ts's own handling of the same gap in the gas-price
// lookup's data.
export function buildEvStationMapData(
  stations: EvStation[],
  center: EvMapCenter | null,
): EvStationMapData {
  const pinnedStations = stations.filter(hasCoordinates);

  const pins = pinnedStations.map(station => {
    const logoUrl = networkLogoUrl(station.network_web);
    return {
      id: station.station_id,
      lat: station.latitude,
      lon: station.longitude,
      logoUrl: logoUrl ? escapeHtml(logoUrl) : null,
    };
  });
  return {pins, center};
}

// JSON.stringify never escapes `<`, so a value containing the literal
// sequence `</script>` (e.g. an unusual station id) would otherwise close
// the embedding <script> tag early and break the page.
function escapeForInlineScript(json: string): string {
  return json.replace(/</g, '\\u003c');
}

// Renders a self-contained Leaflet + OpenStreetMap page (no API key
// required) into a WebView — the EV equivalent of stationMapHtml.ts's
// buildStationMapHtml. Pins are a plain teardrop marker with just the
// charging icon (no name/network text bubble) so the marker's tip points
// exactly at the station's location — tapping a pin opens the full detail
// in a modal instead.
//
// The page also exposes `window.updateMapData(dataJson)` so the native
// side (see EvStationMap.tsx) can patch in new pins/center after this HTML
// has already loaded — e.g. after "Search this area" — without reloading
// the whole page, which would lose the user's current pan/zoom and flash
// the map tiles. Only the initial load frames the view (setView/
// fitBounds); updateMapData never touches it.
export function buildEvStationMapHtml(data: EvStationMapData): string {
  const dataJson = escapeForInlineScript(JSON.stringify(data));

  return `<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>
  html, body, #map { height: 100%; margin: 0; padding: 0; background: #eef1f4; }
  /* A classic map-pin teardrop: a square rotated 45deg with three rounded
     corners leaves the fourth (bottom-left, pre-rotation) as a sharp point
     — that point is what actually marks the station's coordinate. */
  .ev-marker {
    position: relative;
    width: 30px;
    height: 37px;
  }
  .ev-marker-drop {
    position: absolute;
    top: 0;
    left: 0;
    width: 30px;
    height: 30px;
    border-radius: 50% 50% 50% 0;
    background: #2e7d32;
    border: 2px solid #fff;
    transform: rotate(-45deg);
    box-shadow: 0 2px 5px rgba(0,0,0,0.4);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .ev-marker-icon {
    transform: rotate(45deg);
    font-size: 15px;
    line-height: 1;
    width: 18px;
    height: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    border-radius: 4px;
  }
  .ev-marker-icon img {
    width: 100%;
    height: 100%;
    object-fit: contain;
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

  // Falls back to the bolt emoji (no logo reported, or the image failed to
  // load) rather than leaving the pin blank.
  window.handleEvLogoError = function (img) {
    img.style.display = 'none';
    img.parentNode.textContent = '⚡';
  };

  function pinHtml(pin) {
    var icon = pin.logoUrl
      ? '<img src="' + pin.logoUrl + '" onerror="handleEvLogoError(this)" alt="" />'
      : '⚡';
    return (
      '<div class="ev-marker"><div class="ev-marker-drop">' +
      '<span class="ev-marker-icon">' + icon + '</span></div></div>'
    );
  }

  var stationMarkers = [];
  var centerMarker = null;

  function setCenterMarker(center) {
    if (centerMarker) {
      map.removeLayer(centerMarker);
      centerMarker = null;
    }
    if (center) {
      centerMarker = L.marker([center.lat, center.lon], {
        icon: L.divIcon({
          className: '',
          html: '<div class="center-pin"></div>',
          iconSize: [14, 14],
        }),
        interactive: false,
      }).addTo(map);
    }
  }

  function setStationPins(pins) {
    stationMarkers.forEach(function (marker) {
      map.removeLayer(marker);
    });
    stationMarkers = pins.map(function (pin) {
      var marker = L.marker([pin.lat, pin.lon], {
        icon: L.divIcon({
          className: '',
          html: pinHtml(pin),
          iconSize: [30, 37],
          // Bottom-center of the icon box — where the teardrop's point
          // sits — so the marker's tip lands exactly on the station's
          // coordinate, not the icon's visual center.
          iconAnchor: [15, 37],
        }),
      }).addTo(map);
      marker.on('click', function () {
        window.ReactNativeWebView.postMessage(
          JSON.stringify({type: 'selectStation', stationId: pin.id}),
        );
      });
      return marker;
    });
  }

  // Patches in new pins/center without touching the map's current pan or
  // zoom — the native side calls this (via injectJavaScript) for any data
  // change after the initial load, e.g. "Search this area", so refining
  // the search only refreshes the points shown, not the whole map.
  window.updateMapData = function (dataJson) {
    var data = JSON.parse(dataJson);
    setCenterMarker(data.center);
    setStationPins(data.pins);
  };

  // Re-frames the map on a new searched location — for a fresh search via
  // the search bar (not "Search this area", which calls updateMapData
  // above instead and deliberately leaves the current view alone).
  window.recenterMap = function (lat, lon) {
    skipNextMoveEnd = true;
    map.setView([lat, lon], 13);
  };

  setCenterMarker(DATA.center);
  setStationPins(DATA.pins);

  // The initial fitBounds/setView below fires its own moveend — that's
  // framing the search results, not the user moving the map, so it must
  // not be reported as one. Skipping exactly the first occurrence (rather
  // than a timer) is safe regardless of whether Leaflet animates it. Also
  // reused by recenterMap above, for the same reason.
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

  // Unlike the gas map, this never zooms out to frame every pin — a 30km
  // search radius can span far more ground than a single screen should
  // show at once. It stays centered and slightly zoomed on the actual
  // searched location instead, regardless of how many stations were
  // found or how far the farthest ones are. This only ever runs once, at
  // initial load — updateMapData deliberately never calls setView/
  // fitBounds, so later data patches leave the user's pan/zoom alone.
  if (DATA.center) {
    map.setView([DATA.center.lat, DATA.center.lon], 13);
  } else if (DATA.pins.length > 1) {
    map.fitBounds(
      DATA.pins.map(function (pin) {
        return [pin.lat, pin.lon];
      }),
      {padding: [40, 40]},
    );
  } else if (DATA.pins.length === 1) {
    map.setView([DATA.pins[0].lat, DATA.pins[0].lon], 13);
  } else {
    map.setView([0, 0], 2);
  }
</script>
</body>
</html>`;
}
