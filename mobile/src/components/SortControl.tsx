import React, {useMemo, useState} from 'react';
import {Modal, StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {SortOption} from '../utils/sortStations';

type Props = {
  value: SortOption;
  onChange: (value: SortOption) => void;
  primaryFuelLabel: string;
  secondaryFuelLabel: string;
};

function SortControl({
  value,
  onChange,
  primaryFuelLabel,
  secondaryFuelLabel,
}: Props): React.JSX.Element {
  const [open, setOpen] = useState(false);

  const options = useMemo(
    (): {value: SortOption; label: string}[] => [
      {value: 'distance', label: 'Distance'},
      {value: 'price1', label: `Price (${primaryFuelLabel})`},
      {value: 'price2', label: `Price (${secondaryFuelLabel})`},
      {
        value: 'price1AndDistance',
        label: `Price (${primaryFuelLabel}) and Distance`,
      },
      {
        value: 'price2AndDistance',
        label: `Price (${secondaryFuelLabel}) and Distance`,
      },
    ],
    [primaryFuelLabel, secondaryFuelLabel],
  );

  const currentLabel = options.find(option => option.value === value)?.label;

  return (
    <>
      <TouchableOpacity
        style={styles.trigger}
        onPress={() => setOpen(true)}
        accessibilityLabel="Change sort order">
        <Text style={styles.triggerText} numberOfLines={1} ellipsizeMode="tail">
          Sort: {currentLabel}
        </Text>
        <Text style={styles.chevron}>▾</Text>
      </TouchableOpacity>

      <Modal
        visible={open}
        transparent
        animationType="slide"
        onRequestClose={() => setOpen(false)}>
        <TouchableOpacity
          style={styles.backdrop}
          activeOpacity={1}
          onPress={() => setOpen(false)}
          accessibilityLabel="Close sort options">
          <View style={styles.sheet}>
            <TouchableOpacity
              style={styles.closeButton}
              onPress={() => setOpen(false)}
              hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
              accessibilityLabel="Close">
              <Text style={styles.closeIcon}>✕</Text>
            </TouchableOpacity>

            <Text style={styles.sheetTitle}>Sort by</Text>

            {options.map(option => {
              const selected = option.value === value;
              return (
                <TouchableOpacity
                  key={option.value}
                  style={styles.optionRow}
                  onPress={() => {
                    onChange(option.value);
                    setOpen(false);
                  }}
                  accessibilityLabel={`Sort by ${option.label}`}>
                  <Text
                    style={[
                      styles.optionText,
                      selected && styles.optionTextSelected,
                    ]}>
                    {option.label}
                  </Text>
                  {selected && <Text style={styles.checkmark}>✓</Text>}
                </TouchableOpacity>
              );
            })}
          </View>
        </TouchableOpacity>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  trigger: {
    flexDirection: 'row',
    alignItems: 'center',
    height: 40,
    backgroundColor: '#fff',
    borderRadius: 12,
    paddingHorizontal: 12,
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 1},
    shadowOpacity: 0.1,
    shadowRadius: 3,
    elevation: 2,
    // Lets the label truncate (rather than grow past its siblings and
    // push them off-screen) on longer options like "Price (Regular) and
    // Distance" — minWidth: 0 is required for Yoga to actually shrink it
    // below the label's own content size.
    flexShrink: 1,
    minWidth: 0,
  },
  triggerText: {
    fontSize: 13,
    color: '#444',
    fontWeight: '600',
    flexShrink: 1,
  },
  chevron: {
    fontSize: 12,
    color: '#888',
    marginLeft: 4,
    flexShrink: 0,
  },
  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0, 0, 0, 0.4)',
  },
  sheet: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    padding: 20,
    paddingBottom: 32,
  },
  closeButton: {
    position: 'absolute',
    top: 14,
    right: 14,
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f2f2f2',
    zIndex: 1,
  },
  closeIcon: {
    fontSize: 16,
    color: '#555',
  },
  sheetTitle: {
    fontSize: 18,
    fontWeight: '700',
    marginBottom: 8,
  },
  optionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 14,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#eee',
  },
  optionText: {
    fontSize: 16,
    color: '#444',
  },
  optionTextSelected: {
    color: '#1565c0',
    fontWeight: '700',
  },
  checkmark: {
    fontSize: 16,
    color: '#1565c0',
    fontWeight: '700',
  },
});

export default SortControl;
