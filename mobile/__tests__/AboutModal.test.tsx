/**
 * @format
 */

import React from 'react';
import {Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect} from '@jest/globals';

import AboutModal from '../src/components/AboutModal';

function texts(renderer: ReactTestRenderer): string[] {
  return renderer.root.findAllByType(Text).map(node =>
    ([] as unknown[])
      .concat(node.props.children)
      .filter(value => typeof value === 'string')
      .join(''),
  );
}

it('is hidden until the info button is pressed, then shows the non-affiliation disclaimer', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<AboutModal />);
  });

  expect(texts(renderer!)).not.toContain('About GasAgent.ai');

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'About this app'})
      .props.onPress();
  });

  const allTexts = texts(renderer!);
  expect(allTexts).toContain('About GasAgent.ai');
  expect(allTexts.join(' ')).toContain('not affiliated with');
  expect(allTexts).toContain('GasBuddy');
});

it('closes when the close button is pressed', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<AboutModal />);
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'About this app'})
      .props.onPress();
  });
  expect(texts(renderer!)).toContain('About GasAgent.ai');

  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Close'}).props.onPress();
  });
  expect(texts(renderer!)).not.toContain('About GasAgent.ai');
});
