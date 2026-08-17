import {Linking, Platform} from 'react-native';

export function openDirections(
  latitude: number,
  longitude: number,
  label: string,
): void {
  const latLng = `${latitude},${longitude}`;
  const encodedLabel = encodeURIComponent(label);
  const url =
    // daddr accepts a raw "lat,lng" string as an exact GPS destination.
    // The old `q=label@lat,lng` form runs label as a text search merely
    // biased toward that coordinate — for a station whose name/address
    // doesn't match Apple's own place data well (common for independent
    // or small EV networks), that search can resolve somewhere else
    // entirely instead of the station's real location.
    // The custom `maps://` scheme, not the https://maps.apple.com
    // Universal Link — confirmed live that the https form can fall back to
    // opening as a plain web page in Safari instead of the native app
    // (observed in the simulator; Universal Link handoff to the app isn't
    // guaranteed the way opening the app's own registered scheme is).
    // maps:// has no such fallback: it only ever opens the Maps app itself,
    // or fails outright (handled by the .catch() below) if it isn't there.
    Platform.OS === 'ios'
      ? `maps://?daddr=${latLng}`
      : Platform.OS === 'android'
      ? `geo:0,0?q=${latLng}(${encodedLabel})`
      : `https://www.google.com/maps/search/?api=1&query=${latLng}`;

  Linking.openURL(url).catch(() => {
    // Fall back to a universal web URL if the native maps scheme can't
    // be opened (e.g. no maps app registered for it in this environment).
    Linking.openURL(
      `https://www.google.com/maps/search/?api=1&query=${latLng}`,
    ).catch(() => {});
  });
}
