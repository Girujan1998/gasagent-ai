import React, {useEffect, useRef, useState} from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import {GasPriceForecast, getGasPriceForecast} from '../api/client';
import ForecastCard from '../components/ForecastCard';
import {
  LocationQuery,
  locationQueryLabel,
} from '../components/LocationSearchBar';
import PriceRangeForecastCard from '../components/PriceRangeForecastCard';

type Location = {lat: number; lon: number};

// The part of a forecast worth surviving a tab switch: which location it
// was fetched for, and the result. Without this, switching to another tab
// and back would refetch from scratch every time — the same GasBuddy
// request the Gas tab just made, again, for no new information (GasBuddy
// is an unofficial, rate-limit-sensitive scraper, so that's not free).
export type PersistedForecast = {
  searchLocation: Location | null;
  forecast: GasPriceForecast | null;
  error: string | null;
};

export const INITIAL_PERSISTED_FORECAST: PersistedForecast = {
  searchLocation: null,
  forecast: null,
  error: null,
};

function sameLocation(a: Location | null, b: Location | null): boolean {
  if (a === b) {
    return true;
  }
  if (a === null || b === null) {
    return false;
  }
  return a.lat === b.lat && a.lon === b.lon;
}

type Props = {
  // Reuses the Gas tab's own last-searched location rather than asking
  // the user to search again here — "tomorrow's price near where you're
  // already looking" is the whole point of the card.
  searchLocation: Location | null;
  // The Gas tab's own query (what the user actually typed/selected, or
  // "current location" coordinates) — shown as a label so the forecast
  // says what area it's for, without a second geocoding call just to get
  // a display name back from lat/lon.
  locationQuery: LocationQuery | null;
  persistedForecast: PersistedForecast;
  onForecastComplete: (forecast: PersistedForecast) => void;
};

function NotificationsScreen({
  searchLocation,
  locationQuery,
  persistedForecast,
  onForecastComplete,
}: Props): React.JSX.Element {
  const [forecast, setForecast] = useState<GasPriceForecast | null>(
    persistedForecast.forecast,
  );
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(persistedForecast.error);
  // Which location the forecast/error above actually reflect — seeded
  // from the persisted value (so remounting this screen for the same
  // search location reuses it instead of refetching) and only ever
  // updated once a fetch actually completes, never by a prop change, so
  // it can't itself retrigger the effect below.
  const fetchedForRef = useRef(persistedForecast.searchLocation);

  useEffect(() => {
    if (!searchLocation) {
      setForecast(null);
      setError(null);
      fetchedForRef.current = null;
      return;
    }

    if (sameLocation(fetchedForRef.current, searchLocation)) {
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    getGasPriceForecast(searchLocation.lat, searchLocation.lon)
      .then(result => {
        if (!cancelled) {
          setForecast(result);
          fetchedForRef.current = searchLocation;
          onForecastComplete({searchLocation, forecast: result, error: null});
        }
      })
      .catch(err => {
        if (!cancelled) {
          const message =
            err instanceof Error ? err.message : 'Failed to load forecast.';
          setError(message);
          fetchedForRef.current = searchLocation;
          onForecastComplete({searchLocation, forecast: null, error: message});
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [searchLocation, onForecastComplete]);

  // Pulling to refresh re-runs the same fetch for the location already on
  // screen — a failed refresh deliberately leaves the existing forecast in
  // place rather than replacing it with an error, the same "don't wipe out
  // good results over one bad refresh" rule HomeScreen's pull-to-refresh
  // follows for station search.
  const handleRefresh = () => {
    if (!searchLocation) {
      return;
    }
    setRefreshing(true);
    getGasPriceForecast(searchLocation.lat, searchLocation.lon)
      .then(result => {
        setForecast(result);
        fetchedForRef.current = searchLocation;
        onForecastComplete({searchLocation, forecast: result, error: null});
      })
      .catch(() => {
        // Keep showing the last good forecast; nothing to update.
      })
      .finally(() => {
        setRefreshing(false);
      });
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Forecasts</Text>
        {searchLocation && locationQuery && (
          <Text style={styles.locationLabel}>
            {locationQueryLabel(locationQuery)}
          </Text>
        )}
      </View>

      {!searchLocation && (
        <Text style={styles.message}>
          Search for gas stations on the Gas tab to see a price forecast here.
        </Text>
      )}

      {searchLocation && loading && (
        <ActivityIndicator style={styles.spacing} />
      )}

      {searchLocation && !loading && error && (
        <Text style={[styles.message, styles.error]}>⚠️ {error}</Text>
      )}

      {searchLocation && !loading && !error && forecast && (
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={handleRefresh}
              tintColor="#1565c0"
            />
          }>
          <ForecastCard forecast={forecast} />
          <PriceRangeForecastCard forecast={forecast} />
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    paddingHorizontal: 16,
    paddingTop: 16,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
  },
  locationLabel: {
    fontSize: 14,
    color: '#888',
    marginTop: 2,
  },
  message: {
    fontSize: 14,
    color: '#666',
    textAlign: 'center',
    paddingHorizontal: 24,
    marginTop: 40,
  },
  error: {
    color: '#c62828',
  },
  spacing: {
    marginTop: 40,
  },
  scrollContent: {
    paddingBottom: 24,
  },
});

export default NotificationsScreen;
