import React from 'react';
import {ActivityIndicator, StyleSheet, Text, View} from 'react-native';

function SplashScreen(): React.JSX.Element {
  return (
    <View style={styles.container}>
      <View style={styles.badge}>
        <Text style={styles.badgeIcon}>⛽</Text>
      </View>
      <Text style={styles.title}>GasAgent.ai</Text>
      <Text style={styles.subtitle}>Find the best fuel prices nearby</Text>
      <ActivityIndicator style={styles.spinner} color="#1565c0" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#fff',
    paddingHorizontal: 24,
  },
  badge: {
    width: 68,
    height: 68,
    borderRadius: 34,
    backgroundColor: '#dbe6f6',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  badgeIcon: {
    fontSize: 32,
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
  },
  subtitle: {
    fontSize: 15,
    color: '#666',
    marginTop: 8,
    textAlign: 'center',
  },
  spinner: {
    marginTop: 20,
  },
});

export default SplashScreen;
