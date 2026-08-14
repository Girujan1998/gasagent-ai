import Geolocation from '@react-native-community/geolocation';
import React, {useMemo, useState} from 'react';
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';

import {useFavorites} from '../store/FavoritesContext';
import {haversineMiles} from '../utils/distance';
import {requestLocationPermission} from '../utils/location';
import StationList from '../components/StationList';

function FavoritesScreen(): React.JSX.Element {
  const {favorites} = useFavorites();
  const [currentLocation, setCurrentLocation] = useState<{
    lat: number;
    lon: number;
  } | null>(null);
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);

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

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Favorites</Text>
      </View>

      {favorites.length > 0 && !currentLocation && (
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

      {locationError && (
        <Text style={styles.locationError}>{locationError}</Text>
      )}

      <StationList
        stations={stationsWithDistance}
        loading={false}
        error={null}
        emptyMessage="No favorites yet. Tap the star on a gas station to save it here."
      />
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
