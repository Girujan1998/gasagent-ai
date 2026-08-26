import React, {useEffect, useState} from 'react';
import {
  SafeAreaView,
  StatusBar,
  StyleSheet,
  useColorScheme,
} from 'react-native';

import {getHealth, warmupFlareSolverrContainer} from './src/api/client';
import BottomNavBar, {TabKey} from './src/navigation/BottomNavBar';
import ChatScreen, {
  INITIAL_PERSISTED_CHAT,
  PersistedChat,
} from './src/screens/ChatScreen';
import EvScreen, {
  INITIAL_PERSISTED_EV_SEARCH,
  PersistedEvSearch,
} from './src/screens/EvScreen';
import FavoritesScreen from './src/screens/FavoritesScreen';
import HomeScreen, {
  INITIAL_PERSISTED_SEARCH,
  PersistedSearch,
} from './src/screens/HomeScreen';
import NotificationsScreen, {
  INITIAL_PERSISTED_FORECAST,
  PersistedForecast,
} from './src/screens/NotificationsScreen';
import SplashScreen from './src/screens/SplashScreen';
import {FavoritesProvider, useFavorites} from './src/store/FavoritesContext';

// This only waits on waking FlareSolverr's own container, NOT a real
// GasBuddy challenge-solve (~55-60s) — an earlier version of this warmup
// ran a real gas search to also prime a GasBuddy session token, but that
// fired unconditionally on every app launch regardless of whether the
// user ever searched for gas that session, adding real load against
// GasBuddy's own request-rate limit for zero benefit on EV/Chat-only
// sessions. The user's first real gas search still pays for the actual
// challenge-solve itself — this bound only needs margin over a
// container wake, not a full solve.
//
// The backend also best-effort restarts FlareSolverr's own Render
// service on every launch (confirmed live: a fresh restart can succeed
// where an already-awake container kept failing) and then polls for the
// new container to answer, which can itself take up to ~35s — this must
// stay comfortably above that, or the app would proceed before the
// backend's own warmup call even finishes. Not indefinite, though — EV
// search and Chat don't depend on FlareSolverr at all, so there's no
// reason to strand the user if it's genuinely crashed rather than just
// cold (Render can take a couple of minutes to notice and restart it).
const WARMUP_TIMEOUT_MS = 45000;

function ActiveScreen({
  activeTab,
  persistedSearch,
  onSearchComplete,
  persistedEvSearch,
  onEvSearchComplete,
  persistedForecast,
  onForecastComplete,
  persistedChat,
  onChatComplete,
}: {
  activeTab: TabKey;
  persistedSearch: PersistedSearch;
  onSearchComplete: (
    search: PersistedSearch | ((prev: PersistedSearch) => PersistedSearch),
  ) => void;
  persistedEvSearch: PersistedEvSearch;
  onEvSearchComplete: (search: PersistedEvSearch) => void;
  persistedForecast: PersistedForecast;
  onForecastComplete: (forecast: PersistedForecast) => void;
  persistedChat: PersistedChat;
  onChatComplete: (chat: PersistedChat) => void;
}): React.JSX.Element {
  if (activeTab === 'home') {
    return (
      <HomeScreen
        persistedSearch={persistedSearch}
        onSearchComplete={onSearchComplete}
      />
    );
  }
  if (activeTab === 'search') {
    return (
      <EvScreen
        persistedSearch={persistedEvSearch}
        onSearchComplete={onEvSearchComplete}
      />
    );
  }
  if (activeTab === 'favorites') {
    return <FavoritesScreen />;
  }
  if (activeTab === 'personal') {
    return (
      <NotificationsScreen
        searchLocation={persistedSearch.searchLocation}
        locationQuery={persistedSearch.query}
        persistedForecast={persistedForecast}
        onForecastComplete={onForecastComplete}
      />
    );
  }
  return (
    <ChatScreen
      persistedChat={persistedChat}
      onChatComplete={onChatComplete}
      gasTabLocation={persistedSearch.searchLocation}
      evTabLocation={persistedEvSearch.searchLocation}
    />
  );
}

function AppContent(): React.JSX.Element {
  const {isReady} = useFavorites();
  // Wakes the backend + FlareSolverr's container on launch (see the
  // module comment on WARMUP_TIMEOUT_MS for why this stops short of a
  // real gas search). Runs once per app launch, not on every tab switch
  // — this effect lives on AppContent's own mount, same lifetime as
  // isReady above.
  const [warmupDone, setWarmupDone] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>('home');
  // Lifted above HomeScreen/EvScreen so each survives its screen unmounting
  // when the user switches to another tab and back — see the
  // PersistedSearch doc comment in HomeScreen.tsx for what's deliberately
  // left out (pagination).
  const [persistedSearch, setPersistedSearch] = useState<PersistedSearch>(
    INITIAL_PERSISTED_SEARCH,
  );
  const [persistedEvSearch, setPersistedEvSearch] = useState<PersistedEvSearch>(
    INITIAL_PERSISTED_EV_SEARCH,
  );
  const [persistedForecast, setPersistedForecast] = useState<PersistedForecast>(
    INITIAL_PERSISTED_FORECAST,
  );
  const [persistedChat, setPersistedChat] = useState<PersistedChat>(
    INITIAL_PERSISTED_CHAT,
  );

  useEffect(() => {
    let cancelled = false;
    const finish = () => {
      if (!cancelled) {
        setWarmupDone(true);
      }
    };

    const timeoutId = setTimeout(finish, WARMUP_TIMEOUT_MS);

    (async () => {
      try {
        await getHealth();
        if (cancelled) {
          return;
        }
        await warmupFlareSolverrContainer();
      } catch {
        // Backend unreachable, or FlareSolverr's container didn't wake in
        // time (e.g. genuinely crashed rather than just cold) — proceed
        // into the app regardless; the existing per-screen error handling
        // already covers a backend/gas search that isn't actually ready.
      } finally {
        clearTimeout(timeoutId);
        finish();
      }
    })();

    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, []);

  if (!isReady || !warmupDone) {
    return <SplashScreen statusText="Waking up the server…" />;
  }

  return (
    <>
      <ActiveScreen
        activeTab={activeTab}
        persistedSearch={persistedSearch}
        onSearchComplete={setPersistedSearch}
        persistedEvSearch={persistedEvSearch}
        onEvSearchComplete={setPersistedEvSearch}
        persistedForecast={persistedForecast}
        onForecastComplete={setPersistedForecast}
        persistedChat={persistedChat}
        onChatComplete={setPersistedChat}
      />

      <BottomNavBar activeTab={activeTab} onTabPress={setActiveTab} />
    </>
  );
}

function App(): React.JSX.Element {
  const isDarkMode = useColorScheme() === 'dark';

  return (
    <FavoritesProvider>
      <SafeAreaView style={styles.container}>
        <StatusBar barStyle={isDarkMode ? 'light-content' : 'dark-content'} />
        <AppContent />
      </SafeAreaView>
    </FavoritesProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
});

export default App;
