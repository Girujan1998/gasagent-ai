import React, {useEffect, useRef, useState} from 'react';
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import WebView, {WebViewMessageEvent} from 'react-native-webview';

import {EvStation} from '../api/client';
import {haversineMiles} from '../utils/distance';
import {
  buildEvStationMapData,
  buildEvStationMapHtml,
  EvMapCenter,
} from '../utils/evStationMapHtml';
import EvStationDetailModal from './EvStationDetailModal';

// How far the map has to be panned/zoomed away from the searched location
// before "Search this area" is worth offering — mirrors StationMap's own
// threshold.
const SEARCH_AREA_THRESHOLD_MILES = 0.5;

type Props = {
  stations: EvStation[];
  center: EvMapCenter | null;
  loading: boolean;
  error: string | null;
  // Bumped by the caller to recenter/rezoom the map on `center` — e.g. for
  // a fresh location search — without needing every `center` change to do
  // so, since "Search this area" also changes `center` but must leave the
  // user's current pan/zoom alone.
  recenterSignal: number;
  onSearchArea: (center: EvMapCenter) => void;
  emptyMessage?: string;
};

function EvStationMap({
  stations,
  center,
  loading,
  error,
  recenterSignal,
  onSearchArea,
  emptyMessage = 'No EV chargers found nearby.',
}: Props): React.JSX.Element {
  const [selectedStation, setSelectedStation] = useState<EvStation | null>(
    null,
  );
  const [pendingCenter, setPendingCenter] = useState<EvMapCenter | null>(null);
  const webviewRef = useRef<WebView>(null);

  // The WebView's page is built once, the first time there's real data to
  // show, and never rebuilt after that (see the render guard below).
  // `reflectedRef` tracks which stations/center it currently reflects;
  // later changes — e.g. from "Search this area" — are patched into the
  // already-loaded page via injectJavaScript in the effect below, instead
  // of reloading the whole WebView, which would lose the user's current
  // pan/zoom and flash the map tiles.
  const htmlRef = useRef<string | null>(null);
  const reflectedRef = useRef<{
    stations: EvStation[];
    center: EvMapCenter | null;
  }>({stations: [], center: null});
  // Initialized to the current prop, not some sentinel like 0/-1, so the
  // very first render (which already frames the initial center as part of
  // building htmlRef.current, below) doesn't also fire a redundant recenter.
  const lastRecenterSignalRef = useRef(recenterSignal);

  useEffect(() => {
    setPendingCenter(null);
  }, [center]);

  useEffect(() => {
    if (recenterSignal === lastRecenterSignalRef.current) {
      return;
    }
    lastRecenterSignalRef.current = recenterSignal;
    if (!htmlRef.current || !center) {
      return;
    }
    webviewRef.current?.injectJavaScript(
      `window.recenterMap(${center.lat}, ${center.lon}); true;`,
    );
  }, [recenterSignal, center]);

  useEffect(() => {
    if (
      reflectedRef.current.stations === stations &&
      reflectedRef.current.center === center
    ) {
      // Already reflected — either nothing changed, or this is the same
      // render that just built htmlRef.current fresh with this exact
      // data below, which needs no patch.
      return;
    }
    reflectedRef.current = {stations, center};
    if (!htmlRef.current) {
      // No page loaded yet at all — the render below will build one
      // fresh with this data once it's no longer loading/empty.
      return;
    }
    const dataJson = JSON.stringify(buildEvStationMapData(stations, center));
    webviewRef.current?.injectJavaScript(
      `window.updateMapData(${JSON.stringify(dataJson)}); true;`,
    );
  }, [stations, center]);

  const handleMessage = (event: WebViewMessageEvent) => {
    let message: {type?: string; [key: string]: unknown};
    try {
      message = JSON.parse(event.nativeEvent.data);
    } catch {
      return;
    }

    if (message.type === 'selectStation') {
      const station = stations.find(s => s.station_id === message.stationId);
      if (station) {
        setSelectedStation(station);
      }
      return;
    }

    if (message.type === 'centerChanged') {
      const lat = message.lat;
      const lon = message.lon;
      if (typeof lat !== 'number' || typeof lon !== 'number') {
        return;
      }
      const movedFar =
        center != null &&
        haversineMiles(center.lat, center.lon, lat, lon) >
          SEARCH_AREA_THRESHOLD_MILES;
      setPendingCenter(movedFar ? {lat, lon} : null);
    }
  };

  const handleSearchArea = () => {
    if (pendingCenter) {
      onSearchArea(pendingCenter);
      setPendingCenter(null);
    }
  };

  const zoom = (direction: 'in' | 'out') => {
    webviewRef.current?.injectJavaScript(
      direction === 'in'
        ? 'window.map.zoomIn(); true;'
        : 'window.map.zoomOut(); true;',
    );
  };

  // Only the very first load (nothing to show yet) takes over the whole
  // screen with a spinner. A background refresh — e.g. the fetch kicked
  // off by "Search this area" — keeps showing the already-loaded map
  // with its current (still valid) pins until the new data patches in.
  if (loading && stations.length === 0) {
    return <ActivityIndicator style={styles.spacing} />;
  }

  if (error) {
    return <Text style={[styles.message, styles.spacing]}>⚠️ {error}</Text>;
  }

  if (stations.length === 0) {
    return <Text style={[styles.message, styles.spacing]}>{emptyMessage}</Text>;
  }

  if (htmlRef.current === null) {
    htmlRef.current = buildEvStationMapHtml(
      buildEvStationMapData(stations, center),
    );
    reflectedRef.current = {stations, center};
  }

  return (
    <>
      <View style={styles.container}>
        <WebView
          ref={webviewRef}
          style={styles.map}
          originWhitelist={['*']}
          source={{html: htmlRef.current}}
          onMessage={handleMessage}
          accessibilityLabel="EV charging station map"
        />

        {pendingCenter && (
          <TouchableOpacity
            style={styles.searchAreaButton}
            onPress={handleSearchArea}
            accessibilityLabel="Search this area">
            <Text style={styles.searchAreaText}>Search this area</Text>
          </TouchableOpacity>
        )}

        <View style={styles.zoomControls}>
          <TouchableOpacity
            style={styles.zoomButton}
            onPress={() => zoom('in')}
            accessibilityLabel="Zoom in">
            <Text style={styles.zoomButtonText}>+</Text>
          </TouchableOpacity>
          <View style={styles.zoomDivider} />
          <TouchableOpacity
            style={styles.zoomButton}
            onPress={() => zoom('out')}
            accessibilityLabel="Zoom out">
            <Text style={styles.zoomButtonText}>−</Text>
          </TouchableOpacity>
        </View>
      </View>
      <EvStationDetailModal
        station={selectedStation}
        onClose={() => setSelectedStation(null)}
      />
    </>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  map: {
    flex: 1,
  },
  spacing: {
    marginTop: 24,
  },
  message: {
    fontSize: 14,
    color: '#666',
    textAlign: 'center',
    paddingHorizontal: 24,
  },
  searchAreaButton: {
    position: 'absolute',
    top: 16,
    alignSelf: 'center',
    backgroundColor: '#2e7d32',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 20,
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 1},
    shadowOpacity: 0.25,
    shadowRadius: 4,
    elevation: 4,
  },
  searchAreaText: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '700',
  },
  zoomControls: {
    position: 'absolute',
    right: 16,
    bottom: 16,
    backgroundColor: '#fff',
    borderRadius: 10,
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 1},
    shadowOpacity: 0.2,
    shadowRadius: 4,
    elevation: 4,
    overflow: 'hidden',
  },
  zoomButton: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  zoomButtonText: {
    fontSize: 22,
    fontWeight: '600',
    color: '#333',
  },
  zoomDivider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: '#ddd',
  },
});

export default EvStationMap;
