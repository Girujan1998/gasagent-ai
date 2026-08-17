import React from 'react';
import {StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {EvStation} from '../api/client';
import {milesToKm} from '../utils/distance';
import {chargerCountSummary, formatConnectorType} from '../utils/evConnectors';

type Props = {
  station: EvStation;
  onPress?: () => void;
};

function EvStationCard({station, onPress}: Props): React.JSX.Element {
  const summary = chargerCountSummary(station);
  const connectors = station.connector_types.map(formatConnectorType);

  return (
    <TouchableOpacity
      style={styles.card}
      onPress={onPress}
      disabled={!onPress}
      activeOpacity={0.85}
      accessibilityLabel={`View details for ${station.name}`}>
      <View style={styles.headerRow}>
        <View style={styles.iconWrap}>
          <Text style={styles.iconText}>⚡</Text>
        </View>
        <View style={styles.headerTextColumn}>
          <Text style={styles.name} numberOfLines={1}>
            {station.name}
          </Text>
          {station.network && (
            <Text style={styles.network} numberOfLines={1}>
              {station.network}
            </Text>
          )}
        </View>
        {station.distance_miles != null && (
          <Text style={styles.distance}>
            {milesToKm(station.distance_miles).toFixed(1)} km
          </Text>
        )}
      </View>

      {station.address && (
        <Text style={styles.address} numberOfLines={1}>
          {station.address}
        </Text>
      )}

      {(connectors.length > 0 || summary) && (
        <View style={styles.infoRow}>
          {connectors.length > 0 && (
            <Text style={styles.connectors} numberOfLines={1}>
              {connectors.join(' · ')}
            </Text>
          )}
          {summary && (
            <Text style={styles.chargerSummary} numberOfLines={1}>
              {summary}
            </Text>
          )}
        </View>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 14,
    marginHorizontal: 16,
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 1},
    shadowOpacity: 0.1,
    shadowRadius: 3,
    elevation: 2,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  iconWrap: {
    width: 26,
    height: 26,
    borderRadius: 6,
    marginRight: 8,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#e3f3e6',
  },
  iconText: {
    fontSize: 14,
  },
  headerTextColumn: {
    flex: 1,
    marginRight: 8,
  },
  name: {
    fontSize: 16,
    fontWeight: '700',
  },
  network: {
    fontSize: 12,
    color: '#888',
    marginTop: 1,
  },
  distance: {
    fontSize: 13,
    color: '#666',
  },
  address: {
    fontSize: 12,
    color: '#888',
    marginTop: 6,
  },
  infoRow: {
    marginTop: 10,
  },
  connectors: {
    fontSize: 13,
    fontWeight: '600',
    color: '#2e7d32',
  },
  chargerSummary: {
    fontSize: 12,
    color: '#666',
    marginTop: 2,
  },
});

export default EvStationCard;
