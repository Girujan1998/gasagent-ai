import React, {useState} from 'react';
import {
  Dimensions,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';

// A concrete pixel cap, not `flex: 1` — the ScrollView sits in a View
// (`sheet`) whose own height is itself content-driven (bounded only by
// `maxHeight: '80%'`, not a fixed/flex size), and Yoga can't hand a
// flex-grow child a share of "remaining space" a content-driven parent
// never computed a real size for in the first place: it resolves to zero,
// collapsing the whole scrollable section. A fixed cap sidesteps that
// entirely — `sheet` sizes around it (title row + this + Apply button)
// same as any other content, well within its own 80% safety cap.
const SCROLL_AREA_MAX_HEIGHT = Dimensions.get('window').height * 0.5;

import {
  CHARGER_LEVEL_OPTIONS,
  ChargerLevelKey,
  ConnectorOption,
  NetworkOption,
} from '../utils/evFilters';
import FilterIcon from './FilterIcon';

// All three filter dimensions are applied together, from one shared Apply
// button — grouped into a single value rather than three separate
// setState calls in the parent, since there's never a reason to apply one
// without the others.
export type EvFilterSelection = {
  networkKeys: Set<string> | null;
  connectorKeys: Set<string> | null;
  chargerLevelKeys: Set<ChargerLevelKey> | null;
};

type Props = {
  networkOptions: NetworkOption[];
  connectorOptions: ConnectorOption[];
  selection: EvFilterSelection;
  onApply: (selection: EvFilterSelection) => void;
};

function allKeys<T extends string>(options: {key: T}[]): Set<T> {
  return new Set(options.map(option => option.key));
}

// One reusable "allowlist checkbox list" section — used for all three
// filter dimensions (network, connector type, chargers), mirroring the
// gas filter sheet's Brands section.
function CheckboxSection<T extends string>({
  title,
  options,
  draftSelected,
  onToggle,
  onSelectAll,
  onDeselectAll,
  emptyText,
}: {
  title: string;
  options: {key: T; label: string}[];
  draftSelected: Set<T>;
  onToggle: (key: T) => void;
  onSelectAll: () => void;
  onDeselectAll: () => void;
  emptyText: string;
}): React.JSX.Element {
  const allSelected = options.every(option => draftSelected.has(option.key));

  return (
    <>
      <View style={styles.sectionHeaderRow}>
        <Text style={styles.sectionLabel}>{title}</Text>
        {options.length > 0 && (
          <TouchableOpacity
            onPress={allSelected ? onDeselectAll : onSelectAll}
            hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
            accessibilityLabel={
              allSelected ? `Deselect all ${title}` : `Select all ${title}`
            }>
            <Text style={styles.sectionAction}>
              {allSelected ? 'Deselect All' : 'Select All'}
            </Text>
          </TouchableOpacity>
        )}
      </View>
      {options.length === 0 ? (
        <Text style={styles.emptyText}>{emptyText}</Text>
      ) : (
        options.map(option => {
          const selected = draftSelected.has(option.key);
          return (
            <TouchableOpacity
              key={option.key}
              style={styles.optionRow}
              onPress={() => onToggle(option.key)}
              accessibilityLabel={`${selected ? 'Hide' : 'Show'} ${
                option.label
              }`}>
              <Text style={styles.optionText}>{option.label}</Text>
              {selected && <Text style={styles.checkmark}>✓</Text>}
            </TouchableOpacity>
          );
        })
      )}
    </>
  );
}

function draftFrom<T extends string>(
  selectedKeys: Set<T> | null,
  options: {key: T}[],
): Set<T> {
  return selectedKeys === null ? allKeys(options) : new Set(selectedKeys);
}

function EvFilterControl({
  networkOptions,
  connectorOptions,
  selection,
  onApply,
}: Props): React.JSX.Element {
  const [open, setOpen] = useState(false);
  // Working copies, always a concrete set of checked keys — even when no
  // filter is applied, which just means "everything currently known is
  // checked". Edited freely while the sheet is open and only reaching the
  // parent when Apply is pressed. Reseeded from the applied selection each
  // time the sheet opens, so unsubmitted edits from a previous visit never
  // leak in.
  const [draftNetworkKeys, setDraftNetworkKeys] = useState(() =>
    draftFrom(selection.networkKeys, networkOptions),
  );
  const [draftConnectorKeys, setDraftConnectorKeys] = useState(() =>
    draftFrom(selection.connectorKeys, connectorOptions),
  );
  const [draftChargerLevelKeys, setDraftChargerLevelKeys] = useState(() =>
    draftFrom(selection.chargerLevelKeys, CHARGER_LEVEL_OPTIONS),
  );

  const isActive =
    selection.networkKeys !== null ||
    selection.connectorKeys !== null ||
    selection.chargerLevelKeys !== null;

  const handleOpen = () => {
    setDraftNetworkKeys(draftFrom(selection.networkKeys, networkOptions));
    setDraftConnectorKeys(draftFrom(selection.connectorKeys, connectorOptions));
    setDraftChargerLevelKeys(
      draftFrom(selection.chargerLevelKeys, CHARGER_LEVEL_OPTIONS),
    );
    setOpen(true);
  };

  // Resets the draft back to "everything checked" (i.e. no filter) in every
  // section — the same staged-until-Apply treatment as every other edit in
  // this sheet, so Reset behaves predictably alongside Select All/Deselect
  // All rather than as a special case that applies itself immediately.
  const handleReset = () => {
    setDraftNetworkKeys(allKeys(networkOptions));
    setDraftConnectorKeys(allKeys(connectorOptions));
    setDraftChargerLevelKeys(allKeys(CHARGER_LEVEL_OPTIONS));
  };

  const toggle = <T extends string>(
    setter: React.Dispatch<React.SetStateAction<Set<T>>>,
    key: T,
  ) => {
    setter(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  // Selecting every known option is the same as not filtering at all —
  // and crucially, unlike a specific allowlist, it should keep showing
  // options discovered later via pagination too, so it's applied as null
  // rather than the current (possibly incomplete) list of keys.
  const asAppliedValue = <T extends string>(
    draft: Set<T>,
    options: {key: T}[],
  ): Set<T> | null =>
    options.length > 0 && options.every(option => draft.has(option.key))
      ? null
      : new Set(draft);

  const handleApply = () => {
    onApply({
      networkKeys: asAppliedValue(draftNetworkKeys, networkOptions),
      connectorKeys: asAppliedValue(draftConnectorKeys, connectorOptions),
      chargerLevelKeys: asAppliedValue(
        draftChargerLevelKeys,
        CHARGER_LEVEL_OPTIONS,
      ),
    });
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
          <View style={styles.activeDot} testID="ev-filter-active-dot" />
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

            <View style={styles.titleRow}>
              <Text style={styles.sheetTitle}>Filters</Text>
              <TouchableOpacity
                onPress={handleReset}
                hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
                accessibilityLabel="Reset filters">
                <Text style={styles.resetText}>Reset</Text>
              </TouchableOpacity>
            </View>

            <ScrollView
              style={styles.scrollArea}
              showsVerticalScrollIndicator={false}>
              <CheckboxSection
                title="EV Network"
                options={networkOptions}
                draftSelected={draftNetworkKeys}
                onToggle={key => toggle(setDraftNetworkKeys, key)}
                onSelectAll={() => setDraftNetworkKeys(allKeys(networkOptions))}
                onDeselectAll={() => setDraftNetworkKeys(new Set())}
                emptyText="No networks to filter yet."
              />

              <CheckboxSection
                title="Connector Type"
                options={connectorOptions}
                draftSelected={draftConnectorKeys}
                onToggle={key => toggle(setDraftConnectorKeys, key)}
                onSelectAll={() =>
                  setDraftConnectorKeys(allKeys(connectorOptions))
                }
                onDeselectAll={() => setDraftConnectorKeys(new Set())}
                emptyText="No connector types to filter yet."
              />

              <CheckboxSection
                title="Chargers"
                options={CHARGER_LEVEL_OPTIONS}
                draftSelected={draftChargerLevelKeys}
                onToggle={key => toggle(setDraftChargerLevelKeys, key)}
                onSelectAll={() =>
                  setDraftChargerLevelKeys(allKeys(CHARGER_LEVEL_OPTIONS))
                }
                onDeselectAll={() => setDraftChargerLevelKeys(new Set())}
                emptyText="No charger levels to filter yet."
              />
            </ScrollView>

            <TouchableOpacity
              style={styles.submitButton}
              onPress={handleApply}
              accessibilityLabel="Apply filters">
              <Text style={styles.submitButtonText}>Apply Filters</Text>
            </TouchableOpacity>
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
  scrollArea: {
    maxHeight: SCROLL_AREA_MAX_HEIGHT,
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
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
    // Clears the close button, which floats top-right over this row.
    paddingRight: 36,
  },
  sheetTitle: {
    fontSize: 18,
    fontWeight: '700',
  },
  resetText: {
    fontSize: 13,
    color: '#1565c0',
    fontWeight: '600',
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
    marginTop: 20,
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

export default EvFilterControl;
