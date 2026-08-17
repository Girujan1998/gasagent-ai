/**
 * @format
 */

import React from 'react';
import {Modal, Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import SortControl from '../src/components/SortControl';
import {SortOption} from '../src/utils/sortStations';

it('defaults to closed, showing the current sort in the trigger', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <SortControl
        value="distance"
        onChange={() => {}}
        primaryFuelLabel="Regular"
        secondaryFuelLabel="Premium"
      />,
    );
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Change sort order'}),
  ).toBeTruthy();
});

it('truncates the trigger label instead of letting it grow past its siblings (e.g. Filter, off-screen)', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <SortControl
        value="price1AndDistance"
        onChange={() => {}}
        primaryFuelLabel="Regular"
        secondaryFuelLabel="Premium"
      />,
    );
  });

  // The trigger's first Text is the label ("Sort: ..."); the second is
  // just the chevron, which doesn't need to truncate.
  const label = renderer!.root
    .findByProps({accessibilityLabel: 'Change sort order'})
    .findAllByType(Text)[0];
  expect(label.props.numberOfLines).toBe(1);
  expect(label.props.ellipsizeMode).toBe('tail');
});

it('opens the sheet and lists all five sort options, without #1/#2 in the text', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <SortControl
        value="distance"
        onChange={() => {}}
        primaryFuelLabel="Regular"
        secondaryFuelLabel="Premium"
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Change sort order'})
      .props.onPress();
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(true);
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Sort by Distance'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({
      accessibilityLabel: 'Sort by Price (Regular)',
    }),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({
      accessibilityLabel: 'Sort by Price (Premium)',
    }),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({
      accessibilityLabel: 'Sort by Price (Regular) and Distance',
    }),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({
      accessibilityLabel: 'Sort by Price (Premium) and Distance',
    }),
  ).toBeTruthy();
});

it('reflects whichever fuel labels are passed in, not fixed Regular/Premium text', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <SortControl
        value="distance"
        onChange={() => {}}
        primaryFuelLabel="Midgrade"
        secondaryFuelLabel="Diesel"
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Change sort order'})
      .props.onPress();
  });

  expect(
    renderer!.root.findByProps({
      accessibilityLabel: 'Sort by Price (Midgrade)',
    }),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({
      accessibilityLabel: 'Sort by Price (Diesel) and Distance',
    }),
  ).toBeTruthy();
});

it('selecting a price-and-distance option calls onChange with that specific option and closes the sheet', async () => {
  const onChange = jest.fn<(value: SortOption) => void>();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <SortControl
        value="distance"
        onChange={onChange}
        primaryFuelLabel="Regular"
        secondaryFuelLabel="Premium"
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Change sort order'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'Sort by Price (Premium) and Distance',
      })
      .props.onPress();
  });

  expect(onChange).toHaveBeenCalledWith('price2AndDistance');
  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);
});

it('tapping the backdrop closes the sheet without changing the sort', async () => {
  const onChange = jest.fn<(value: SortOption) => void>();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <SortControl
        value="price1"
        onChange={onChange}
        primaryFuelLabel="Regular"
        secondaryFuelLabel="Premium"
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Change sort order'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Close sort options'})
      .props.onPress();
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);
  expect(onChange).not.toHaveBeenCalled();
});
