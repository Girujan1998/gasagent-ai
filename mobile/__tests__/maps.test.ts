/**
 * @format
 */

import {Linking, Platform} from 'react-native';
import {it, expect, jest} from '@jest/globals';

import {openDirections} from '../src/utils/maps';

it('opens the native Maps app directly on iOS, at the exact coordinate, not a text search', async () => {
  Platform.OS = 'ios';
  const openURLSpy = jest
    .spyOn(Linking, 'openURL')
    .mockResolvedValue(undefined as never);

  openDirections(41.85, -87.65, 'MTOCP');

  expect(openURLSpy).toHaveBeenCalledTimes(1);
  const url = openURLSpy.mock.calls[0][0];
  // The custom maps:// scheme only ever opens the Maps app itself — unlike
  // the https://maps.apple.com Universal Link, which was confirmed live to
  // sometimes fall back to a plain web page in Safari instead. daddr with
  // a raw "lat,lng" value is also an exact GPS destination, unlike the old
  // `q=<label>@<lat,lng>` form, which ran a text search that a mismatched
  // station name could derail to the wrong place.
  expect(url).toBe('maps://?daddr=41.85,-87.65');
  expect(url).not.toContain('MTOCP');

  openURLSpy.mockRestore();
});

it("still labels the pin on Android, since Android's geo URI treats q=lat,lng(label) as an exact point, not a search", async () => {
  Platform.OS = 'android';
  const openURLSpy = jest
    .spyOn(Linking, 'openURL')
    .mockResolvedValue(undefined as never);

  openDirections(41.85, -87.65, 'MTOCP');

  expect(openURLSpy).toHaveBeenCalledTimes(1);
  const url = openURLSpy.mock.calls[0][0];
  expect(url).toBe('geo:0,0?q=41.85,-87.65(MTOCP)');

  openURLSpy.mockRestore();
});

it('falls back to a coordinate-only Google Maps URL if the native scheme fails to open', async () => {
  Platform.OS = 'ios';
  const openURLSpy = jest
    .spyOn(Linking, 'openURL')
    .mockRejectedValueOnce(new Error('no maps app'))
    .mockResolvedValueOnce(undefined as never);

  openDirections(41.85, -87.65, 'MTOCP');
  // Let both the initial call and its .catch() fallback resolve.
  await Promise.resolve();
  await Promise.resolve();

  expect(openURLSpy).toHaveBeenCalledTimes(2);
  expect(openURLSpy.mock.calls[1][0]).toBe(
    'https://www.google.com/maps/search/?api=1&query=41.85,-87.65',
  );

  openURLSpy.mockRestore();
});
