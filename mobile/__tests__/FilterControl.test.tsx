/**
 * @format
 */

import React from 'react';
import {Modal, Text} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import FilterControl from '../src/components/FilterControl';
import {FuelKey} from '../src/config/fuelDisplay';
import {BrandOption} from '../src/utils/brandFilter';

const BRAND_OPTIONS: BrandOption[] = [
  {key: 'Shell', label: 'Shell'},
  {key: 'Esso', label: 'Esso'},
  {key: '__other__', label: 'Other'},
];

function renderControl(
  overrides: Partial<React.ComponentProps<typeof FilterControl>> = {},
) {
  const props: React.ComponentProps<typeof FilterControl> = {
    primaryFuelKey: 'regular',
    secondaryFuelKey: 'premium',
    onChangePrimaryFuelKey: jest.fn<(key: FuelKey) => void>(),
    onChangeSecondaryFuelKey: jest.fn<(key: FuelKey) => void>(),
    brandOptions: BRAND_OPTIONS,
    // null = no filter applied — the default, everything shown/checked.
    selectedBrandKeys: null,
    onApplyBrandFilters: jest.fn<(keys: Set<string> | null) => void>(),
    ...overrides,
  };
  return {props, element: <FilterControl {...props} />};
}

async function open(renderer: ReactTestRenderer) {
  await act(async () => {
    renderer.root
      .findByProps({accessibilityLabel: 'Open filters'})
      .props.onPress();
  });
}

it('defaults to closed', async () => {
  const {element} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Open filters'}),
  ).toBeTruthy();
});

it('opens on tap and lists fuel grade options for both price slots plus every brand, all checked by default', async () => {
  const {element} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  expect(renderer!.root.findByType(Modal).props.visible).toBe(true);
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show Regular as Price 1'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show Diesel as Price 1'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({
      accessibilityLabel: 'Show Premium as Price 2',
    }),
  ).toBeTruthy();
  // No filter applied yet (null) — every brand starts checked, i.e. every
  // row reads "Hide" (tapping it would hide that brand).
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide Shell'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide Esso'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide Other'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Apply brand filters'}),
  ).toBeTruthy();
});

it('selecting a Price 1 fuel grade calls the callback immediately and keeps the sheet open', async () => {
  const {element, props} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Show Midgrade as Price 1'})
      .props.onPress();
  });

  // Fuel grade is not part of the brand submit flow — it still applies
  // live, same as before.
  expect(props.onChangePrimaryFuelKey).toHaveBeenCalledWith('midgrade');
  expect(renderer!.root.findByType(Modal).props.visible).toBe(true);
});

it('disables the Price 2 chip that matches the current Price 1 selection', async () => {
  const {element, props} = renderControl({
    primaryFuelKey: 'regular',
    secondaryFuelKey: 'premium',
  });
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  const disabledChip = renderer!.root.findByProps({
    accessibilityLabel: 'Show Regular as Price 2',
  });
  expect(disabledChip.props.disabled).toBe(true);

  await act(async () => {
    disabledChip.props.onPress();
  });
  expect(props.onChangeSecondaryFuelKey).not.toHaveBeenCalled();

  // Price 1's own current grade (Regular) stays enabled in its own row.
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show Regular as Price 1'})
      .props.disabled,
  ).toBe(false);
});

it('disables the Price 1 chip that matches the current Price 2 selection', async () => {
  const {element, props} = renderControl({
    primaryFuelKey: 'regular',
    secondaryFuelKey: 'premium',
  });
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  const disabledChip = renderer!.root.findByProps({
    accessibilityLabel: 'Show Premium as Price 1',
  });
  expect(disabledChip.props.disabled).toBe(true);

  await act(async () => {
    disabledChip.props.onPress();
  });
  expect(props.onChangePrimaryFuelKey).not.toHaveBeenCalled();
});

it('toggling a brand updates the checkmark locally without applying anything yet', async () => {
  const {element, props} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Hide Esso'})
      .props.onPress();
  });

  // The row flips to reflect the draft...
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show Esso'}),
  ).toBeTruthy();
  // ...but nothing has been applied to the actual filter yet.
  expect(props.onApplyBrandFilters).not.toHaveBeenCalled();
});

it('applying with only some brands checked submits exactly that allowlist', async () => {
  const {element, props} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  // Uncheck Esso and Other, leaving only Shell.
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Hide Esso'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Hide Other'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Apply brand filters'})
      .props.onPress();
  });

  expect(props.onApplyBrandFilters).toHaveBeenCalledTimes(1);
  expect(props.onApplyBrandFilters).toHaveBeenCalledWith(new Set(['Shell']));
  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);
});

it('applying with everything still checked submits null, not a full-but-fragile allowlist', async () => {
  const {element, props} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Apply brand filters'})
      .props.onPress();
  });

  // Everything was checked, so this should mean "no filter" — which also
  // means brands discovered later via pagination stay visible, unlike an
  // allowlist that happened to list every *currently known* brand.
  expect(props.onApplyBrandFilters).toHaveBeenCalledWith(null);
});

