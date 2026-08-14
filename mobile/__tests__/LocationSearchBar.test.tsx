/**
 * @format
 */

import React from 'react';
import {TextInput} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import LocationSearchBar, {
  LocationQuery,
} from '../src/components/LocationSearchBar';

it('submits a typed city/postal code search', async () => {
  const onSearch = jest.fn<(query: LocationQuery) => void>();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<LocationSearchBar onSearch={onSearch} />);
  });

  const input = renderer!.root.findByType(TextInput);
  await act(async () => {
    input.props.onChangeText('90210');
  });

  const searchButton = renderer!.root.findByProps({
    accessibilityLabel: 'Search',
  });
  await act(async () => {
    searchButton.props.onPress();
  });

  expect(onSearch).toHaveBeenCalledWith({type: 'text', value: '90210'});
});

it('restores a persisted text query on mount and can clear it', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <LocationSearchBar initialQuery={{type: 'text', value: '60614'}} />,
    );
  });

  expect(renderer!.root.findByType(TextInput).props.value).toBe('60614');

  const clearButton = renderer!.root.findByProps({
    accessibilityLabel: 'Clear search',
  });
  await act(async () => {
    clearButton.props.onPress();
  });

  expect(renderer!.root.findByType(TextInput).props.value).toBe('');
  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Clear search'}),
  ).toThrow();
});

it('restores a persisted coordinate query as a location label on mount', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <LocationSearchBar
        initialQuery={{type: 'coordinates', latitude: 41.85, longitude: -87.65}}
      />,
    );
  });

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Clear search'}),
  ).toBeTruthy();
});

it('does not show the clear button when there is nothing to clear', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<LocationSearchBar />);
  });

  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Clear search'}),
  ).toThrow();
});
