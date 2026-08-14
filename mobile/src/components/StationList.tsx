import React from 'react';
import {
  ActivityIndicator,
  FlatList,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import {GasStation} from '../api/client';
import StationCard from './StationCard';

type Props = {
  stations: GasStation[];
  loading: boolean;
  error: string | null;
  onEndReached?: () => void;
  loadingMore?: boolean;
  emptyMessage?: string;
};

function renderSeparator(): React.JSX.Element {
  return <View style={styles.separator} />;
}

function renderStation({item}: {item: GasStation}): React.JSX.Element {
  return <StationCard station={item} />;
}

function ListFooter({
  loadingMore,
}: {
  loadingMore: boolean;
}): React.JSX.Element | null {
  if (!loadingMore) {
    return null;
  }
  return <ActivityIndicator style={styles.footerSpacing} />;
}

function StationList({
  stations,
  loading,
  error,
  onEndReached,
  loadingMore = false,
  emptyMessage = 'No stations found nearby.',
}: Props): React.JSX.Element {
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
    <FlatList
      style={styles.list}
      contentContainerStyle={styles.listContent}
      data={stations}
      keyExtractor={item => item.station_id}
      renderItem={renderStation}
      ItemSeparatorComponent={renderSeparator}
      onEndReached={onEndReached}
      onEndReachedThreshold={0.5}
      ListFooterComponent={<ListFooter loadingMore={loadingMore} />}
    />
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
  message: {
    fontSize: 14,
    color: '#666',
    textAlign: 'center',
    paddingHorizontal: 24,
  },
});

export default StationList;