it('discards unsubmitted brand edits when the sheet is closed without pressing Apply', async () => {
  const {element, props} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Hide Esso'})
      .props.onPress();
  });
  // Close without submitting.
  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Close'}).props.onPress();
  });

  expect(props.onApplyBrandFilters).not.toHaveBeenCalled();

  // Reopening starts fresh from the still-applied (unfiltered) state —
  // the abandoned edit to Esso is gone.
  await open(renderer!);
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide Esso'}),
  ).toBeTruthy();
});

it('reopens reflecting whatever allowlist was last applied, not a stale draft', async () => {
  const {element, props} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Hide Esso'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Hide Other'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Apply brand filters'})
      .props.onPress();
  });
  expect(props.onApplyBrandFilters).toHaveBeenCalledWith(new Set(['Shell']));

  // Simulate the parent actually applying it, then reopen.
  await act(async () => {
    renderer!.update(
      <FilterControl {...props} selectedBrandKeys={new Set(['Shell'])} />,
    );
  });
  await open(renderer!);

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show Esso'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide Shell'}),
  ).toBeTruthy();
});

it('hides a brand discovered later via pagination that was never part of the applied allowlist', async () => {
  // This is the exact reported bug, reproduced at the component level: a
  // 2-brand filter is applied, then "load more" turns up a third brand
  // that didn't exist when the filter was chosen. It must show as
  // unchecked (filtered out), not silently checked just because it's new.
  const {element, props} = renderControl({
    selectedBrandKeys: new Set(['Shell', 'Esso']),
  });
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });

  // Pagination grows brandOptions with a brand that wasn't there before.
  const grownOptions: BrandOption[] = [
    ...BRAND_OPTIONS,
    {key: 'Petro-Canada', label: 'Petro-Canada'},
  ];
  await act(async () => {
    renderer!.update(<FilterControl {...props} brandOptions={grownOptions} />);
  });
  await open(renderer!);

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show Petro-Canada'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide Shell'}),
  ).toBeTruthy();
});

it('shows Deselect All when every brand is selected in the draft', async () => {
  const {element, props} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  const toggle = renderer!.root.findByProps({
    accessibilityLabel: 'Deselect all brands',
  });
  expect(toggle.findByType(Text).props.children).toBe('Deselect All');

  await act(async () => {
    toggle.props.onPress();
  });

  // Deselecting all is itself a draft edit — still not applied.
  expect(props.onApplyBrandFilters).not.toHaveBeenCalled();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Select all brands'}),
  ).toBeTruthy();
});

it('shows Select All when any brand is deselected in the draft, and it re-checks everything', async () => {
  const {element} = renderControl({
    selectedBrandKeys: new Set(['Shell']),
  });
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  const toggle = renderer!.root.findByProps({
    accessibilityLabel: 'Select all brands',
  });
  expect(toggle.findByType(Text).props.children).toBe('Select All');

  await act(async () => {
    toggle.props.onPress();
  });

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide Esso'}),
  ).toBeTruthy();
});

it('hides the select/deselect-all toggle and submit button when there are no brands to filter', async () => {
  const {element} = renderControl({brandOptions: []});
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Select all brands'}),
  ).toThrow();
  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Deselect all brands'}),
  ).toThrow();
  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Apply brand filters'}),
  ).toThrow();
});

it('shows a brand outside the applied allowlist as unchecked', async () => {
  const {element} = renderControl({selectedBrandKeys: new Set(['Shell'])});
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show Esso'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide Shell'}),
  ).toBeTruthy();
});

it('hides the active-filter dot when no brand allowlist is applied (null)', async () => {
  const {element} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });

  expect(() =>
    renderer!.root.findByProps({testID: 'filter-active-dot'}),
  ).toThrow();
});

it('shows the active-filter dot when a brand allowlist has been applied', async () => {
  const {element} = renderControl({selectedBrandKeys: new Set(['Shell'])});
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });

  expect(
    renderer!.root.findByProps({testID: 'filter-active-dot'}),
  ).toBeTruthy();
});

it('shows the active-filter dot when a fuel grade has been changed from its default', async () => {
  const {element} = renderControl({primaryFuelKey: 'diesel'});
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });

  expect(
    renderer!.root.findByProps({testID: 'filter-active-dot'}),
  ).toBeTruthy();
});

it('closing via the close button hides the sheet', async () => {
  const {element} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Close'}).props.onPress();
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);
});

it('shows a fallback message when there are no brands to filter yet', async () => {
  const {element} = renderControl({brandOptions: []});
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  expect(
    renderer!.root.findByProps({children: 'No brands to filter yet.'}),
  ).toBeTruthy();
});
