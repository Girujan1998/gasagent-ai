/**
 * @format
 */

import {it, expect} from '@jest/globals';

import {moveInArray} from '../src/utils/reorder';

it('moves an item earlier in the array, shifting the ones in between later', () => {
  expect(moveInArray(['a', 'b', 'c', 'd'], 3, 1)).toEqual(['a', 'd', 'b', 'c']);
});

it('moves an item later in the array, shifting the ones in between earlier', () => {
  expect(moveInArray(['a', 'b', 'c', 'd'], 0, 2)).toEqual(['b', 'c', 'a', 'd']);
});

it('returns the same array (by content) when fromIndex equals toIndex', () => {
  const items = ['a', 'b', 'c'];
  expect(moveInArray(items, 1, 1)).toEqual(items);
});

it('leaves the array unchanged when either index is out of bounds', () => {
  const items = ['a', 'b', 'c'];
  expect(moveInArray(items, -1, 1)).toBe(items);
  expect(moveInArray(items, 1, 3)).toBe(items);
  expect(moveInArray(items, 3, 1)).toBe(items);
});

it('does not mutate the original array', () => {
  const items = ['a', 'b', 'c'];
  moveInArray(items, 0, 2);
  expect(items).toEqual(['a', 'b', 'c']);
});
