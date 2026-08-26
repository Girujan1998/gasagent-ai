import React, {createContext, useContext, useState} from 'react';

// Session-only (not persisted to AsyncStorage, unlike FavoritesContext) —
// resets on the next app launch, the same as every other tab's own
// search state already does. The point is just to stop the Gas, EV,
// Chat, and Favorites tabs from each asking for a fresh GPS fix
// independently: once any one of them shares a location, the others can
// read it here instead of prompting again.
export type SharedLocation = {lat: number; lon: number};

type LocationContextValue = {
  location: SharedLocation | null;
  setLocation: (location: SharedLocation) => void;
};

const LocationContext = createContext<LocationContextValue | null>(null);

function LocationProvider({
  children,
}: {
  children: React.ReactNode;
}): React.JSX.Element {
  const [location, setLocation] = useState<SharedLocation | null>(null);

  return (
    <LocationContext.Provider value={{location, setLocation}}>
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
