/**
 * @format
 */

import {it, expect} from '@jest/globals';

import {timeAgo} from '../src/utils/time';

function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60000).toISOString();
}

it('returns "just now" for under a minute', () => {
  expect(timeAgo(minutesAgo(0))).toBe('just now');
});

it('returns minutes for under an hour', () => {
  expect(timeAgo(minutesAgo(45))).toBe('45m ago');
});

it('returns just hours when exactly on the hour', () => {
  expect(timeAgo(minutesAgo(120))).toBe('2h ago');
});

it('returns hours and minutes when there are leftover minutes', () => {
  expect(timeAgo(minutesAgo(135))).toBe('2h 15m ago');
});

it('returns days once 24 hours have passed', () => {
  expect(timeAgo(minutesAgo(60 * 30))).toBe('1d ago');
});

it('returns "unknown" for a missing or invalid timestamp', () => {
  expect(timeAgo(null)).toBe('unknown');
  expect(timeAgo('not-a-date')).toBe('unknown');
});
