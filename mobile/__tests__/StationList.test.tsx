/**
 * @format
 */

import React from 'react';
import {Linking, Modal, Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import {GasStation} from '../src/api/client';
import StationList from '../src/components/StationList';
import {FavoritesProvider} from '../src/store/FavoritesContext';

const station: GasStation = {
  station_id: 'abc',
  name: 'Test Station',
  brand: 'Shell',
  brand_logo_url: null,
  connected_brand: 'Circle K',
  connected_brand_logo_url: null,
  address: '1 Main St, Springfield, IL',
  latitude: 41.9,
  longitude: -87.6,
  distance_miles: 1.5,
  regular: {price: 3.19, formatted_price: '$3.19', last_updated: null},
  midgrade: {price: 3.49, formatted_price: '$3.49', last_updated: null},
  premium: {price: 3.79, formatted_price: '$3.79', last_updated: null},
  diesel: {price: 3.99, formatted_price: '$3.99', last_updated: null},
  star_rating: 4.5,
  ratings_count: 120,
  amenities: ['Car Wash', 'Restrooms'],
};

it('opens a detail modal on tap, and closes it via the close button', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationList stations={[station]} loading={false} error={null} />
      </FavoritesProvider>,
    );
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);

  // Each Text node's children joined into one string (a Text like
  // `{value} km` renders as two separate children, not one string).
  const joinedTexts = () =>
    renderer!.root.findAllByType(Text).map(node =>
      ([] as unknown[])
        .concat(node.props.children)
        .filter(value => typeof value === 'string')
        .join(''),
    );

  // The card itself (before opening anything) shows distance in
  // kilometers, not miles — 1.5 miles.
  expect(joinedTexts()).toContain('2.4 km');
  // The connected brand shows as secondary text, not as the primary name.
  expect(joinedTexts()).toContain('with Circle K');

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'View details for Shell'})
      .props.onPress();
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(true);
  const textNodes = joinedTexts();

  // All four fuel prices should be present in the expanded view.
  expect(textNodes).toEqual(
    expect.arrayContaining(['$3.19', '$3.49', '$3.79', '$3.99']),
  );
  // The modal also shows kilometers, not miles.
  expect(textNodes).toContain('2.4 km away');
  // ...and the connected brand too.
  expect(textNodes).toContain('with Circle K');
  // ...and the station's amenities.
  expect(textNodes).toEqual(
    expect.arrayContaining(['Car Wash', 'Restrooms']),
  );

  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Close'}).props.onPress();
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);
});

it('hides the amenities section for a station with none reported', async () => {
  const stationWithNoAmenities: GasStation = {...station, amenities: []};

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationList
          stations={[stationWithNoAmenities]}
          loading={false}
          error={null}
        />
      </FavoritesProvider>,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'View details for Shell'})
      .props.onPress();
  });

  expect(
    renderer!.root.findAllByProps({children: 'Features & Amenities'}),
  ).toHaveLength(0);
});

it('opens the device maps app with the station location when Navigate is pressed', async () => {
  const openURLSpy = jest
    .spyOn(Linking, 'openURL')
    .mockResolvedValue(undefined as never);

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <StationList stations={[station]} loading={false} error={null} />
      </FavoritesProvider>,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'View details for Shell'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Navigate to this station'})
      .props.onPress();
  });

  expect(openURLSpy).toHaveBeenCalledTimes(1);
  const url = openURLSpy.mock.calls[0][0];
  expect(url).toContain('41.9');
  expect(url).toContain('-87.6');

  openURLSpy.mockRestore();
});
