import React from 'react';
import {StyleSheet, Text, View} from 'react-native';

import {GasPriceForecast} from '../api/client';
import {priceChangeColor} from '../utils/priceChange';

type Props = {
  forecast: GasPriceForecast;
};

function PriceRangeForecastCard({forecast}: Props): React.JSX.Element {
  const hasRange =
    forecast.forecasted_lowest_formatted != null &&
    forecast.forecasted_highest_formatted != null;

  return (
    <View style={styles.card}>
      <Text style={styles.title}>Tomorrow's Price Range</Text>

      {hasRange ? (
        <View style={styles.columns}>
          <View style={styles.column}>
            <Text style={[styles.label, styles.lowLabel]}>Lowest</Text>
            <Text style={styles.price}>
              {forecast.forecasted_lowest_formatted}
            </Text>
            {forecast.lowest_price_change_formatted && (
              <Text
                style={[
                  styles.changeText,
                  {color: priceChangeColor(forecast.lowest_price_change)},
                ]}>
                {forecast.lowest_price_change_formatted}
              </Text>
            )}
            {forecast.today_lowest_formatted && (
              <Text style={styles.todayText}>
                Today: {forecast.today_lowest_formatted}
              </Text>
            )}
          </View>

          <View style={styles.divider} />

          <View style={styles.column}>
            <Text style={[styles.label, styles.highLabel]}>Highest</Text>
            <Text style={styles.price}>
              {forecast.forecasted_highest_formatted}
            </Text>
            {forecast.highest_price_change_formatted && (
              <Text
                style={[
                  styles.changeText,
                  {color: priceChangeColor(forecast.highest_price_change)},
                ]}>
                {forecast.highest_price_change_formatted}
              </Text>
            )}
            {forecast.today_highest_formatted && (
              <Text style={styles.todayText}>
                Today: {forecast.today_highest_formatted}
              </Text>
            )}
          </View>
        </View>
      ) : (
        <Text style={styles.emptyText}>
          No nearby stations reported a price to forecast a range from yet.
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 20,
    marginHorizontal: 16,
    marginTop: 16,
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 1},
    shadowOpacity: 0.1,
    shadowRadius: 3,
    elevation: 2,
  },
  title: {
    fontSize: 13,
    color: '#888',
    textTransform: 'uppercase',
    fontWeight: '600',
  },
  columns: {
    flexDirection: 'row',
    marginTop: 14,
  },
  column: {
    flex: 1,
    alignItems: 'center',
  },
  divider: {
    width: StyleSheet.hairlineWidth,
    backgroundColor: '#eee',
    marginHorizontal: 12,
  },
  label: {
    fontSize: 11,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  // Cheaper is good news for a driver, pricier is bad — same green/red
  // convention as ForecastCard's rising/falling trend colors.
  lowLabel: {
    color: '#2e7d32',
  },
  highLabel: {
    color: '#c62828',
  },
  price: {
    fontSize: 24,
    fontWeight: '700',
    marginTop: 4,
  },
  changeText: {
    fontSize: 13,
    marginTop: 2,
    fontWeight: '600',
  },
  todayText: {
    fontSize: 11,
    color: '#999',
    marginTop: 4,
  },
  emptyText: {
    fontSize: 14,
    color: '#666',
    marginTop: 10,
  },
});

export default PriceRangeForecastCard;
