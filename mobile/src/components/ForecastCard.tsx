import React from 'react';
import {StyleSheet, Text, View} from 'react-native';

import {GasPriceForecast} from '../api/client';
import {priceChangeColor} from '../utils/priceChange';

const MONTH_NAMES = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

function formatMonthYear(isoDate: string): string {
  const [year, month] = isoDate.split('-');
  const monthName = MONTH_NAMES[parseInt(month, 10) - 1] ?? month;
  return `${monthName} ${year}`;
}

function formatWeekOf(isoDate: string): string {
  const [, month, day] = isoDate.split('-');
  const monthName = MONTH_NAMES[parseInt(month, 10) - 1] ?? month;
  return `week of ${monthName} ${parseInt(day, 10)}`;
}

// Statistics Canada's series is monthly, EIA's is weekly — each source's
// period_end date is worded to match, rather than a single generic "as of"
// that would misdescribe either one.
function sourceLabel(forecast: GasPriceForecast): string {
  if (forecast.source === 'statcan') {
    return forecast.source_period_end
      ? `Based on Statistics Canada's national trend for ${formatMonthYear(
          forecast.source_period_end,
        )}`
      : "Based on Statistics Canada's national trend";
  }
  if (forecast.source === 'eia') {
    return forecast.source_period_end
      ? `Based on the U.S. EIA's national trend (${formatWeekOf(
          forecast.source_period_end,
        )})`
      : "Based on the U.S. EIA's national trend";
  }
  return "No regional trend data available — showing today's average price";
}

// Framed the way a driver actually cares about it: a falling price is
// good news (green), a rising one is bad news (red) — not a neutral
// up-is-blue/down-is-orange color scheme.
const TREND_DISPLAY: Record<
  GasPriceForecast['trend_direction'],
  {arrow: string; color: string; label: string}
> = {
  up: {arrow: '▲', color: '#c62828', label: 'Rising'},
  down: {arrow: '▼', color: '#2e7d32', label: 'Falling'},
  flat: {arrow: '—', color: '#888', label: 'Steady'},
};

type Props = {
  forecast: GasPriceForecast;
};

function ForecastCard({forecast}: Props): React.JSX.Element {
  const trend = TREND_DISPLAY[forecast.trend_direction];
  const hasForecast = forecast.forecasted_price_formatted != null;

  return (
    <View style={styles.card}>
      <Text style={styles.title}>Tomorrow's Gas Price Forecast</Text>

      {hasForecast ? (
        <>
          <View style={styles.priceRow}>
            <Text style={[styles.arrow, {color: trend.color}]}>
              {trend.arrow}
            </Text>
            <Text style={styles.price}>
              {forecast.forecasted_price_formatted}
            </Text>
            {forecast.price_change_formatted && (
              <Text
                style={[
                  styles.changeBadge,
                  {color: priceChangeColor(forecast.price_change)},
                ]}>
                {forecast.price_change_formatted}
              </Text>
            )}
          </View>
          <Text style={[styles.trendLabel, {color: trend.color}]}>
            {trend.label}
          </Text>
          {forecast.today_average_formatted && (
            <Text style={styles.todayText}>
              Today's average: {forecast.today_average_formatted}
            </Text>
          )}
          <Text style={styles.sampleText}>
            Based on {forecast.stations_sampled} nearby station
            {forecast.stations_sampled === 1 ? '' : 's'}
          </Text>
        </>
      ) : (
        <Text style={styles.emptyText}>
          No nearby stations reported a price to forecast from yet.
        </Text>
      )}

      <Text style={styles.sourceText}>{sourceLabel(forecast)}</Text>
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
  priceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 10,
  },
  arrow: {
    fontSize: 24,
    marginRight: 8,
  },
  price: {
    fontSize: 36,
    fontWeight: '700',
  },
  changeBadge: {
    fontSize: 15,
    fontWeight: '700',
    marginLeft: 8,
  },
  trendLabel: {
    fontSize: 14,
    fontWeight: '600',
    marginTop: 2,
  },
  todayText: {
    fontSize: 13,
    color: '#666',
    marginTop: 10,
  },
  sampleText: {
    fontSize: 12,
    color: '#999',
    marginTop: 2,
  },
  emptyText: {
    fontSize: 14,
    color: '#666',
    marginTop: 10,
  },
  sourceText: {
    fontSize: 11,
    color: '#aaa',
    marginTop: 12,
    fontStyle: 'italic',
  },
});

export default ForecastCard;
