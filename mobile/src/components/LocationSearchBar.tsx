import React, {useEffect, useRef, useState} from 'react';
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import Geolocation from '@react-native-community/geolocation';

import {getLocationAutocomplete, LocationSuggestion} from '../api/client';
import {requestLocationPermission} from '../utils/location';

const AUTOCOMPLETE_MIN_LENGTH = 3;
const AUTOCOMPLETE_DEBOUNCE_MS = 300;

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

// A human-readable label for a definite (non-null) LocationQuery — what
// the user typed/selected for a text search, or its coordinates for a
// "current location" one. Used wherever a search's location needs to be
// shown elsewhere in the app (e.g. the Forecasts tab's forecast),
// without a second geocoding call just to get a display name.
export function locationQueryLabel(query: LocationQuery): string {
  return query.type === 'text'
    ? query.value
    : `${query.latitude.toFixed(4)}, ${query.longitude.toFixed(4)}`;
}

function LocationSearchBar({onSearch, initialQuery}: Props): React.JSX.Element {
  const [query, setQuery] = useState(() => initialQueryText(initialQuery));
  const [locating, setLocating] = useState(false);
  const [locationLabel, setLocationLabel] = useState<string | null>(() =>
    initialLocationLabel(initialQuery),
  );
  const [locationError, setLocationError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<LocationSuggestion[]>([]);

  // Set right before a suggestion is picked, so filling the input with its
  // value doesn't immediately reopen the dropdown with the same result.
  const suppressNextFetchRef = useRef(false);
  // Guards against an older, slower response overwriting a newer one.
  const requestIdRef = useRef(0);
  // Lifted out of the effect so a manual search (which doesn't change
  // `query`, so the effect's own cleanup never runs) can still cancel a
  // debounce that's already in flight from earlier typing.
  const debounceTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The effect below also runs on mount, and `query` can start out
  // non-empty — restored from a previous search (e.g. leaving the Home
  // tab and coming back re-mounts this with the persisted query). That's
  // not the user typing, so it shouldn't trigger a fetch; only reactions
  // to real subsequent changes should.
  const isFirstRenderRef = useRef(true);

  useEffect(() => {
    if (isFirstRenderRef.current) {
      isFirstRenderRef.current = false;
      return;
    }

    if (suppressNextFetchRef.current) {
      suppressNextFetchRef.current = false;
      setSuggestions([]);
      return;
    }

    const trimmed = query.trim();
    if (trimmed.length < AUTOCOMPLETE_MIN_LENGTH) {
      setSuggestions([]);
      return;
    }

    debounceTimeoutRef.current = setTimeout(() => {
      const requestId = ++requestIdRef.current;
      getLocationAutocomplete(trimmed)
        .then(response => {
          if (requestIdRef.current === requestId) {
            setSuggestions(
              Array.isArray(response?.results) ? response.results : [],
            );
          }
        })
        .catch(() => {
          // A dropped connection while typing shouldn't surface as an
          // error — it just stays empty until the next keystroke retries.
          if (requestIdRef.current === requestId) {
            setSuggestions([]);
          }
        });
    }, AUTOCOMPLETE_DEBOUNCE_MS);

    return () => {
      if (debounceTimeoutRef.current) {
        clearTimeout(debounceTimeoutRef.current);
      }
    };
  }, [query]);

  // Cancels a pending or in-flight autocomplete fetch and hides the
  // dropdown — used whenever the user acts on the query directly (search,
  // clear) rather than through a suggestion, so a slower request from
  // earlier typing can't repopulate the dropdown after the fact.
  const dismissSuggestions = () => {
    if (debounceTimeoutRef.current) {
      clearTimeout(debounceTimeoutRef.current);
      debounceTimeoutRef.current = null;
    }
    requestIdRef.current += 1;
    setSuggestions([]);
  };

  const handleTextSearch = () => {
    const trimmed = query.trim();
    if (!trimmed) {
      return;
    }
    dismissSuggestions();
    setLocationLabel(null);
    setLocationError(null);
    onSearch?.({type: 'text', value: trimmed});
  };

  const handleSelectSuggestion = (suggestion: LocationSuggestion) => {
    suppressNextFetchRef.current = true;
    setQuery(suggestion.value);
    setSuggestions([]);
    setLocationLabel(null);
    setLocationError(null);
    onSearch?.({type: 'text', value: suggestion.value});
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
    dismissSuggestions();
    setQuery('');
    setLocationLabel(null);
    setLocationError(null);
  };

  const showClear = query.length > 0 || locationLabel !== null;
  const showSuggestions =
    query.trim().length >= AUTOCOMPLETE_MIN_LENGTH && suggestions.length > 0;

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

      {showSuggestions && (
        <View style={styles.suggestionsList}>
          {suggestions.map(suggestion => (
            <TouchableOpacity
              key={suggestion.value}
              style={styles.suggestionRow}
              onPress={() => handleSelectSuggestion(suggestion)}
              accessibilityLabel={`Search ${suggestion.label}`}>
              <Text style={styles.suggestionText} numberOfLines={1}>
                {suggestion.label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      )}

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
  suggestionsList: {
    marginTop: 6,
    backgroundColor: '#fff',
    borderRadius: 14,
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 1},
    shadowOpacity: 0.12,
    shadowRadius: 3,
    elevation: 3,
  },
  suggestionRow: {
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#eee',
  },
  suggestionText: {
    fontSize: 14,
    color: '#444',
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
