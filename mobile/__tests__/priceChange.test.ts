/**
 * @format
 */

import {it, expect} from '@jest/globals';

import {priceChangeColor} from '../src/utils/priceChange';

it('colors a price increase red', () => {
  expect(priceChangeColor(1.2)).toBe('#c62828');
});

it('colors a price decrease green', () => {
  expect(priceChangeColor(-1.2)).toBe('#2e7d32');
});

it('colors no change and a null change gray', () => {
  expect(priceChangeColor(0)).toBe('#888');
  expect(priceChangeColor(null)).toBe('#888');
});
