/**
 * @format
 */

import React from 'react';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import BottomNavBar, {TabKey} from '../src/navigation/BottomNavBar';

it('reports the pressed tab, including the raised center Chat button', async () => {
  const onTabPress = jest.fn<(tab: TabKey) => void>();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <BottomNavBar activeTab="home" onTabPress={onTabPress} />,
    );
  });

  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Search'}).props.onPress();
  });
  expect(onTabPress).toHaveBeenLastCalledWith('search');

  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Chat'}).props.onPress();
  });
  expect(onTabPress).toHaveBeenLastCalledWith('chat');
});
