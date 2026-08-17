import React, {forwardRef, useImperativeHandle} from 'react';
import {View, ViewProps} from 'react-native';

// react-native-webview requires a real native module that doesn't exist in
// the Jest environment. Standing in for it with a plain View keeps its
// props (source, onMessage, accessibilityLabel, ...) inspectable in tests
// the same way any other component's props are.
//
// injectJavaScript is exposed via the ref like the real component, backed
// by this shared mock rather than a per-instance one — StationMap holds
// its WebView ref internally, so a test has no way to reach a
// per-instance mock; importing this export directly is the only way to
// assert on injected JS. Fine since the app never mounts more than one
// WebView at a time.
export const mockInjectJavaScript = jest.fn();

const WebView = forwardRef<{injectJavaScript: jest.Mock}, ViewProps>(
  function WebView(props, ref) {
    useImperativeHandle(
      ref,
      () => ({injectJavaScript: mockInjectJavaScript}),
      [],
    );
    return <View {...props} />;
  },
);

export default WebView;
