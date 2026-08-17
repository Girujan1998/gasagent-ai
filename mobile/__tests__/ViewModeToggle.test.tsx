/**
 * @format
 */

import React from 'react';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import ViewModeToggle from '../src/components/ViewModeToggle';

it('calls onChange with "map" when the Map segment is pressed', async () => {
  const onChange = jest.fn();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<ViewModeToggle value="list" onChange={onChange} />);
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show map view'})
      .props.onPress();
  });

  expect(onChange).toHaveBeenCalledWith('map');
});

it('calls onChange with "list" when the List segment is pressed', async () => {
  const onChange = jest.fn();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<ViewModeToggle value="map" onChange={onChange} />);
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show list view'})
      .props.onPress();
  });

  expect(onChange).toHaveBeenCalledWith('list');
});

it('marks the active segment as selected for accessibility', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<ViewModeToggle value="map" onChange={() => {}} />);
  });

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show map view'}).props
      .accessibilityState.selected,
  ).toBe(true);
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show list view'}).props
      .accessibilityState.selected,
  ).toBe(false);
});
