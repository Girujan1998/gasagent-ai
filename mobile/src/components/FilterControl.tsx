import React, {useState} from 'react';
import {
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';

import {
  DEFAULT_PRIMARY_FUEL_KEY,
  DEFAULT_SECONDARY_FUEL_KEY,
  FUEL_KEYS,
  FUEL_LABELS,
  FuelKey,
} from '../config/fuelDisplay';
import {BrandOption} from '../utils/brandFilter';
import FilterIcon from './FilterIcon';

type Props = {
  primaryFuelKey: FuelKey;
  secondaryFuelKey: FuelKey;
  onChangePrimaryFuelKey: (key: FuelKey) => void;
  onChangeSecondaryFuelKey: (key: FuelKey) => void;
  brandOptions: BrandOption[];
  // The applied allowlist — what's actually filtering the list right now.
  // null means no filter (show every brand, including ones not seen yet).
  // Brand changes are staged locally while the sheet is open and only
  // reach this via onApplyBrandFilters, when Submit is pressed.
  selectedBrandKeys: Set<string> | null;
  onApplyBrandFilters: (selectedKeys: Set<string> | null) => void;
};

function allBrandKeys(options: BrandOption[]): Set<string> {
  return new Set(options.map(option => option.key));
}

function FuelKeyChips({
  selected,
  onSelect,
  slotLabel,
  disabledKey,
}: {
  selected: FuelKey;
  onSelect: (key: FuelKey) => void;
  slotLabel: string;
  // The fuel grade the other price slot already uses — offering it here
  // too would let both slots show the same grade, so it's shown but
  // can't be picked.
  disabledKey: FuelKey;
}): React.JSX.Element {
  return (
    <View style={styles.chipRow}>
      {FUEL_KEYS.map(key => {
        const isSelected = key === selected;
        const isDisabled = key === disabledKey;
        return (
          <TouchableOpacity
            key={key}
            style={[
              styles.chip,
              isSelected && styles.chipSelected,
              isDisabled && styles.chipDisabled,
            ]}
            onPress={() => {
              if (!isDisabled) {
                onSelect(key);
              }
            }}
            disabled={isDisabled}
            accessibilityState={{disabled: isDisabled}}
            accessibilityLabel={`Show ${FUEL_LABELS[key]} as ${slotLabel}`}>
            <Text
              style={[styles.chipText, isSelected && styles.chipTextSelected]}>
              {FUEL_LABELS[key]}
            </Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

function FilterControl({
  primaryFuelKey,
  secondaryFuelKey,
  onChangePrimaryFuelKey,
  onChangeSecondaryFuelKey,
  brandOptions,
  selectedBrandKeys,
  onApplyBrandFilters,
}: Props): React.JSX.Element {
  const [open, setOpen] = useState(false);
  // A working copy, always a concrete set of checked keys — even when no
  // filter is applied, which just means "everything currently known is
  // checked". Edited freely while the sheet is open and only reaching the
  // parent when Submit is pressed. Seeded from the applied selection each
  // time the sheet opens, so unsubmitted edits from a previous visit
  // never leak in and a previous Submit is reflected.
  const [draftSelectedBrandKeys, setDraftSelectedBrandKeys] = useState(() =>
    selectedBrandKeys === null
      ? allBrandKeys(brandOptions)
      : new Set(selectedBrandKeys),
  );

  const isActive =
    primaryFuelKey !== DEFAULT_PRIMARY_FUEL_KEY ||
    secondaryFuelKey !== DEFAULT_SECONDARY_FUEL_KEY ||
    selectedBrandKeys !== null;
  const allBrandsSelected = brandOptions.every(option =>
    draftSelectedBrandKeys.has(option.key),
  );

  const handleOpen = () => {
    setDraftSelectedBrandKeys(
      selectedBrandKeys === null
        ? allBrandKeys(brandOptions)
        : new Set(selectedBrandKeys),
    );
    setOpen(true);
  };

  const handleToggleBrandDraft = (key: string) => {
    setDraftSelectedBrandKeys(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const handleSelectAllDraft = () =>
    setDraftSelectedBrandKeys(allBrandKeys(brandOptions));

  const handleDeselectAllDraft = () => setDraftSelectedBrandKeys(new Set());

  const handleSubmitBrands = () => {
    // Selecting every known brand is the same as not filtering at all —
    // and crucially, unlike a specific allowlist, it should keep showing
    // brands discovered later via pagination too, so it's stored as null
    // rather than the current (possibly incomplete) list of keys.
    const everythingSelected = brandOptions.every(option =>
      draftSelectedBrandKeys.has(option.key),
    );
    onApplyBrandFilters(
      everythingSelected ? null : new Set(draftSelectedBrandKeys),
    );
    setOpen(false);
  };

  return (
    <>
      <TouchableOpacity
        style={styles.trigger}
        onPress={handleOpen}
        accessibilityLabel="Open filters">
        <FilterIcon />
        {isActive && (
          <View style={styles.activeDot} testID="filter-active-dot" />
        )}
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
          accessibilityLabel="Close filters">
          <View style={styles.sheet}>
            <TouchableOpacity
              style={styles.closeButton}
              onPress={() => setOpen(false)}
              hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
              accessibilityLabel="Close">
              <Text style={styles.closeIcon}>✕</Text>
            </TouchableOpacity>

            <Text style={styles.sheetTitle}>Filters</Text>

            <ScrollView
              style={styles.scrollArea}
              showsVerticalScrollIndicator={false}>
              <View style={styles.sectionHeaderRow}>
                <Text style={styles.sectionLabel}>Price 1 fuel grade</Text>
              </View>
              <FuelKeyChips
                selected={primaryFuelKey}
                onSelect={onChangePrimaryFuelKey}
                slotLabel="Price 1"
                disabledKey={secondaryFuelKey}
              />

              <View style={styles.sectionHeaderRow}>
                <Text style={styles.sectionLabel}>Price 2 fuel grade</Text>
              </View>
              <FuelKeyChips
                selected={secondaryFuelKey}
                onSelect={onChangeSecondaryFuelKey}
                slotLabel="Price 2"
                disabledKey={primaryFuelKey}
              />

              <View style={styles.sectionHeaderRow}>
                <Text style={styles.sectionLabel}>Brands</Text>
                {brandOptions.length > 0 && (
                  <TouchableOpacity
                    onPress={
                      allBrandsSelected
                        ? handleDeselectAllDraft
                        : handleSelectAllDraft
                    }
                    hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
                    accessibilityLabel={
                      allBrandsSelected
                        ? 'Deselect all brands'
                        : 'Select all brands'
                    }>
                    <Text style={styles.sectionAction}>
                      {allBrandsSelected ? 'Deselect All' : 'Select All'}
                    </Text>
                  </TouchableOpacity>
                )}
              </View>
              {brandOptions.length === 0 ? (
                <Text style={styles.emptyText}>No brands to filter yet.</Text>
              ) : (
                brandOptions.map(option => {
                  const selected = draftSelectedBrandKeys.has(option.key);
                  return (
                    <TouchableOpacity
                      key={option.key}
                      style={styles.optionRow}
                      onPress={() => handleToggleBrandDraft(option.key)}
                      accessibilityLabel={`${selected ? 'Hide' : 'Show'} ${
                        option.label
                      }`}>
                      <Text style={styles.optionText}>{option.label}</Text>
                      {selected && <Text style={styles.checkmark}>✓</Text>}
                    </TouchableOpacity>
                  );
                })
              )}
            </ScrollView>

            {brandOptions.length > 0 && (
              // Fixed below the ScrollView rather than as its last item, so
              // it stays visible without the user scrolling the brand list
              // to find it.
              <TouchableOpacity
                style={styles.submitButton}
                onPress={handleSubmitBrands}
                accessibilityLabel="Apply brand filters">
                <Text style={styles.submitButtonText}>
                  Apply Brand Filters
                </Text>
              </TouchableOpacity>
            )}
          </View>
        </TouchableOpacity>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  trigger: {
    width: 34,
    height: 34,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#fff',
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 1},
    shadowOpacity: 0.1,
    shadowRadius: 3,
    elevation: 2,
  },
  activeDot: {
    position: 'absolute',
    top: 4,
    right: 4,
    width: 7,
    height: 7,
    borderRadius: 3.5,
    backgroundColor: '#1565c0',
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
    maxHeight: '80%',
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
    marginBottom: 12,
  },
  scrollArea: {
    // No fixed height — hugs its content up to the sheet's own maxHeight,
    // at which point this flex:1 lets it shrink to the space left over
    // after the title and the fixed submitButton footer below, so the
    // footer is always visible without occupying empty space when the
    // list itself is short.
    flexGrow: 0,
    flexShrink: 1,
  },
  sectionHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 16,
    marginBottom: 8,
  },
  sectionLabel: {
    fontSize: 12,
    color: '#888',
    textTransform: 'uppercase',
  },
  sectionAction: {
    fontSize: 12,
    color: '#1565c0',
    fontWeight: '600',
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  chip: {
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: 16,
    backgroundColor: '#f2f2f2',
  },
  chipSelected: {
    backgroundColor: '#1565c0',
  },
  chipDisabled: {
    opacity: 0.4,
  },
  chipText: {
    fontSize: 13,
    color: '#444',
    fontWeight: '600',
  },
  chipTextSelected: {
    color: '#fff',
  },
  optionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#eee',
  },
  optionText: {
    fontSize: 15,
    color: '#444',
  },
  checkmark: {
    fontSize: 16,
    color: '#1565c0',
    fontWeight: '700',
  },
  emptyText: {
    fontSize: 13,
    color: '#999',
    paddingVertical: 8,
  },
  submitButton: {
    marginTop: 16,
    backgroundColor: '#1565c0',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  submitButtonText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '700',
  },
});

export default FilterControl;
