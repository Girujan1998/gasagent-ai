/**
 * @format
 */

import {it, expect} from '@jest/globals';

import {freshnessColor} from '../src/utils/freshness';

it('returns pure green at 0 minutes', () => {
  expect(freshnessColor(0)).toBe('rgb(27, 122, 61)');
});

it('returns pure amber at 30 minutes', () => {
  expect(freshnessColor(30)).toBe('rgb(183, 121, 31)');
});

it('returns pure orange at 60 minutes', () => {
  expect(freshnessColor(60)).toBe('rgb(194, 84, 12)');
});

it('returns pure red at 90 minutes', () => {
  expect(freshnessColor(90)).toBe('rgb(185, 28, 28)');
});

it('holds flat red past 90 minutes', () => {
  expect(freshnessColor(150)).toBe('rgb(185, 28, 28)');
  expect(freshnessColor(90)).toBe(freshnessColor(500));
});

it('interpolates smoothly between stops instead of jumping', () => {
  const quarter = freshnessColor(15); // halfway between the 0 and 30 stops
  expect(quarter).toBe('rgb(105, 122, 46)');
  expect(quarter).not.toBe(freshnessColor(0));
  expect(quarter).not.toBe(freshnessColor(30));
});

it('clamps negative input to the freshest color', () => {
  expect(freshnessColor(-5)).toBe(freshnessColor(0));
});
