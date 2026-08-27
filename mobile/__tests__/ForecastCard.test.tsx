/**
 * @format
 */

import React from 'react';
import {Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect} from '@jest/globals';

import {GasPriceForecast} from '../src/api/client';
import ForecastCard from '../src/components/ForecastCard';

function makeForecast(
  overrides: Partial<GasPriceForecast> = {},
): GasPriceForecast {
  return {
    lat: 43.36,
    lon: -80.31,
    today_average_price: 167.7,
    forecasted_price: 168.9,
    today_average_formatted: '167.7¢',
    forecasted_price_formatted: '168.9¢',
    price_change: 1.2,
    price_change_formatted: '+1.2¢',
    trend_direction: 'up',
    daily_change_pct: 0.0023,
    source: 'ca',
    source_period_end: '2026-07-01',
    stations_sampled: 8,
    today_lowest_price: 158.9,
    today_highest_price: 175.9,
    today_lowest_formatted: '158.9¢',
    today_highest_formatted: '175.9¢',
    forecasted_lowest_price: 159.1,
    forecasted_highest_price: 176.1,
    forecasted_lowest_formatted: '159.1¢',
    forecasted_highest_formatted: '176.1¢',
    lowest_price_change: 0.2,
    lowest_price_change_formatted: '+0.2¢',
    highest_price_change: 0.2,
    highest_price_change_formatted: '+0.2¢',
    ...overrides,
  };
}

// A <Text> with mixed literal/interpolated children (e.g. `Today's
// average: {value}`) renders `children` as an array of parts, not one
// joined string — flatten each node down to a single string so
// `.toContain` works the same regardless of how a given line is composed.
function texts(renderer: ReactTestRenderer): string[] {
  return renderer.root.findAllByType(Text).map(node =>
    ([] as unknown[])
      .concat(node.props.children)
      .filter(value => typeof value === 'string' || typeof value === 'number')
      .join(''),
  );
}

it("shows the forecasted price, trend, today's average, and sample size", async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<ForecastCard forecast={makeForecast()} />);
  });

  const allTexts = texts(renderer!);
  expect(allTexts).toContain('168.9¢');
  expect(allTexts).toContain('Rising');
  expect(allTexts).toContain("Today's average: 167.7¢");
  expect(allTexts.join(' ')).toContain('8 nearby station');
});

it('shows the signed price change alongside the forecasted price', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ForecastCard
        forecast={makeForecast({price_change_formatted: '+1.2¢'})}
      />,
    );
  });

  expect(texts(renderer!)).toContain('+1.2¢');
});

it('omits the change badge when there is no price change to show', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ForecastCard
        forecast={makeForecast({
          price_change: null,
          price_change_formatted: null,
        })}
      />,
    );
  });

  expect(texts(renderer!)).not.toContain('+1.2¢');
});

it('uses singular "station" for a sample of exactly one', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ForecastCard forecast={makeForecast({stations_sampled: 1})} />,
    );
  });

  expect(texts(renderer!).join(' ')).toContain('1 nearby station');
  expect(texts(renderer!).join(' ')).not.toContain('1 nearby stations');
});

it('shows a falling trend in a different color than a rising one', async () => {
  let upRenderer: ReactTestRenderer;
  await act(async () => {
    upRenderer = create(
      <ForecastCard forecast={makeForecast({trend_direction: 'up'})} />,
    );
  });
  let downRenderer: ReactTestRenderer;
  await act(async () => {
    downRenderer = create(
      <ForecastCard forecast={makeForecast({trend_direction: 'down'})} />,
    );
  });

  expect(texts(upRenderer!)).toContain('Rising');
  expect(texts(downRenderer!)).toContain('Falling');

  const upLabel = upRenderer!.root.findByProps({children: 'Rising'});
  const downLabel = downRenderer!.root.findByProps({children: 'Falling'});
  const colorOf = (style: unknown) =>
    ([] as Record<string, unknown>[]).concat(style as never).find(s => s?.color)
      ?.color;
  expect(colorOf(upLabel.props.style)).not.toBe(colorOf(downLabel.props.style));
});

it('colors the change badge by the sign of the price change, not the trend direction', async () => {
  let upRenderer: ReactTestRenderer;
  await act(async () => {
    upRenderer = create(
      <ForecastCard
        forecast={makeForecast({
          trend_direction: 'up',
          price_change: -0.5,
          price_change_formatted: '-0.5¢',
        })}
      />,
    );
  });
  let downRenderer: ReactTestRenderer;
  await act(async () => {
    downRenderer = create(
      <ForecastCard
        forecast={makeForecast({
          trend_direction: 'down',
          price_change: 0.5,
          price_change_formatted: '+0.5¢',
        })}
      />,
    );
  });

  const colorOf = (style: unknown) =>
    ([] as Record<string, unknown>[]).concat(style as never).find(s => s?.color)
      ?.color;

  const fallingBadge = upRenderer!.root.findByProps({children: '-0.5¢'});
  const risingBadge = downRenderer!.root.findByProps({children: '+0.5¢'});
  expect(colorOf(fallingBadge.props.style)).toBe('#2e7d32');
  expect(colorOf(risingBadge.props.style)).toBe('#c62828');
});

it('shows a flat/steady label when the trend direction is flat', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ForecastCard forecast={makeForecast({trend_direction: 'flat'})} />,
    );
  });

  expect(texts(renderer!)).toContain('Steady');
});

it("attributes the forecast to Canada's monthly trend by month and year", async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ForecastCard
        forecast={makeForecast({
          source: 'ca',
          source_period_end: '2026-07-01',
        })}
      />,
    );
  });

  expect(texts(renderer!).join(' ')).toContain(
    "Based on Canada's national price trend for Jul 2026",
  );
});

it("attributes the forecast to the US weekly trend by week", async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ForecastCard
        forecast={makeForecast({
          source: 'us',
          source_period_end: '2026-08-11',
        })}
      />,
    );
  });

  expect(texts(renderer!).join(' ')).toContain(
    'Based on the US national price trend (week of Aug 11)',
  );
});

it('explains when no regional trend data is available', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ForecastCard
        forecast={makeForecast({
          source: 'none',
          source_period_end: null,
          daily_change_pct: null,
          trend_direction: 'flat',
        })}
      />,
    );
  });

  expect(texts(renderer!).join(' ')).toContain(
    'No regional trend data available',
  );
});

it('shows a fallback message when there is no forecasted price to show', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ForecastCard
        forecast={makeForecast({
          today_average_price: null,
          forecasted_price: null,
          today_average_formatted: null,
          forecasted_price_formatted: null,
          stations_sampled: 0,
        })}
      />,
    );
  });

  expect(texts(renderer!).join(' ')).toContain(
    'No nearby stations reported a price to forecast from yet.',
  );
  expect(texts(renderer!)).not.toContain('Rising');
});
