import React, {useMemo, useRef, useState} from 'react';
import {StyleSheet, Text, View} from 'react-native';

import {EvStation, searchNearestEvStations} from '../api/client';
import LocationSearchBar, {
  LocationQuery,
} from '../components/LocationSearchBar';
import EvFilterControl, {
  EvFilterSelection,
} from '../components/EvFilterControl';
import EvStationList from '../components/EvStationList';
import EvStationMap from '../components/EvStationMap';
import ViewModeToggle, {ViewMode} from '../components/ViewModeToggle';
import {
  connectorOptionsFromStations,
  filterStationsByChargerLevels,
  filterStationsByConnectors,
  filterStationsByNetworks,
  networkOptionsFromStations,
} from '../utils/evFilters';

const NO_MATCHING_FILTERS_MESSAGE =
  'No EV chargers match the selected filters.';

const INITIAL_EV_FILTER_SELECTION: EvFilterSelection = {
  networkKeys: null,
  connectorKeys: null,
  chargerLevelKeys: null,
};

// AFDC has no cursor-based pagination — `limit` is the total nearest
// stations to return, already sorted by distance. "Load More" re-requests
// the same location with a bigger limit and replaces the results, rather
// than appending a page (see EV_STATIONS_PER_PAGE usage below).
const MAX_TOTAL_STATIONS = 40;
const EV_STATIONS_PER_PAGE = 20;

// Map view searches its own fixed radius instead of reusing List view's
// nearest-N results, so a sparse suburb doesn't leave the map nearly empty
// just because List view's page size ran out of nearby stations.
const MAP_SEARCH_RADIUS_KM = 30;
// NREL's own hard ceiling (see afdc_client.MAX_LIMIT) — there's no further
// pagination beyond this on their end, so this is "no cap of our own"
// rather than an arbitrary number.
const MAP_RESULTS_LIMIT = 200;

// The part of a search worth surviving a tab switch: the location searched
// and its first page of results — mirrors HomeScreen's PersistedSearch.
export type PersistedEvSearch = {
  hasSearched: boolean;
  query: LocationQuery | null;
  stations: EvStation[];
  totalResults: number;
  mapStations: EvStation[];
  mapError: string | null;
  searchLocation: {lat: number; lon: number} | null;
  error: string | null;
};

export const INITIAL_PERSISTED_EV_SEARCH: PersistedEvSearch = {
  hasSearched: false,
  query: null,
  stations: [],
  totalResults: 0,
  mapStations: [],
  mapError: null,
  searchLocation: null,
  error: null,
};

type Props = {
  persistedSearch: PersistedEvSearch;
  onSearchComplete: (search: PersistedEvSearch) => void;
};

