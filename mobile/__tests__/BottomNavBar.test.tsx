/**
 * @format
 */

import React from 'react';
import {Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import BottomNavBar, {TabKey} from '../src/navigation/BottomNavBar';

it('labels the home tab "Gas" with a gas pump icon', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<BottomNavBar activeTab="home" onTabPress={() => {}} />);
  });

  const homeTab = renderer!.root.findByProps({accessibilityLabel: 'Gas'});
  const texts = homeTab.findAllByType(Text).map(node => node.props.children);
  expect(texts).toContain('Gas');
  expect(texts).toContain('⛽');
});

it('labels the search tab "EV" with a charger icon', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<BottomNavBar activeTab="home" onTabPress={() => {}} />);
  });

  const evTab = renderer!.root.findByProps({accessibilityLabel: 'EV'});
  const texts = evTab.findAllByType(Text).map(node => node.props.children);
  expect(texts).toContain('EV');
  // A custom View-built icon (no single emoji reads as "EV charger"),
  // matching how the filter button's icon is built.
  expect(evTab.findByProps({testID: 'ev-charger-icon'})).toBeTruthy();
});

it('reports the pressed tab, including the raised center Chat button', async () => {
  const onTabPress = jest.fn<(tab: TabKey) => void>();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <BottomNavBar activeTab="home" onTabPress={onTabPress} />,
    );
  });

  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'EV'}).props.onPress();
  });
  expect(onTabPress).toHaveBeenLastCalledWith('search');

  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Chat'}).props.onPress();
  });
  expect(onTabPress).toHaveBeenLastCalledWith('chat');
});
