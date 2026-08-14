/**
 * @format
 */

import 'react-native';
import React from 'react';
import App from '../App';

// Note: import explicitly to use the types shipped with jest.
import {it, jest} from '@jest/globals';

// Note: test renderer must be required after react-native.
import {act, create} from 'react-test-renderer';

beforeEach(() => {
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve({status: 'ok', app_name: 'GasAIAgent API'}),
    }),
  ) as unknown as typeof fetch;
});

it('renders correctly', async () => {
  await act(async () => {
    create(<App />);
  });
});