function EvScreen({
  persistedSearch,
  onSearchComplete,
}: Props): React.JSX.Element {
  const [stations, setStations] = useState<EvStation[]>(
    persistedSearch.stations,
  );
  const [totalResults, setTotalResults] = useState(
    persistedSearch.totalResults,
  );
  const [mapStations, setMapStations] = useState<EvStation[]>(
    persistedSearch.mapStations,
  );
  const [mapLoading, setMapLoading] = useState(false);
  const [mapError, setMapError] = useState<string | null>(
    persistedSearch.mapError,
  );
  const [hasSearched, setHasSearched] = useState(persistedSearch.hasSearched);
  const [searching, setSearching] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(
    persistedSearch.error,
  );
  const [loadingMore, setLoadingMore] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  // Not persisted across tab switches — a view preference, same treatment
  // as viewMode above rather than search result data.
  const [evFilterSelection, setEvFilterSelection] = useState<EvFilterSelection>(
    INITIAL_EV_FILTER_SELECTION,
  );
  // Bumped only for a fresh location search (search bar or current
  // location), never for "Search this area" — EvStationMap watches this to
  // decide when to recenter/zoom the map versus just patching in new pins
  // at whatever pan/zoom the user currently has.
  const [mapRecenterToken, setMapRecenterToken] = useState(0);

  // Filter options are drawn from List view's own results — Map view uses
  // the same options and selection rather than deriving its own from its
  // (much larger) pool, so switching between List and Map never changes
  // what a given filter selection means.
  const networkOptions = useMemo(
    () => networkOptionsFromStations(stations),
    [stations],
  );
  const connectorOptions = useMemo(
    () => connectorOptionsFromStations(stations),
    [stations],
  );

  const filteredStations = useMemo(
    () =>
      filterStationsByChargerLevels(
        filterStationsByConnectors(
          filterStationsByNetworks(stations, evFilterSelection.networkKeys),
          evFilterSelection.connectorKeys,
        ),
        evFilterSelection.chargerLevelKeys,
      ),
    [stations, evFilterSelection],
  );
  const filteredMapStations = useMemo(
    () =>
      filterStationsByChargerLevels(
        filterStationsByConnectors(
          filterStationsByNetworks(mapStations, evFilterSelection.networkKeys),
          evFilterSelection.connectorKeys,
        ),
        evFilterSelection.chargerLevelKeys,
      ),
    [mapStations, evFilterSelection],
  );
  const emptyMessage =
    stations.length > 0 && filteredStations.length === 0
      ? NO_MATCHING_FILTERS_MESSAGE
      : undefined;
  const mapEmptyMessage =
    mapStations.length > 0 && filteredMapStations.length === 0
      ? NO_MATCHING_FILTERS_MESSAGE
      : undefined;

  // Refs (not state) so handleLoadMore reads the latest value synchronously,
  // without waiting on a re-render — mirrors HomeScreen's own refs.
  const searchLocationRef = useRef<{lat: number; lon: number} | null>(
    persistedSearch.searchLocation,
  );
  const loadingMoreRef = useRef(false);
  const lastQueryRef = useRef<LocationQuery | null>(persistedSearch.query);

  const canLoadMore =
    stations.length > 0 &&
    stations.length < MAX_TOTAL_STATIONS &&
    stations.length < totalResults;

  // Shared by a fresh search, a pull-to-refresh, and "Search this area" —
  // same split as HomeScreen.runSearch for isRefresh: a fresh search clears
  // the screen down to the error, a refresh leaves existing results in
  // place on failure. This also drives Map view's own wide-radius fetch,
  // reusing the coordinates List view's search already resolved rather
  // than geocoding a second time. `recenterMap` is true for a genuinely
  // new location (search bar, current location, or a refresh of one) and
  // false for "Search this area" — which searches a new center too, but
  // deliberately shouldn't yank the map away from where the user just
  // panned it.
  const runSearch = async (
    locationQuery: LocationQuery,
    isRefresh: boolean,
    recenterMap: boolean,
  ) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setHasSearched(true);
      setSearching(true);
      searchLocationRef.current = null;
      lastQueryRef.current = locationQuery;
    }
    setSearchError(null);

    // What ends up persisted once this search (list + map) settles —
    // starts from the current values so a failed refresh leaves them
    // untouched, and is only overwritten where a fetch actually succeeds
    // or a fresh (non-refresh) search fails outright.
    let nextStations = stations;
    let nextTotalResults = totalResults;
    let nextSearchLocation = searchLocationRef.current;
    let nextError: string | null = null;
    let nextMapStations = mapStations;
    let nextMapError = mapError;

    try {
      const params =
        locationQuery.type === 'text'
          ? {query: locationQuery.value}
          : {lat: locationQuery.latitude, lon: locationQuery.longitude};
      const response = await searchNearestEvStations(
        params,
        EV_STATIONS_PER_PAGE,
      );
      const searchLocation = {lat: response.lat, lon: response.lon};
      nextStations = response.results;
      nextTotalResults = response.total_results;
      nextSearchLocation = searchLocation;
      setStations(nextStations);
      setTotalResults(nextTotalResults);
      searchLocationRef.current = searchLocation;

      setMapLoading(true);
      setMapError(null);
      try {
        const mapResponse = await searchNearestEvStations(
          searchLocation,
          MAP_RESULTS_LIMIT,
          MAP_SEARCH_RADIUS_KM,
        );
        nextMapStations = mapResponse.results;
        nextMapError = null;
        setMapStations(nextMapStations);
        if (recenterMap) {
          setMapRecenterToken(token => token + 1);
        }
      } catch (mapErr) {
        if (!isRefresh) {
          const message =
            mapErr instanceof Error ? mapErr.message : 'Search failed.';
          nextMapStations = [];
          nextMapError = message;
          setMapStations([]);
          setMapError(message);
        }
      } finally {
        setMapLoading(false);
      }
    } catch (err) {
      // A failed refresh deliberately leaves the error state alone too —
      // the existing (still valid) results stay on screen, uninterrupted,
      // rather than getting replaced by an error page over one failed
      // pull-to-refresh.
      if (!isRefresh) {
        const message = err instanceof Error ? err.message : 'Search failed.';
        nextStations = [];
        nextTotalResults = 0;
        nextSearchLocation = null;
        nextError = message;
        nextMapStations = [];
        nextMapError = null;
        setSearchError(message);
        setStations([]);
        setTotalResults(0);
      }
    } finally {
      if (isRefresh) {
        setRefreshing(false);
      } else {
        setSearching(false);
      }
    }

    onSearchComplete({
      hasSearched: true,
      query: locationQuery,
      stations: nextStations,
      totalResults: nextTotalResults,
      mapStations: nextMapStations,
      mapError: nextMapError,
      searchLocation: nextSearchLocation,
      error: nextError,
    });
  };

  const handleLocationSearch = (locationQuery: LocationQuery) =>
    runSearch(locationQuery, false, true);

  // Only offered once there's a location to refresh — the pull gesture
  // itself only exists once StationList's FlatList is on screen, which
  // requires a completed search already.
  const handleRefresh = () => {
    if (lastQueryRef.current) {
      runSearch(lastQueryRef.current, true, true);
    }
  };

  // "Search this area" on the map — unlike handleLocationSearch, this
  // deliberately doesn't recenter/rezoom the map once results come back,
  // since the user just panned there on purpose.
  const handleSearchThisArea = (areaCenter: {lat: number; lon: number}) =>
    runSearch(
      {
        type: 'coordinates',
        latitude: areaCenter.lat,
        longitude: areaCenter.lon,
      },
      false,
      false,
    );

  // Only ever called from the "Load More" button. Re-requests the same
  // location with a bigger limit and replaces the results array — there is
  // no cursor to continue from, unlike gas search. Local-only, like
  // HomeScreen's own pagination — never persisted via onSearchComplete,
  // and never touches Map view's independently-fetched radius search.
  const handleLoadMore = async () => {
    const location = searchLocationRef.current;
    if (
      !location ||
      loadingMoreRef.current ||
      stations.length >= MAX_TOTAL_STATIONS ||
      stations.length >= totalResults
    ) {
      return;
    }

    const targetLimit = Math.min(
      stations.length + EV_STATIONS_PER_PAGE,
      MAX_TOTAL_STATIONS,
    );

    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const response = await searchNearestEvStations(location, targetLimit);
      setStations(response.results);
      setTotalResults(response.total_results);
    } catch {
      // Keep the results already on screen; just stop trying to paginate.
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
        <>
          {stations.length > 0 && (
            <View style={styles.controlsRow}>
              <ViewModeToggle value={viewMode} onChange={setViewMode} />
              <EvFilterControl
                networkOptions={networkOptions}
                connectorOptions={connectorOptions}
                selection={evFilterSelection}
                onApply={setEvFilterSelection}
              />
            </View>
          )}
          {viewMode === 'list' ? (
            <EvStationList
              stations={filteredStations}
              loading={searching}
              error={searchError}
              onLoadMore={handleLoadMore}
              canLoadMore={canLoadMore}
              loadingMore={loadingMore}
              refreshing={refreshing}
              onRefresh={handleRefresh}
              emptyMessage={emptyMessage}
            />
          ) : (
            <EvStationMap
              stations={filteredMapStations}
              center={searchLocationRef.current}
              loading={mapLoading}
              error={mapError}
              recenterSignal={mapRecenterToken}
              onSearchArea={handleSearchThisArea}
              emptyMessage={mapEmptyMessage}
            />
          )}
        </>
      ) : (
        <View style={styles.intro}>
          <Text style={styles.title}>EV Charging</Text>
          <Text style={styles.subtitle}>
            Search a city, postal code, or use your current location to find
            nearby EV charging stations.
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  controlsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    marginTop: 10,
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
});

export default EvScreen;
