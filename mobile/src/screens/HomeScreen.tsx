import React, {useEffect, useMemo, useRef, useState} from 'react';
import {
  ActivityIndicator,
  Keyboard,
  StyleSheet,
  Text,
  TouchableWithoutFeedback,
  View,
} from 'react-native';

import {
  GasStation,
  getHealth,
  HealthResponse,
  searchNearestStations,
} from '../api/client';
import AboutModal from '../components/AboutModal';
import LocationSearchBar, {
  LocationQuery,
} from '../components/LocationSearchBar';
import FilterControl from '../components/FilterControl';
import SortControl from '../components/SortControl';
import StationList from '../components/StationList';
import StationMap from '../components/StationMap';
import ViewModeToggle, {ViewMode} from '../components/ViewModeToggle';
import {
  DEFAULT_PRIMARY_FUEL_KEY,
  DEFAULT_SECONDARY_FUEL_KEY,
  FUEL_LABELS,
  FuelKey,
} from '../config/fuelDisplay';
import {
  brandOptionsFromStations,
  filterStationsByBrands,
} from '../utils/brandFilter';
import {sortStations, SortOption} from '../utils/sortStations';
import {useSharedLocation} from '../store/LocationContext';

// Pagination is manual (a "Load More" button, not infinite scroll) and
// capped: once this many stations have been fetched, unfiltered, from the
// API, we stop calling it and hide the button — regardless of how many
// stations still match an active brand filter. A filter only narrows what
// is displayed from that fixed pool, it never triggers more fetching.
const MAX_TOTAL_STATIONS = 40;
// 20 is the API's maximum `limit` per request (see stations.py).
const STATIONS_PER_PAGE = 20;
// Map view has no "Load More" of its own — it always shows just the first
// page of whatever's been fetched, even if List view's Load More has since
// grown `stations` past this.
const MAX_MAP_STATIONS = 20;

const NO_MATCHING_BRANDS_MESSAGE =
  'No stations match the selected brand filters.';

// The part of a search worth surviving a tab switch: the location searched
// and its first page of results (deliberately excludes anything loaded via
// "load more" — leaving Home and coming back should show the first page
// again, not everything the user had scrolled through), plus the sort order
// and filter selections, which survive a tab switch independently of any
// search.
export type PersistedSearch = {
  hasSearched: boolean;
  query: LocationQuery | null;
  stations: GasStation[];
  nextCursor: string | null;
  searchLocation: {lat: number; lon: number} | null;
  error: string | null;
  sortBy: SortOption;
  primaryFuelKey: FuelKey;
  secondaryFuelKey: FuelKey;
  selectedBrandKeys: Set<string> | null;
};

export const INITIAL_PERSISTED_SEARCH: PersistedSearch = {
  hasSearched: false,
  query: null,
  stations: [],
  nextCursor: null,
  searchLocation: null,
  error: null,
  sortBy: 'distance',
  primaryFuelKey: DEFAULT_PRIMARY_FUEL_KEY,
  secondaryFuelKey: DEFAULT_SECONDARY_FUEL_KEY,
  selectedBrandKeys: null,
};

type Props = {
  persistedSearch: PersistedSearch;
  // Accepts a functional update (like React's own setState) so a sort/
  // filter change can patch just its own field on top of whatever was last
  // persisted, without needing to know or restate the rest — in particular
  // without resending `stations`/`nextCursor`, which must stay exactly what
  // the last completed search/refresh set them to, not whatever "load more"
  // has since grown them to locally (see the PersistedSearch comment above).
  onSearchComplete: (
    search: PersistedSearch | ((prev: PersistedSearch) => PersistedSearch),
  ) => void;
};

