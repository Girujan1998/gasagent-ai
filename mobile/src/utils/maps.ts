import {Linking, Platform} from 'react-native';

export function openDirections(
  latitude: number,
  longitude: number,
  label: string,
): void {
  const latLng = `${latitude},${longitude}`;
  const encodedLabel = encodeURIComponent(label);
  const url =
    Platform.OS === 'ios'
      ? `maps:0,0?q=${encodedLabel}@${latLng}`
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
