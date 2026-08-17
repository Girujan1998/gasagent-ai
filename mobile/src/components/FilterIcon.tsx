import React from 'react';
import {StyleSheet, View} from 'react-native';

// A row of the trigger's icon: a track split by a knob, the knob's
// position (left vs. right flex weight) varying per row so it reads as
// the familiar sliders/adjustments glyph rather than three plain lines.
function SliderRow({
  leftFlex,
  rightFlex,
}: {
  leftFlex: number;
  rightFlex: number;
}): React.JSX.Element {
  return (
    <View style={styles.sliderRow}>
      <View style={[styles.sliderTrack, {flex: leftFlex}]} />
      <View style={styles.sliderKnob} />
      <View style={[styles.sliderTrack, {flex: rightFlex}]} />
    </View>
  );
}

function FilterIcon(): React.JSX.Element {
  return (
    <View style={styles.sliderIcon}>
      <SliderRow leftFlex={3} rightFlex={1} />
      <SliderRow leftFlex={1} rightFlex={2} />
      <SliderRow leftFlex={2} rightFlex={1} />
    </View>
  );
}

const styles = StyleSheet.create({
  sliderIcon: {
    width: 15,
    gap: 2.5,
  },
  sliderRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  sliderTrack: {
    height: 2,
    borderRadius: 1,
    backgroundColor: '#444',
  },
  sliderKnob: {
    width: 3,
    height: 7,
    borderRadius: 1.5,
    backgroundColor: '#444',
    marginHorizontal: 1,
  },
});

export default FilterIcon;
