/**
 * @format
 */

import 'react-native';
import React from 'react';
import App from '../App';

// Note: import explicitly to use the types shipped with jest.
import {it, expect, jest} from '@jest/globals';

// Note: test renderer must be required after react-native.
import {act, create, ReactTestRenderer} from 'react-test-renderer';

import BottomNavBar from '../src/navigation/BottomNavBar';

function healthResponse() {
  return {
    ok: true,
    json: () => Promise.resolve({status: 'ok', app_name: 'GasAgent.ai API'}),
  };
}

function warmupContainerResponse(awake: boolean) {
  return {
    ok: true,
    json: () => Promise.resolve({awake}),
  };
}

beforeEach(() => {
  global.fetch = jest.fn(() =>
    Promise.resolve(healthResponse()),
  ) as unknown as typeof fetch;
});

it('renders correctly', async () => {
  await act(async () => {
    create(<App />);
  });
});

it('shows the app once the startup warmup (health + FlareSolverr container wake) resolves', async () => {
  let call = 0;
  const responses = [healthResponse(), warmupContainerResponse(true)];
  global.fetch = jest.fn(() =>
    Promise.resolve(responses[Math.min(call++, responses.length - 1)]),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<App />);
  });

  expect(renderer!.root.findAllByType(BottomNavBar)).toHaveLength(1);
});

it('lets the user into the app after the warmup timeout, even if the container never wakes', async () => {
  jest.useFakeTimers();
  // Health resolves normally; the container-warmup call hangs forever
  // (e.g. FlareSolverr genuinely crashed) — the app must still proceed
  // once WARMUP_TIMEOUT_MS elapses, rather than blocking indefinitely.
  let call = 0;
  global.fetch = jest.fn(() => {
    call += 1;
    return call === 1
      ? Promise.resolve(healthResponse())
      : new Promise(() => {});
  }) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<App />);
  });

  expect(renderer!.root.findAllByType(BottomNavBar)).toHaveLength(0);

  await act(async () => {
    jest.advanceTimersByTime(65000);
  });

  expect(renderer!.root.findAllByType(BottomNavBar)).toHaveLength(1);

  jest.useRealTimers();
});
