import React from 'react';
import {StyleSheet, Text, TouchableOpacity, View} from 'react-native';

export type ViewMode = 'list' | 'map';

type Props = {
  value: ViewMode;
  onChange: (value: ViewMode) => void;
};

function Segment({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}): React.JSX.Element {
  return (
    <TouchableOpacity
      style={[styles.segment, active && styles.segmentActive]}
      onPress={onPress}
      accessibilityLabel={`Show ${label.toLowerCase()} view`}
      accessibilityState={{selected: active}}>
      <Text style={[styles.segmentText, active && styles.segmentTextActive]}>
        {label}
      </Text>
    </TouchableOpacity>
  );
}

function ViewModeToggle({value, onChange}: Props): React.JSX.Element {
  return (
    <View style={styles.container}>
      <Segment
        label="List"
        active={value === 'list'}
        onPress={() => onChange('list')}
      />
      <Segment
        label="Map"
        active={value === 'map'}
        onPress={() => onChange('map')}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    height: 34,
    backgroundColor: '#fff',
    borderRadius: 10,
    padding: 2,
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 1},
    shadowOpacity: 0.1,
    shadowRadius: 3,
    elevation: 2,
  },
  segment: {
    paddingHorizontal: 12,
    justifyContent: 'center',
    borderRadius: 8,
  },
  segmentActive: {
    backgroundColor: '#1565c0',
  },
  segmentText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#666',
  },
  segmentTextActive: {
    color: '#fff',
  },
});

export default ViewModeToggle;
