import React, {createContext, useCallback, useContext, useRef, useState} from 'react';

// Session-only (not persisted to AsyncStorage, unlike FavoritesContext) —
// resets on the next app launch, the same as every other tab's own
// search state already does. The point is just to stop the Gas, EV,
// Chat, and Favorites tabs from each asking for a fresh GPS fix
// independently: once any one of them shares a location, the others can
// read it here instead of prompting again.
export type SharedLocation = {lat: number; lon: number};

type LocationContextValue = {
  location: SharedLocation | null;
  // A real "share my location" (GPS) action — always wins, and once
  // given, only another GPS share can replace it.
  setSharedGpsLocation: (location: SharedLocation) => void;
  // A manual text search's resolved location (e.g. typing "Chicago") —
  // only takes effect when no GPS location has been shared yet this
  // session; a GPS share always keeps priority over it.
  setManualSearchLocation: (location: SharedLocation) => void;
};

const LocationContext = createContext<LocationContextValue | null>(null);

function LocationProvider({
  children,
}: {
  children: React.ReactNode;
}): React.JSX.Element {
  const [location, setLocation] = useState<SharedLocation | null>(null);
  // A ref, not state — purely an internal priority flag, never itself
  // read for rendering, so changing it shouldn't cause a re-render on
  // its own (only `location` changing should).
  const hasGpsShareRef = useRef(false);

  const setSharedGpsLocation = useCallback((next: SharedLocation) => {
    hasGpsShareRef.current = true;
    setLocation(next);
  }, []);

  const setManualSearchLocation = useCallback((next: SharedLocation) => {
    if (!hasGpsShareRef.current) {
      setLocation(next);
    }
  }, []);

  return (
    <LocationContext.Provider
      value={{location, setSharedGpsLocation, setManualSearchLocation}}>
      {children}
    </LocationContext.Provider>
  );
}

function useSharedLocation(): LocationContextValue {
  const context = useContext(LocationContext);
  if (!context) {
    throw new Error('useSharedLocation must be used within a LocationProvider');
  }
  return context;
}

export {LocationProvider, useSharedLocation};
