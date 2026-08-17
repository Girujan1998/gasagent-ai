import React, {useCallback, useState} from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';

import {EvStation} from '../api/client';
import EvStationCard from './EvStationCard';
import EvStationDetailModal from './EvStationDetailModal';

type Props = {
  stations: EvStation[];
  loading: boolean;
  error: string | null;
  onLoadMore?: () => void;
  canLoadMore?: boolean;
  loadingMore?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  emptyMessage?: string;
};

function renderSeparator(): React.JSX.Element {
  return <View style={styles.separator} />;
}

function ListFooter({
  canLoadMore,
  loadingMore,
  onLoadMore,
}: {
  canLoadMore: boolean;
  loadingMore: boolean;
  onLoadMore?: () => void;
}): React.JSX.Element | null {
  if (loadingMore) {
    return <ActivityIndicator style={styles.footerSpacing} />;
  }
  if (canLoadMore) {
    return (
      <TouchableOpacity
        style={styles.loadMoreButton}
        onPress={onLoadMore}
        accessibilityLabel="Load more stations">
        <Text style={styles.loadMoreText}>Load More</Text>
      </TouchableOpacity>
    );
  }
  return null;
}

function EvStationList({
  stations,
  loading,
  error,
  onLoadMore,
  canLoadMore = false,
  loadingMore = false,
  refreshing = false,
  onRefresh,
  emptyMessage = 'No EV chargers found nearby.',
}: Props): React.JSX.Element {
  const [selectedStation, setSelectedStation] = useState<EvStation | null>(
    null,
  );

  const renderStation = useCallback(
    ({item}: {item: EvStation}) => (
      <EvStationCard station={item} onPress={() => setSelectedStation(item)} />
    ),
    [],
  );

  if (loading) {
    return <ActivityIndicator style={styles.spacing} />;
  }

  if (error) {
    return <Text style={[styles.message, styles.spacing]}>⚠️ {error}</Text>;
  }

  if (stations.length === 0) {
    return <Text style={[styles.message, styles.spacing]}>{emptyMessage}</Text>;
  }

  return (
    <>
      <FlatList
        style={styles.list}
        contentContainerStyle={styles.listContent}
        data={stations}
        keyExtractor={item => item.station_id}
        renderItem={renderStation}
        ItemSeparatorComponent={renderSeparator}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor="#2e7d32"
          />
        }
        ListFooterComponent={
          <ListFooter
            canLoadMore={canLoadMore}
            loadingMore={loadingMore}
            onLoadMore={onLoadMore}
          />
        }
      />
      <EvStationDetailModal
        station={selectedStation}
        onClose={() => setSelectedStation(null)}
      />
    </>
  );
}

const styles = StyleSheet.create({
  list: {
    flex: 1,
  },
  listContent: {
    paddingVertical: 12,
  },
  separator: {
    height: 10,
  },
  spacing: {
    marginTop: 24,
  },
  footerSpacing: {
    marginVertical: 16,
  },
  loadMoreButton: {
    marginVertical: 16,
    marginHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 8,
    backgroundColor: '#f0f0f0',
    alignItems: 'center',
  },
  loadMoreText: {
    fontSize: 15,
    fontWeight: '600',
    color: '#333',
  },
  message: {
    fontSize: 14,
    color: '#666',
    textAlign: 'center',
    paddingHorizontal: 24,
  },
});

export default EvStationList;
