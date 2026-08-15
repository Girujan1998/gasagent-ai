import React, {useState} from 'react';
import {
  SafeAreaView,
  StatusBar,
  StyleSheet,
  useColorScheme,
} from 'react-native';

import BottomNavBar, {TabKey} from './src/navigation/BottomNavBar';
import FavoritesScreen from './src/screens/FavoritesScreen';
import HomeScreen, {
  INITIAL_PERSISTED_SEARCH,
  PersistedSearch,
} from './src/screens/HomeScreen';
import PlaceholderScreen from './src/screens/PlaceholderScreen';
import SplashScreen from './src/screens/SplashScreen';
import {FavoritesProvider, useFavorites} from './src/store/FavoritesContext';

const PLACEHOLDER_TITLES: Record<
  Exclude<TabKey, 'home' | 'favorites'>,
  string
> = {
  search: 'Search',
  chat: 'Chat',
  personal: 'Personal',
};

function ActiveScreen({
  activeTab,
  persistedSearch,
  onSearchComplete,
}: {
  activeTab: TabKey;
  persistedSearch: PersistedSearch;
  onSearchComplete: (search: PersistedSearch) => void;
}): React.JSX.Element {
  if (activeTab === 'home') {
    return (
      <HomeScreen
        persistedSearch={persistedSearch}
        onSearchComplete={onSearchComplete}
      />
    );
  }
  if (activeTab === 'favorites') {
    return <FavoritesScreen />;
  }
  return <PlaceholderScreen title={PLACEHOLDER_TITLES[activeTab]} />;
}

function AppContent(): React.JSX.Element {
  const {isReady} = useFavorites();
  const [activeTab, setActiveTab] = useState<TabKey>('home');
  // Lifted above HomeScreen so it survives HomeScreen unmounting when the
  // user switches to another tab and back — see the PersistedSearch doc
  // comment in HomeScreen.tsx for what's deliberately left out (pagination).
  const [persistedSearch, setPersistedSearch] = useState<PersistedSearch>(
    INITIAL_PERSISTED_SEARCH,
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
