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

  const value = useMemo(
    () => ({favorites, isFavorite, toggleFavorite, isReady: loaded}),
    [favorites, isFavorite, toggleFavorite, loaded],
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
