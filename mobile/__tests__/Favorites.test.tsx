/**
 * @format
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import Geolocation from '@react-native-community/geolocation';
import React from 'react';
import {FlatList} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, beforeEach} from '@jest/globals';

import {GasStation} from '../src/api/client';
import StationCard from '../src/components/StationCard';
import FavoritesScreen from '../src/screens/FavoritesScreen';
import {FavoritesProvider} from '../src/store/FavoritesContext';

const station: GasStation = {
  station_id: 'abc',
  name: 'Test Station',
  brand: 'Shell',
  brand_logo_url: null,
  address: '1 Main St',
  latitude: 41.9,
  longitude: -87.6,
  distance_miles: 1.5,
  regular: null,
  premium: null,
  star_rating: null,
  ratings_count: null,
};

beforeEach(async () => {
  await AsyncStorage.clear();
});

it('adds and removes a station from favorites via the star button', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationCard station={station} />
      </FavoritesProvider>,
    );
  });

  const star = () =>
    renderer!.root.findByProps({accessibilityLabel: 'Add to favorites'});
  const unstar = () =>
    renderer!.root.findByProps({
      accessibilityLabel: 'Remove from favorites',
    });

  expect(star).not.toThrow();

  await act(async () => {
    star().props.onPress();
  });
  expect(unstar).not.toThrow();

  await act(async () => {
    unstar().props.onPress();
  });
  expect(star).not.toThrow();
});

it('hides distance until location is shared, then shows it', async () => {
  await AsyncStorage.setItem('gasaiagent:favorites', JSON.stringify([station]));

  (Geolocation.getCurrentPosition as jest.Mock).mockImplementation(
    (
      success: (pos: {coords: {latitude: number; longitude: number}}) => void,
    ) => {
      success({coords: {latitude: 41.95, longitude: -87.65}});
    },
  );

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <FavoritesScreen />
      </FavoritesProvider>,
    );
  });

  let list = renderer!.root.findByType(FlatList);
  expect(list.props.data).toHaveLength(1);
  expect(list.props.data[0].distance_miles).toBeNull();

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Share your location'})
      .props.onPress();
  });

  list = renderer!.root.findByType(FlatList);
  expect(typeof list.props.data[0].distance_miles).toBe('number');
});
