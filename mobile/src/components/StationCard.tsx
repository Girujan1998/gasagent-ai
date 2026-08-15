import React, {useState} from 'react';
import {Image, StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {FuelPrice, GasStation} from '../api/client';
import {useFavorites} from '../store/FavoritesContext';
import {milesToKm} from '../utils/distance';
import {freshnessColor} from '../utils/freshness';
import {minutesSince, timeAgo} from '../utils/time';

type Props = {
  station: GasStation;
  onPress?: () => void;
};

function renderStars(rating: number): string {
  const rounded = Math.round(rating);
  return '★'.repeat(rounded) + '☆'.repeat(Math.max(0, 5 - rounded));
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

function PriceColumn({
  label,
  fuel,
}: {
  label: string;
  fuel: FuelPrice | null;
}): React.JSX.Element {
  const priceText =
    fuel?.formatted_price ??
    (fuel?.price != null ? `$${fuel.price.toFixed(2)}` : '—');
  const minutesAgo = minutesSince(fuel?.last_updated);
  const highlight = minutesAgo != null ? freshnessColor(minutesAgo) : null;

  return (
    <View style={styles.priceColumn}>
      <Text style={styles.priceLabel}>{label}</Text>
      <Text
        style={[styles.priceValue, highlight != null && {color: highlight}]}>
        {priceText}
      </Text>
      {fuel?.last_updated && (
        <Text
          style={[styles.priceAge, highlight != null && {color: highlight}]}>
          {timeAgo(fuel.last_updated)}
        </Text>
      )}
    </View>
  );
}

function StationCard({station, onPress}: Props): React.JSX.Element {
  const {isFavorite, toggleFavorite} = useFavorites();
  const favorited = isFavorite(station.station_id);

  return (
    <TouchableOpacity
      style={styles.card}
      onPress={onPress}
      disabled={!onPress}
      activeOpacity={0.85}
      accessibilityLabel={`View details for ${station.brand || station.name}`}>
      <View style={styles.headerRow}>
        <View style={styles.brandRow}>
          <BrandLogo url={station.brand_logo_url} />
          <View style={styles.brandTextColumn}>
            <Text style={styles.name} numberOfLines={1}>
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
                <Text style={styles.connectedBrandText} numberOfLines={1}>
                  with {station.connected_brand}
                </Text>
              </View>
            )}
          </View>
        </View>

        <View style={styles.headerRight}>
          {station.distance_miles != null && (
            <Text style={styles.distance}>
              {milesToKm(station.distance_miles).toFixed(1)} km
            </Text>
          )}
          <TouchableOpacity
            onPress={() => toggleFavorite(station)}
            hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
            accessibilityLabel={
              favorited ? 'Remove from favorites' : 'Add to favorites'
            }>
            <Text style={[styles.star, favorited && styles.starFilled]}>
              {favorited ? '★' : '☆'}
            </Text>
          </TouchableOpacity>
        </View>
      </View>

      {station.address && (
        <Text style={styles.address} numberOfLines={1}>
          {station.address}
        </Text>
      )}

      <View style={styles.pricesRow}>
        <PriceColumn label="Regular" fuel={station.regular} />
        <PriceColumn label="Premium" fuel={station.premium} />
      </View>

      {station.star_rating != null && (
        <Text style={styles.rating}>
          <Text style={styles.stars}>{renderStars(station.star_rating)}</Text>
          {` ${station.star_rating.toFixed(1)}`}
          {station.ratings_count != null ? ` (${station.ratings_count})` : ''}
        </Text>
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
    justifyContent: 'space-between',
  },
  brandRow: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    marginRight: 8,
  },
  logo: {
    width: 26,
    height: 26,
    borderRadius: 6,
    marginRight: 8,
    backgroundColor: '#f2f2f2',
  },
  logoFallback: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#dbe6f6',
  },
  logoFallbackIcon: {
    fontSize: 14,
  },
  brandTextColumn: {
    flex: 1,
  },
  name: {
    fontSize: 16,
    fontWeight: '700',
  },
  connectedBrandRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 2,
  },
  connectedBrandLogo: {
    width: 12,
    height: 12,
    borderRadius: 3,
    marginRight: 4,
  },
  connectedBrandText: {
    fontSize: 11,
    color: '#888',
    fontStyle: 'italic',
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  distance: {
    fontSize: 13,
    color: '#666',
    marginRight: 8,
  },
  star: {
    fontSize: 22,
    color: '#ccc',
  },
  starFilled: {
    color: '#f5a623',
  },
  address: {
    fontSize: 12,
    color: '#888',
    marginTop: 2,
  },
  pricesRow: {
    flexDirection: 'row',
    marginTop: 12,
  },
  priceColumn: {
    flex: 1,
    alignItems: 'center',
  },
  priceLabel: {
    fontSize: 11,
    color: '#888',
    textTransform: 'uppercase',
  },
  priceValue: {
    fontSize: 18,
    fontWeight: '700',
    marginTop: 2,
    color: '#1565c0',
  },
  priceAge: {
    fontSize: 11,
    color: '#999',
    marginTop: 2,
  },
  rating: {
    marginTop: 12,
    fontSize: 13,
    color: '#666',
    textAlign: 'center',
  },
  stars: {
    color: '#f5a623',
  },
});

export default StationCard;
