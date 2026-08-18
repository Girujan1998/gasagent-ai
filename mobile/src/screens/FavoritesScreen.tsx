import Geolocation from '@react-native-community/geolocation';
import React, {useMemo, useState} from 'react';
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';

import {GasStation, searchNearestStations} from '../api/client';
import {useFavorites} from '../store/FavoritesContext';
import {haversineMiles} from '../utils/distance';
import {requestLocationPermission} from '../utils/location';
import FilterControl from '../components/FilterControl';
import ReorderableFavoritesList from '../components/ReorderableFavoritesList';
import StationList from '../components/StationList';
import {
  DEFAULT_PRIMARY_FUEL_KEY,
  DEFAULT_SECONDARY_FUEL_KEY,
  FuelKey,
} from '../config/fuelDisplay';
import {
  brandOptionsFromStations,
  filterStationsByBrands,
} from '../utils/brandFilter';

const NO_MATCHING_BRANDS_MESSAGE =
  'No favorites match the selected brand filters.';
const NO_FAVORITES_MESSAGE =
  'No favorites yet. Tap the star on a gas station to save it here.';

function FavoritesScreen(): React.JSX.Element {
  const {favorites, reorderFavorites, updateFavoritePrices} = useFavorites();
  const [reordering, setReordering] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [currentLocation, setCurrentLocation] = useState<{
    lat: number;
    lon: number;
  } | null>(null);
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);
  // Same filter concept as the Gas tab's FilterControl — a fuel-grade pair
  // to price by, plus an optional brand allowlist — applied to the
  // favorites list rather than a fresh search's results.
  const [primaryFuelKey, setPrimaryFuelKey] = useState<FuelKey>(
    DEFAULT_PRIMARY_FUEL_KEY,
  );
  const [secondaryFuelKey, setSecondaryFuelKey] = useState<FuelKey>(
    DEFAULT_SECONDARY_FUEL_KEY,
  );
  const [selectedBrandKeys, setSelectedBrandKeys] =
    useState<Set<string> | null>(null);

  const handleShareLocation = async () => {
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
        setCurrentLocation({
          lat: position.coords.latitude,
          lon: position.coords.longitude,
        });
        setLocating(false);
      },
      err => {
        setLocationError(err.message || 'Could not get current location.');
        setLocating(false);
      },
      {enableHighAccuracy: true, timeout: 15000},
    );
  };

  // Favorites store a snapshot of the station (including price) from when
  // it was saved, so unlike the Gas tab there's nothing to re-fetch on a
  // timer — pulling to refresh re-queries GasBuddy at each favorite's own
  // coordinates and updates just the price fields, one call per favorite
  // (there's no batch "get by id" endpoint). A favorite with no saved
  // coordinates, or whose lookup fails or no longer matches by station_id,
  // is left showing its last-known price rather than being dropped.
  const handleRefresh = async () => {
    const refreshable = favorites.filter(
      station => station.latitude != null && station.longitude != null,
    );
    if (refreshable.length === 0) {
      return;
    }

    setRefreshing(true);
    try {
      const results = await Promise.allSettled(
        refreshable.map(station =>
          searchNearestStations(
            {lat: station.latitude as number, lon: station.longitude as number},
            1,
          ),
        ),
      );
      const updates: GasStation[] = [];
      results.forEach((result, index) => {
        if (result.status !== 'fulfilled') {
          return;
        }
        const match = result.value.results.find(
          station => station.station_id === refreshable[index].station_id,
        );
        if (match) {
          updates.push(match);
        }
      });
      if (updates.length > 0) {
        updateFavoritePrices(updates);
      }
    } finally {
      setRefreshing(false);
    }
  };

  const stationsWithDistance = useMemo(() => {
    if (!currentLocation) {
      return favorites.map(station => ({...station, distance_miles: null}));
    }
    return favorites.map(station =>
      station.latitude != null && station.longitude != null
        ? {
            ...station,
            distance_miles: haversineMiles(
              currentLocation.lat,
              currentLocation.lon,
              station.latitude,
              station.longitude,
            ),
          }
        : {...station, distance_miles: null},
    );
  }, [favorites, currentLocation]);

  const brandOptions = useMemo(
    () => brandOptionsFromStations(favorites),
    [favorites],
  );
  const filteredStations = useMemo(
    () => filterStationsByBrands(stationsWithDistance, selectedBrandKeys),
    [stationsWithDistance, selectedBrandKeys],
  );
  const emptyMessage =
    favorites.length === 0
      ? NO_FAVORITES_MESSAGE
      : filteredStations.length === 0
      ? NO_MATCHING_BRANDS_MESSAGE
      : undefined;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Favorites</Text>
        {favorites.length > 1 && (
          <TouchableOpacity
            onPress={() => setReordering(prev => !prev)}
            hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
            accessibilityLabel={
              reordering ? 'Done reordering favorites' : 'Order favorites'
            }>
            <Text style={styles.orderButtonText}>
              {reordering ? 'Done' : 'Order'}
            </Text>
          </TouchableOpacity>
        )}
      </View>

      {favorites.length > 0 && !reordering && (
        <View style={styles.controlsRow}>
          <FilterControl
            primaryFuelKey={primaryFuelKey}
            secondaryFuelKey={secondaryFuelKey}
            onChangePrimaryFuelKey={setPrimaryFuelKey}
            onChangeSecondaryFuelKey={setSecondaryFuelKey}
            brandOptions={brandOptions}
            selectedBrandKeys={selectedBrandKeys}
            onApplyBrandFilters={setSelectedBrandKeys}
          />
        </View>
      )}

      {favorites.length > 0 && !currentLocation && !reordering && (
        <TouchableOpacity
          style={styles.locationBanner}
          onPress={handleShareLocation}
          disabled={locating}
          accessibilityLabel="Share your location">
          {locating ? (
            <ActivityIndicator size="small" color="#1565c0" />
          ) : (
            <Text style={styles.locationBannerText}>
              📍 Share your location to see distances
            </Text>
          )}
        </TouchableOpacity>
      )}

      {locationError && !reordering && (
        <Text style={styles.locationError}>{locationError}</Text>
      )}

      {reordering ? (
        <ReorderableFavoritesList
          stations={favorites}
          onReorder={reorderFavorites}
        />
      ) : (
        <StationList
          stations={filteredStations}
          primaryFuelKey={primaryFuelKey}
          secondaryFuelKey={secondaryFuelKey}
          loading={false}
          error={null}
          refreshing={refreshing}
          onRefresh={handleRefresh}
          emptyMessage={emptyMessage}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 16,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
  },
  orderButtonText: {
    fontSize: 15,
    color: '#1565c0',
    fontWeight: '600',
  },
  controlsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    paddingHorizontal: 16,
    marginTop: 10,
  },
  locationBanner: {
    marginHorizontal: 16,
    marginTop: 12,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 12,
    backgroundColor: '#dbe6f6',
    alignItems: 'center',
  },
  locationBannerText: {
    fontSize: 13,
    color: '#1565c0',
    fontWeight: '600',
  },
  locationError: {
    marginTop: 8,
    marginHorizontal: 16,
    fontSize: 12,
    color: '#c62828',
    textAlign: 'center',
  },
});

export default FavoritesScreen;
