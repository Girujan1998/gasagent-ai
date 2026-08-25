import React, {useEffect, useState} from 'react';
import {
  SafeAreaView,
  StatusBar,
  StyleSheet,
  useColorScheme,
} from 'react-native';

import {getHealth, warmupGasSearch} from './src/api/client';
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

// A cold FlareSolverr solve can take ~55-60s, so this bound needs real
// margin above that to actually cover the normal case (a tighter bound
// was cutting the splash screen short right before warmup would have
// finished). Not indefinite, though — EV search and Chat don't depend on
// FlareSolverr at all, so there's no reason to strand the user for
// minutes if it's genuinely crashed rather than just cold (Render can
// take a couple of minutes to notice and restart it) — a gas search
// attempted before it's actually ready just shows its existing
// "temporarily blocking" retry message, same as before this existed.
const WARMUP_TIMEOUT_MS = 90000;

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
  // Wakes the backend + FlareSolverr on launch (see the module comment on
  // WARMUP_TIMEOUT_MS) rather than waiting for the user's own first gas
  // search to pay a cold-start cost. Runs once per app launch, not on
  // every tab switch — this effect lives on AppContent's own mount, same
  // lifetime as isReady above.
  const [warmupDone, setWarmupDone] = useState(false);
  const [warmupStatusText, setWarmupStatusText] = useState(
    'Waking up the server…',
  );
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
        setWarmupStatusText('Getting ready for gas prices…');
        await warmupGasSearch();
      } catch {
        // Backend unreachable, or the gas warmup itself didn't succeed in
        // time (e.g. FlareSolverr genuinely crashed) — proceed into the
        // app regardless; the existing per-screen error handling already
        // covers a backend/gas search that isn't actually ready.
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
    return <SplashScreen statusText={warmupStatusText} />;
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
