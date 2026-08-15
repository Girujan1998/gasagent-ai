import React, {useState} from 'react';
import {
  Image,
  Modal,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';

import {FuelPrice, GasStation} from '../api/client';
import {milesToKm} from '../utils/distance';
import {freshnessColor} from '../utils/freshness';
import {openDirections} from '../utils/maps';
import {minutesSince, timeAgo} from '../utils/time';

type Props = {
  station: GasStation | null;
  onClose: () => void;
};

function renderStars(rating: number): string {
  const rounded = Math.round(rating);
  return '★'.repeat(rounded) + '☆'.repeat(Math.max(0, 5 - rounded));
}

function NavigateIcon(): React.JSX.Element {
  return (
    <View style={styles.navigateIconCircle}>
      <View style={styles.navigateIconArrow} />
    </View>
  );
}

function BrandLogo({url}: {url: string | null}): React.JSX.Element {
  const [failed, setFailed] = useState(false);

  if (url && !failed) {
    return (
      <Image
        source={{uri: url}}
        style={styles.logo}
        resizeMode="contain"
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <View style={[styles.logo, styles.logoFallback]}>
      <Text style={styles.logoFallbackIcon}>⛽</Text>
    </View>
  );
}

function PriceRow({
  label,
  fuel,
}: {
  label: string;
  fuel: FuelPrice | null;
}): React.JSX.Element | null {
  if (!fuel || (fuel.price == null && !fuel.formatted_price)) {
    return null;
  }

  const priceText =
    fuel.formatted_price ??
    (fuel.price != null ? `$${fuel.price.toFixed(2)}` : '—');
  const minutesAgo = minutesSince(fuel.last_updated);
  const highlight = minutesAgo != null ? freshnessColor(minutesAgo) : null;

  return (
    <View style={styles.priceRow}>
      <Text style={styles.priceRowLabel}>{label}</Text>
      <View style={styles.priceRowValues}>
        <Text
          style={[
            styles.priceRowValue,
            highlight != null && {color: highlight},
          ]}>
          {priceText}
        </Text>
        {fuel.last_updated && (
          <Text
            style={[
              styles.priceRowAge,
              highlight != null && {color: highlight},
            ]}>
            {timeAgo(fuel.last_updated)}
          </Text>
        )}
      </View>
    </View>
  );
}

function StationDetailModal({station, onClose}: Props): React.JSX.Element {
  return (
    <Modal
      visible={station !== null}
      animationType="slide"
      transparent
      onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <TouchableOpacity
            style={styles.closeButton}
            onPress={onClose}
            hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
            accessibilityLabel="Close">
            <Text style={styles.closeIcon}>✕</Text>
          </TouchableOpacity>

          {station && (
            <>
              <View style={styles.header}>
                <BrandLogo url={station.brand_logo_url} />
                <View style={styles.headerText}>
                  <Text style={styles.name} numberOfLines={2}>
                    {station.brand || station.name}
                  </Text>
                  {station.connected_brand && (
                    <View style={styles.connectedBrandRow}>
                      {station.connected_brand_logo_url && (
                        <Image
                          source={{uri: station.connected_brand_logo_url}}
                          style={styles.connectedBrandLogo}
                          resizeMode="contain"
                        />
                      )}
                      <Text style={styles.connectedBrandText}>
                        with {station.connected_brand}
                      </Text>
                    </View>
                  )}
                  {station.address && (
                    <Text style={styles.address}>{station.address}</Text>
                  )}
                  {station.distance_miles != null && (
                    <Text style={styles.distance}>
                      {milesToKm(station.distance_miles).toFixed(1)} km away
                    </Text>
                  )}
                </View>
              </View>

              <View style={styles.pricesSection}>
                <PriceRow label="Regular" fuel={station.regular} />
                <PriceRow label="Midgrade" fuel={station.midgrade} />
                <PriceRow label="Premium" fuel={station.premium} />
                <PriceRow label="Diesel" fuel={station.diesel} />
              </View>

              {station.amenities.length > 0 && (
                <View style={styles.amenitiesSection}>
                  <Text style={styles.amenitiesLabel}>
                    Features & Amenities
                  </Text>
                  <View style={styles.amenitiesList}>
                    {station.amenities.map(amenity => (
                      <View key={amenity} style={styles.amenityChip}>
                        <Text style={styles.amenityChipText}>{amenity}</Text>
                      </View>
                    ))}
                  </View>
                </View>
              )}

              {station.star_rating != null && (
                <Text style={styles.rating}>
                  <Text style={styles.stars}>
                    {renderStars(station.star_rating)}
                  </Text>
                  {` ${station.star_rating.toFixed(1)}`}
                  {station.ratings_count != null
                    ? ` (${station.ratings_count})`
                    : ''}
                </Text>
              )}

              <TouchableOpacity
                style={styles.navigateButton}
                disabled={station.latitude == null || station.longitude == null}
                onPress={() =>
                  station.latitude != null &&
                  station.longitude != null &&
                  openDirections(
                    station.latitude,
                    station.longitude,
                    station.brand || station.name,
                  )
                }
                accessibilityLabel="Navigate to this station">
                <View style={styles.navigateButtonContent}>
                  <NavigateIcon />
                  <Text style={styles.navigateButtonText}>Navigate</Text>
                </View>
              </TouchableOpacity>
            </>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0, 0, 0, 0.4)',
  },
  sheet: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    padding: 20,
    paddingBottom: 32,
  },
  closeButton: {
    position: 'absolute',
    top: 14,
    right: 14,
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f2f2f2',
    zIndex: 1,
  },
  closeIcon: {
    fontSize: 16,
    color: '#555',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginTop: 8,
    paddingRight: 36,
  },
  logo: {
    width: 48,
    height: 48,
    borderRadius: 10,
    marginRight: 12,
    backgroundColor: '#f2f2f2',
  },
  logoFallback: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#dbe6f6',
  },
  logoFallbackIcon: {
    fontSize: 24,
  },
  headerText: {
    flex: 1,
  },
  name: {
    fontSize: 20,
    fontWeight: '700',
  },
  connectedBrandRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 3,
  },
  connectedBrandLogo: {
    width: 14,
    height: 14,
    borderRadius: 3,
    marginRight: 5,
  },
  connectedBrandText: {
    fontSize: 12,
    color: '#888',
    fontStyle: 'italic',
  },
  address: {
    marginTop: 2,
    fontSize: 13,
    color: '#888',
  },
  distance: {
    marginTop: 4,
    fontSize: 13,
    color: '#666',
  },
  pricesSection: {
    marginTop: 20,
  },
  priceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#eee',
  },
  priceRowLabel: {
    fontSize: 14,
    color: '#444',
    textTransform: 'uppercase',
  },
  priceRowValues: {
    alignItems: 'flex-end',
  },
  priceRowValue: {
    fontSize: 17,
    fontWeight: '700',
    color: '#1565c0',
  },
  priceRowAge: {
    fontSize: 11,
    color: '#999',
    marginTop: 1,
  },
  amenitiesSection: {
    marginTop: 20,
  },
  amenitiesLabel: {
    fontSize: 12,
    color: '#888',
    textTransform: 'uppercase',
    marginBottom: 8,
  },
  amenitiesList: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  amenityChip: {
    backgroundColor: '#f2f2f2',
    borderRadius: 12,
    paddingVertical: 5,
    paddingHorizontal: 10,
  },
  amenityChipText: {
    fontSize: 12,
    color: '#444',
  },
  rating: {
    marginTop: 16,
    fontSize: 14,
    color: '#666',
    textAlign: 'center',
  },
  stars: {
    color: '#f5a623',
  },
  navigateButton: {
    marginTop: 20,
    backgroundColor: '#1565c0',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  navigateButtonContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  navigateButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  navigateIconCircle: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 1.5,
    borderColor: '#fff',
    backgroundColor: '#29b6e8',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 8,
  },
  navigateIconArrow: {
    width: 0,
    height: 0,
    borderLeftWidth: 4,
    borderRightWidth: 4,
    borderBottomWidth: 8,
    borderLeftColor: 'transparent',
    borderRightColor: 'transparent',
    borderBottomColor: '#fff',
    transform: [{rotate: '45deg'}],
    marginBottom: 1,
  },
});

export default StationDetailModal;
