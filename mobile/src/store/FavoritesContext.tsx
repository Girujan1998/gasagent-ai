import AsyncStorage from '@react-native-async-storage/async-storage';
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import {GasStation} from '../api/client';

const STORAGE_KEY = 'gasaiagent:favorites';

type FavoritesContextValue = {
  favorites: GasStation[];
  isFavorite: (stationId: string) => boolean;
  toggleFavorite: (station: GasStation) => void;
  // Replaces the favorites list wholesale with a new ordering of the same
  // stations — the array's order is itself the persisted display order
  // (see AsyncStorage above), so drag-to-reorder is just "store this
  // permutation" rather than a separate sort-key concept.
  reorderFavorites: (stations: GasStation[]) => void;
  // Replaces each favorite with its freshly-fetched counterpart (matched by
  // station_id) — e.g. after a pull-to-refresh re-queries live prices.
  // Favorites not present in `updates` (a failed lookup, or one with no
  // coordinates to refresh from) are left untouched rather than dropped.
  updateFavoritePrices: (updates: GasStation[]) => void;
  isReady: boolean;
};

const FavoritesContext = createContext<FavoritesContextValue | null>(null);

function FavoritesProvider({
  children,
}: {
  children: React.ReactNode;
}): React.JSX.Element {
  const [favorites, setFavorites] = useState<GasStation[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then(raw => {
        if (raw) {
          setFavorites(JSON.parse(raw));
        }
      })
      .catch(() => {
        // Corrupt or unavailable storage — start with an empty list.
      })
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    if (!loaded) {
      return;
    }
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(favorites)).catch(
      () => {},
    );
  }, [favorites, loaded]);

  const isFavorite = useCallback(
    (stationId: string) =>
      favorites.some(station => station.station_id === stationId),
    [favorites],
  );

  const toggleFavorite = useCallback((station: GasStation) => {
    setFavorites(prev =>
      prev.some(existing => existing.station_id === station.station_id)
        ? prev.filter(existing => existing.station_id !== station.station_id)
        : [...prev, station],
    );
  }, []);

  const reorderFavorites = useCallback((stations: GasStation[]) => {
    setFavorites(stations);
  }, []);

  const updateFavoritePrices = useCallback((updates: GasStation[]) => {
    setFavorites(prev =>
      prev.map(
        existing =>
          updates.find(fresh => fresh.station_id === existing.station_id) ??
          existing,
      ),
    );
  }, []);

  const value = useMemo(
    () => ({
      favorites,
      isFavorite,
      toggleFavorite,
      reorderFavorites,
      updateFavoritePrices,
      isReady: loaded,
    }),
    [
      favorites,
      isFavorite,
      toggleFavorite,
      reorderFavorites,
      updateFavoritePrices,
      loaded,
    ],
  );

  return (
    <FavoritesContext.Provider value={value}>
      {children}
    </FavoritesContext.Provider>
  );
}

function useFavorites(): FavoritesContextValue {
  const context = useContext(FavoritesContext);
  if (!context) {
    throw new Error('useFavorites must be used within a FavoritesProvider');
  }
  return context;
}

export {FavoritesProvider, useFavorites};
