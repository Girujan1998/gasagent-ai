import React, {useState} from 'react';
import {
  SafeAreaView,
  StatusBar,
  StyleSheet,
  useColorScheme,
} from 'react-native';

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
    />
  );
}

function AppContent(): React.JSX.Element {
  const {isReady} = useFavorites();
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

  if (!isReady) {
    return <SplashScreen />;
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