function HomeScreen({
  persistedSearch,
  onSearchComplete,
}: Props): React.JSX.Element {
  const {location: sharedLocation, setManualSearchLocation} =
    useSharedLocation();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const [stations, setStations] = useState<GasStation[]>(
    persistedSearch.stations,
  );
  const [hasSearched, setHasSearched] = useState(persistedSearch.hasSearched);
  const [searching, setSearching] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(
    persistedSearch.error,
  );
  const [loadingMore, setLoadingMore] = useState(false);
  const [sortBy, setSortBy] = useState<SortOption>(persistedSearch.sortBy);
  // View mode (list/map) is deliberately not persisted — a display
  // preference rather than a way of narrowing/ordering results, unlike
  // sort and filter below.
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [primaryFuelKey, setPrimaryFuelKey] = useState<FuelKey>(
    persistedSearch.primaryFuelKey,
  );
  const [secondaryFuelKey, setSecondaryFuelKey] = useState<FuelKey>(
    persistedSearch.secondaryFuelKey,
  );
  // null = no brand filter applied (show everything, including brands
  // discovered later via "load more"); a Set is a strict allowlist.
  const [selectedBrandKeys, setSelectedBrandKeys] =
    useState<Set<string> | null>(persistedSearch.selectedBrandKeys);

  const brandOptions = useMemo(
    () => brandOptionsFromStations(stations),
    [stations],
  );
  const filteredStations = useMemo(
    () => filterStationsByBrands(stations, selectedBrandKeys),
    [stations, selectedBrandKeys],
  );
  const sortedStations = useMemo(
    () =>
      sortStations(filteredStations, sortBy, primaryFuelKey, secondaryFuelKey),
    [filteredStations, sortBy, primaryFuelKey, secondaryFuelKey],
  );
  const emptyMessage =
    stations.length > 0 && filteredStations.length === 0
      ? NO_MATCHING_BRANDS_MESSAGE
      : undefined;

  // Map view's own pool — capped independently of List view's Load More,
  // then filtered the same way.
  const mapStations = useMemo(
    () =>
      filterStationsByBrands(
        stations.slice(0, MAX_MAP_STATIONS),
        selectedBrandKeys,
      ),
    [stations, selectedBrandKeys],
  );
  const mapEmptyMessage =
    stations.length > 0 && mapStations.length === 0
      ? NO_MATCHING_BRANDS_MESSAGE
      : undefined;

  // The coordinates + cursor a "load more" page continues from. Refs (not
  // state) because handleLoadMore reads the latest value synchronously,
  // without waiting on a re-render.
  const searchLocationRef = useRef<{lat: number; lon: number} | null>(
    persistedSearch.searchLocation,
  );
  const nextCursorRef = useRef<string | null>(persistedSearch.nextCursor);
  const loadingMoreRef = useRef(false);
  // What "refresh" re-runs. A ref (not the persistedSearch prop) so it
  // stays this component's own live source of truth, the same way the
  // refs above do — persistedSearch is for surviving a tab switch, not
  // for driving behavior within a single mount.
  const lastQueryRef = useRef<LocationQuery | null>(persistedSearch.query);

  // Load More is available whenever there's a fetched-but-unshown page to
  // get (a cursor from the API) and we're still under the overall cap —
  // never based on how many stations currently pass the brand filter.
  const canLoadMore =
    stations.length > 0 &&
    stations.length < MAX_TOTAL_STATIONS &&
    nextCursorRef.current !== null;

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(err => setHealthError(err.message));
  }, []);

  // Shared by a fresh search (typing a location, "Search this area", the
  // current-location pin) and a pull-to-refresh of the current one. They
  // differ only in which loading flag they drive and what happens on
  // failure: a fresh search clears the screen down to the error, but a
  // refresh leaves whatever was already showing in place rather than
  // wiping out good results just because one refresh attempt failed.
  const runSearch = async (
    locationQuery: LocationQuery,
    isRefresh: boolean,
  ) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setHasSearched(true);
      setSearching(true);
      nextCursorRef.current = null;
      searchLocationRef.current = null;
      lastQueryRef.current = locationQuery;
    }
    setSearchError(null);

    try {
      const params =
        locationQuery.type === 'text'
          ? {query: locationQuery.value}
          : {lat: locationQuery.latitude, lon: locationQuery.longitude};
      const response = await searchNearestStations(params, STATIONS_PER_PAGE);
      const searchLocation = {lat: response.lat, lon: response.lon};
      setStations(response.results);
      nextCursorRef.current = response.next_cursor;
      searchLocationRef.current = searchLocation;
      // A manual text search's resolved location still counts as "the
      // shared location" for other tabs, just at lower priority than an
      // actual GPS share (see LocationContext.tsx) — a coordinates-type
      // query already published itself via setSharedGpsLocation when the
      // fix was taken, so this is a no-op for that case.
      setManualSearchLocation(searchLocation);
      onSearchComplete(prev => ({
        ...prev,
        hasSearched: true,
        query: locationQuery,
        stations: response.results,
        nextCursor: response.next_cursor,
        searchLocation,
        error: null,
      }));
    } catch (err) {
      // A failed refresh deliberately leaves the error state alone too —
      // the existing (still valid) results stay on screen, uninterrupted,
      // rather than getting replaced by an error page over one failed
      // pull-to-refresh.
      if (!isRefresh) {
        const message = err instanceof Error ? err.message : 'Search failed.';
        setSearchError(message);
        setStations([]);
        onSearchComplete(prev => ({
          ...prev,
          hasSearched: true,
          query: locationQuery,
          stations: [],
          nextCursor: null,
          searchLocation: null,
          error: message,
        }));
      }
    } finally {
      if (isRefresh) {
        setRefreshing(false);
      } else {
        setSearching(false);
      }
    }
  };

  const handleLocationSearch = (locationQuery: LocationQuery) =>
    runSearch(locationQuery, false);

  // Only offered once there's a location to refresh — the pull gesture
  // itself only exists once StationList's FlatList is on screen, which
  // requires a completed search already.
  const handleRefresh = () => {
    if (lastQueryRef.current) {
      runSearch(lastQueryRef.current, true);
    }
  };

  // Only ever called from the "Load More" button — there is no automatic/
  // scroll-triggered pagination, and a brand filter never causes this to
  // fire on its own even if the filtered list is short.
  const handleLoadMore = async () => {
    const location = searchLocationRef.current;
    const cursor = nextCursorRef.current;
    if (
      !location ||
      !cursor ||
      loadingMoreRef.current ||
      stations.length >= MAX_TOTAL_STATIONS
    ) {
      return;
    }

    const remaining = MAX_TOTAL_STATIONS - stations.length;
    const pageSize = Math.min(STATIONS_PER_PAGE, remaining);

    // Deliberately not persisted via onSearchComplete — pagination is
    // local-only and resets the next time this screen mounts.
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const response = await searchNearestStations(location, pageSize, cursor);
      if (response.results.length > 0) {
        setStations(prev => [...prev, ...response.results]);
      }
      nextCursorRef.current = response.next_cursor;
    } catch {
      // Keep the results already on screen; just stop trying to paginate.
      nextCursorRef.current = null;
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  };

  // Sort and filter each persist immediately on their own change — not
  // just at search time — so they survive a tab switch even if the user
  // never runs another search after adjusting them.
  const handleSortByChange = (value: SortOption) => {
    setSortBy(value);
    onSearchComplete(prev => ({...prev, sortBy: value}));
  };

  const handlePrimaryFuelKeyChange = (value: FuelKey) => {
    setPrimaryFuelKey(value);
    onSearchComplete(prev => ({...prev, primaryFuelKey: value}));
  };

  const handleSecondaryFuelKeyChange = (value: FuelKey) => {
    setSecondaryFuelKey(value);
    onSearchComplete(prev => ({...prev, secondaryFuelKey: value}));
  };

  const handleBrandFiltersApply = (value: Set<string> | null) => {
    setSelectedBrandKeys(value);
    onSearchComplete(prev => ({...prev, selectedBrandKeys: value}));
  };

  return (
    <View style={styles.container}>
      {/* TouchableWithoutFeedback deliberately wraps only this static
          top section, never StationList/StationMap below — nesting a
          FlatList (or a WebView map) inside one is a known way to break
          its scroll/pan gesture on a real device (not always caught by
          the Simulator or by tests). */}
      <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
        <View>
          <View style={styles.topRow}>
            <AboutModal />
          </View>

          <LocationSearchBar
            onSearch={handleLocationSearch}
            initialQuery={
              persistedSearch.query ??
              (sharedLocation
                ? {
                    type: 'coordinates',
                    latitude: sharedLocation.lat,
                    longitude: sharedLocation.lon,
                  }
                : null)
            }
          />

          {hasSearched && stations.length > 0 && (
            <View style={styles.controlsRow}>
              <View style={styles.leftControls}>
                <SortControl
                  value={sortBy}
                  onChange={handleSortByChange}
                  primaryFuelLabel={FUEL_LABELS[primaryFuelKey]}
                  secondaryFuelLabel={FUEL_LABELS[secondaryFuelKey]}
                />
                <ViewModeToggle value={viewMode} onChange={setViewMode} />
              </View>
              <FilterControl
                primaryFuelKey={primaryFuelKey}
                secondaryFuelKey={secondaryFuelKey}
                onChangePrimaryFuelKey={handlePrimaryFuelKeyChange}
                onChangeSecondaryFuelKey={handleSecondaryFuelKeyChange}
                brandOptions={brandOptions}
                selectedBrandKeys={selectedBrandKeys}
                onApplyBrandFilters={handleBrandFiltersApply}
              />
            </View>
          )}
        </View>
      </TouchableWithoutFeedback>

      {hasSearched ? (
        <>
          {viewMode === 'list' ? (
            <StationList
              stations={sortedStations}
              primaryFuelKey={primaryFuelKey}
              secondaryFuelKey={secondaryFuelKey}
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
            // Panning, zooming, and tapping a pin never trigger a fetch —
            // the map only ever displays its own fixed pool of
            // already-fetched stations (see MAX_MAP_STATIONS above). The
            // one deliberate exception is "Search this area" itself, which
            // runs a brand new search exactly like typing a location and
            // pressing Search.
            <StationMap
              stations={mapStations}
              primaryFuelKey={primaryFuelKey}
              secondaryFuelKey={secondaryFuelKey}
              center={searchLocationRef.current}
              loading={searching}
              error={searchError}
              onSearchArea={areaCenter =>
                handleLocationSearch({
                  type: 'coordinates',
                  latitude: areaCenter.lat,
                  longitude: areaCenter.lon,
                })
              }
              emptyMessage={mapEmptyMessage}
            />
          )}
        </>
      ) : (
        <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
          <View style={styles.intro}>
            <Text style={styles.title}>Gas Fill-Up</Text>
            <Text style={styles.subtitle}>
              Search a city, postal code, or use your current location to find
              the 20 nearest gas stations.
            </Text>

            {!health && !healthError && (
              <ActivityIndicator style={styles.spacing} />
            )}

            {healthError && (
              <Text style={[styles.error, styles.spacing]}>
                ⚠️ Could not reach backend: {healthError}
                {'\n'}Make sure the FastAPI server is running (see
                backend/README).
              </Text>
            )}
          </View>
        </TouchableWithoutFeedback>
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
  topRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
  },
  leftControls: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    // Lets SortControl's trigger truncate instead of pushing FilterControl
    // (which must stay flexShrink: 0, i.e. RN's own default) off-screen —
    // minWidth: 0 is required for that shrinking to actually kick in, since
    // Yoga otherwise floors a flex item's width at its content size.
    flexShrink: 1,
    minWidth: 0,
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
