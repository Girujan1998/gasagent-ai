import React, {useState} from 'react';
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import Geolocation from '@react-native-community/geolocation';

import {requestLocationPermission} from '../utils/location';

export type LocationQuery =
  | {type: 'text'; value: string}
  | {type: 'coordinates'; latitude: number; longitude: number};

type Props = {
  onSearch?: (query: LocationQuery) => void;
  initialQuery?: LocationQuery | null;
};

function initialQueryText(initialQuery?: LocationQuery | null): string {
  return initialQuery?.type === 'text' ? initialQuery.value : '';
}

function initialLocationLabel(
  initialQuery?: LocationQuery | null,
): string | null {
  if (initialQuery?.type !== 'coordinates') {
    return null;
  }
  return `${initialQuery.latitude.toFixed(4)}, ${initialQuery.longitude.toFixed(
    4,
  )}`;
}

function LocationSearchBar({onSearch, initialQuery}: Props): React.JSX.Element {
  const [query, setQuery] = useState(() => initialQueryText(initialQuery));
  const [locating, setLocating] = useState(false);
  const [locationLabel, setLocationLabel] = useState<string | null>(() =>
    initialLocationLabel(initialQuery),
  );
  const [locationError, setLocationError] = useState<string | null>(null);

  const handleTextSearch = () => {
    const trimmed = query.trim();
    if (!trimmed) {
      return;
    }
    setLocationLabel(null);
    setLocationError(null);
    onSearch?.({type: 'text', value: trimmed});
  };

  const handleUseCurrentLocation = async () => {
    setLocationError(null);
    setLocating(true);

    const hasPermission = await requestLocationPermission();
    if (!hasPermission) {
      setLocationError('Location permission denied.');
      setLocating(false);
      return;
    }

    Geolocation.getCurrentPosition(
      position => {
        const {latitude, longitude} = position.coords;
        setQuery('');
        setLocationLabel(`${latitude.toFixed(4)}, ${longitude.toFixed(4)}`);
        onSearch?.({type: 'coordinates', latitude, longitude});
        setLocating(false);
      },
      err => {
        setLocationError(err.message || 'Could not get current location.');
        setLocating(false);
      },
      {enableHighAccuracy: true, timeout: 15000},
    );
  };

  const handleClear = () => {
    setQuery('');
    setLocationLabel(null);
    setLocationError(null);
  };

  const showClear = query.length > 0 || locationLabel !== null;

  return (
    <View style={styles.container}>
      <View style={styles.row}>
        <TextInput
          style={styles.input}
          placeholder="Search by city or postal code"
          placeholderTextColor="#999"
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={handleTextSearch}
          returnKeyType="search"
        />
        {showClear && (
          <TouchableOpacity
            style={styles.iconButton}
            onPress={handleClear}
            hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
            accessibilityLabel="Clear search">
            <Text style={styles.clearIcon}>✕</Text>
          </TouchableOpacity>
        )}
        <TouchableOpacity
          style={styles.iconButton}
          onPress={handleTextSearch}
          accessibilityLabel="Search">
          <Text style={styles.icon}>🔍</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={styles.iconButton}
          onPress={handleUseCurrentLocation}
          disabled={locating}
          accessibilityLabel="Use current location">
          {locating ? (
            <ActivityIndicator size="small" />
          ) : (
            <Text style={styles.icon}>📍</Text>
          )}
        </TouchableOpacity>
      </View>

      {locationLabel && (
        <Text style={styles.helperText}>Using location: {locationLabel}</Text>
      )}
      {locationError && <Text style={styles.errorText}>{locationError}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    paddingTop: 8,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 24,
    paddingHorizontal: 8,
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 1},
    shadowOpacity: 0.15,
    shadowRadius: 3,
    elevation: 3,
  },
  input: {
    flex: 1,
    height: 44,
    paddingHorizontal: 12,
    fontSize: 15,
  },
  iconButton: {
    width: 36,
    height: 36,
    alignItems: 'center',
    justifyContent: 'center',
  },
  icon: {
    fontSize: 18,
  },
  clearIcon: {
    fontSize: 15,
    color: '#999',
    fontWeight: '700',
  },
  helperText: {
    marginTop: 6,
    marginLeft: 4,
    fontSize: 12,
    color: '#555',
  },
  errorText: {
    marginTop: 6,
    marginLeft: 4,
    fontSize: 12,
    color: '#c62828',
  },
});

export default LocationSearchBar;
