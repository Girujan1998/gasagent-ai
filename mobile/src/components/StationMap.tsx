import React, {useEffect, useMemo, useRef, useState} from 'react';
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import WebView, {WebViewMessageEvent} from 'react-native-webview';

import {GasStation} from '../api/client';
import {FuelKey} from '../config/fuelDisplay';
import {haversineMiles} from '../utils/distance';
import {
  buildStationMapData,
  buildStationMapHtml,
  MapCenter,
} from '../utils/stationMapHtml';
import StationDetailModal from './StationDetailModal';

// How far the map has to be panned/zoomed away from the searched location
// before "Search this area" is worth offering — small pans/zooms to look
// around the existing results shouldn't prompt a new search.
const SEARCH_AREA_THRESHOLD_MILES = 0.5;

type Props = {
  stations: GasStation[];
  primaryFuelKey: FuelKey;
  secondaryFuelKey: FuelKey;
  center: MapCenter | null;
  loading: boolean;
  error: string | null;
  onSearchArea: (center: MapCenter) => void;
  emptyMessage?: string;
};

function StationMap({
  stations,
  primaryFuelKey,
  secondaryFuelKey,
  center,
  loading,
  error,
  onSearchArea,
  emptyMessage = 'No stations found nearby.',
}: Props): React.JSX.Element {
  const [selectedStation, setSelectedStation] = useState<GasStation | null>(
    null,
  );
  // Set from the page's centerChanged messages once the map has moved
  // meaningfully away from `center` — cleared below whenever `center`
  // itself changes (a fresh search re-frames the map on its own results).
  const [pendingCenter, setPendingCenter] = useState<MapCenter | null>(null);
  const webviewRef = useRef<WebView>(null);

  useEffect(() => {
    setPendingCenter(null);
  }, [center]);

  // A WebView reloads its whole page whenever `source.html` changes
  // identity, so this must stay referentially stable across re-renders
  // that don't actually change the map (e.g. the list's loadingMore
  // toggling) — memoized on the same data the page is built from.
  const html = useMemo(
    () =>
      buildStationMapHtml(
        buildStationMapData(stations, primaryFuelKey, secondaryFuelKey, center),
      ),
    [stations, primaryFuelKey, secondaryFuelKey, center],
  );

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

  if (loading) {
    return <ActivityIndicator style={styles.spacing} />;
  }

  if (error) {
    return <Text style={[styles.message, styles.spacing]}>⚠️ {error}</Text>;
  }

  if (stations.length === 0) {
    return <Text style={[styles.message, styles.spacing]}>{emptyMessage}</Text>;
  }

  return (
    <>
      <View style={styles.container}>
        <WebView
          ref={webviewRef}
          style={styles.map}
          originWhitelist={['*']}
          source={{html}}
          onMessage={handleMessage}
          accessibilityLabel="Gas station price map"
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
      <StationDetailModal
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
    backgroundColor: '#1565c0',
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

export default StationMap;
