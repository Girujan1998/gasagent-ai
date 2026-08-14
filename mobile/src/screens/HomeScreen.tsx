import React, {useEffect, useRef, useState} from 'react';
import {ActivityIndicator, StyleSheet, Text, View} from 'react-native';

import {
  GasStation,
  getHealth,
  HealthResponse,
  searchNearestStations,
} from '../api/client';
import StationList from '../components/StationList';
import LocationSearchBar, {
  LocationQuery,
} from '../components/LocationSearchBar';

// The part of a search worth surviving a tab switch: the location searched
// and its first page of results. Deliberately excludes anything loaded via
// "load more" — leaving Home and coming back should show the first page
// again, not everything the user had scrolled through.
export type PersistedSearch = {
  hasSearched: boolean;
  query: LocationQuery | null;
  stations: GasStation[];
  nextCursor: string | null;
  searchLocation: {lat: number; lon: number} | null;
  error: string | null;
};

export const INITIAL_PERSISTED_SEARCH: PersistedSearch = {
  hasSearched: false,
  query: null,
  stations: [],
  nextCursor: null,
  searchLocation: null,
  error: null,
};

type Props = {
  persistedSearch: PersistedSearch;
  onSearchComplete: (search: PersistedSearch) => void;
};

function HomeScreen({
  persistedSearch,
  onSearchComplete,
}: Props): React.JSX.Element {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [stations, setStations] = useState<GasStation[]>(
    persistedSearch.stations,
  );
  const [hasSearched, setHasSearched] = useState(persistedSearch.hasSearched);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(
    persistedSearch.error,
  );
  const [loadingMore, setLoadingMore] = useState(false);

  // The coordinates + cursor a "load more" page continues from. Refs (not
  // state) because handleLoadMore reads the latest value synchronously from
  // FlatList's onEndReached callback, without waiting on a re-render.
  const searchLocationRef = useRef<{lat: number; lon: number} | null>(
    persistedSearch.searchLocation,
  );
  const nextCursorRef = useRef<string | null>(persistedSearch.nextCursor);
  const loadingMoreRef = useRef(false);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(err => setHealthError(err.message));
  }, []);

  const handleLocationSearch = async (locationQuery: LocationQuery) => {
    setHasSearched(true);
    setSearching(true);
    setSearchError(null);
    nextCursorRef.current = null;
    searchLocationRef.current = null;

    try {
      const params =
        locationQuery.type === 'text'
          ? {query: locationQuery.value}
          : {lat: locationQuery.latitude, lon: locationQuery.longitude};
      const response = await searchNearestStations(params, 10);
      const searchLocation = {lat: response.lat, lon: response.lon};
      setStations(response.results);
      nextCursorRef.current = response.next_cursor;
      searchLocationRef.current = searchLocation;
      onSearchComplete({
        hasSearched: true,
        query: locationQuery,
        stations: response.results,
        nextCursor: response.next_cursor,
        searchLocation,
        error: null,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Search failed.';
      setStations([]);
      setSearchError(message);
      onSearchComplete({
        hasSearched: true,
        query: locationQuery,
        stations: [],
        nextCursor: null,
        searchLocation: null,
        error: message,
      });
    } finally {
      setSearching(false);
    }
  };

  const handleLoadMore = async () => {
    const location = searchLocationRef.current;
    const cursor = nextCursorRef.current;
    if (!location || !cursor || loadingMoreRef.current) {
      return;
    }

    // Deliberately not persisted via onSearchComplete — pagination is
    // local-only and resets the next time this screen mounts.
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const response = await searchNearestStations(location, 10, cursor);
      setStations(prev => [...prev, ...response.results]);
      nextCursorRef.current = response.next_cursor;
    } catch {
      // Keep the results already on screen; just stop trying to paginate.
      nextCursorRef.current = null;
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  };

  return (
    <View style={styles.container}>
      <LocationSearchBar
        onSearch={handleLocationSearch}
        initialQuery={persistedSearch.query}
      />

      {hasSearched ? (
        <StationList
          stations={stations}
          loading={searching}
          error={searchError}
          onEndReached={handleLoadMore}
          loadingMore={loadingMore}
        />
      ) : (
        <View style={styles.intro}>
          <Text style={styles.title}>GasAIAgent</Text>
          <Text style={styles.subtitle}>
            Search a city, postal code, or use your current location to find the
            10 nearest gas stations.
          </Text>

          {!health && !healthError && (
            <ActivityIndicator style={styles.spacing} />
          )}

          {health && (
            <Text style={[styles.status, styles.spacing]}>
              ✅ {health.app_name} — {health.status}
            </Text>
          )}

          {healthError && (
            <Text style={[styles.error, styles.spacing]}>
              ⚠️ Could not reach backend: {healthError}
              {'\n'}Make sure the FastAPI server is running (see
              backend/README).
            </Text>
          )}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  intro: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
  },
  subtitle: {
    fontSize: 15,
    color: '#666',
    marginTop: 8,
    textAlign: 'center',
  },
  status: {
    fontSize: 16,
    color: '#2e7d32',
    textAlign: 'center',
  },
  error: {
    fontSize: 14,
    color: '#c62828',
    textAlign: 'center',
  },
  spacing: {
    marginTop: 24,
  },
});

export default HomeScreen;
