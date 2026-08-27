/**
 * @format
 */

import React from 'react';
import {Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect} from '@jest/globals';

import {GasPriceForecast} from '../src/api/client';
import PriceRangeForecastCard from '../src/components/PriceRangeForecastCard';

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

function texts(renderer: ReactTestRenderer): string[] {
  return renderer.root.findAllByType(Text).map(node =>
    ([] as unknown[])
      .concat(node.props.children)
      .filter(value => typeof value === 'string' || typeof value === 'number')
      .join(''),
  );
}

it('shows the forecasted lowest and highest price', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<PriceRangeForecastCard forecast={makeForecast()} />);
  });

  const allTexts = texts(renderer!);
  expect(allTexts).toContain('159.1¢');
  expect(allTexts).toContain('176.1¢');
});

it("shows today's low and high for comparison", async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<PriceRangeForecastCard forecast={makeForecast()} />);
  });

  const joined = texts(renderer!).join(' ');
  expect(joined).toContain('Today: 158.9¢');
  expect(joined).toContain('Today: 175.9¢');
});

it('shows the signed change for each end of the range', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <PriceRangeForecastCard
        forecast={makeForecast({
          lowest_price_change_formatted: '+0.2¢',
          highest_price_change_formatted: '-0.3¢',
        })}
      />,
    );
  });

  const allTexts = texts(renderer!);
  expect(allTexts).toContain('+0.2¢');
  expect(allTexts).toContain('-0.3¢');
});

it('colors each change by its own sign, not by which column it is in', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <PriceRangeForecastCard
        forecast={makeForecast({
          // A drop at the top of the range and a rise at the bottom of the
          // range — the opposite of what column position alone would imply.
          lowest_price_change: 0.3,
          lowest_price_change_formatted: '+0.3¢',
          highest_price_change: -0.4,
          highest_price_change_formatted: '-0.4¢',
        })}
      />,
    );
  });

  const colorOf = (style: unknown) =>
    ([] as Record<string, unknown>[]).concat(style as never).find(s => s?.color)
      ?.color;

  const lowestChange = renderer!.root.findByProps({children: '+0.3¢'});
  const highestChange = renderer!.root.findByProps({children: '-0.4¢'});
  expect(colorOf(lowestChange.props.style)).toBe('#c62828');
  expect(colorOf(highestChange.props.style)).toBe('#2e7d32');
});

it('does not show any gas station names', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<PriceRangeForecastCard forecast={makeForecast()} />);
  });

  const allTexts = texts(renderer!);
  expect(allTexts).not.toContain('Costco');
  expect(allTexts).not.toContain('Shell');
});

it('shows a fallback message when there is no range to forecast', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <PriceRangeForecastCard
        forecast={makeForecast({
          forecasted_lowest_price: null,
          forecasted_highest_price: null,
          forecasted_lowest_formatted: null,
          forecasted_highest_formatted: null,
          today_lowest_price: null,
          today_highest_price: null,
          today_lowest_formatted: null,
          today_highest_formatted: null,
          lowest_price_change: null,
          lowest_price_change_formatted: null,
          highest_price_change: null,
          highest_price_change_formatted: null,
          stations_sampled: 0,
        })}
      />,
    );
  });

  expect(texts(renderer!).join(' ')).toContain(
    'No nearby stations reported a price to forecast a range from yet.',
  );
});
