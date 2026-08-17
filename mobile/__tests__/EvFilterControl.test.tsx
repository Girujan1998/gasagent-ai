/**
 * @format
 */

import React from 'react';
import {Modal} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import EvFilterControl, {
  EvFilterSelection,
} from '../src/components/EvFilterControl';
import {ConnectorOption, NetworkOption} from '../src/utils/evFilters';

const NETWORK_OPTIONS: NetworkOption[] = [
  {key: 'ChargePoint', label: 'ChargePoint'},
  {key: 'EVgo', label: 'EVgo'},
];

const CONNECTOR_OPTIONS: ConnectorOption[] = [
  {key: 'J1772', label: 'J1772'},
  {key: 'J1772COMBO', label: 'CCS'},
];

const UNFILTERED_SELECTION: EvFilterSelection = {
  networkKeys: null,
  connectorKeys: null,
  chargerLevelKeys: null,
};

function renderControl(
  overrides: Partial<React.ComponentProps<typeof EvFilterControl>> = {},
) {
  const props: React.ComponentProps<typeof EvFilterControl> = {
    networkOptions: NETWORK_OPTIONS,
    connectorOptions: CONNECTOR_OPTIONS,
    selection: UNFILTERED_SELECTION,
    onApply: jest.fn<(selection: EvFilterSelection) => void>(),
    ...overrides,
  };
  return {props, element: <EvFilterControl {...props} />};
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
});

it('opens on tap and lists every network, connector type, and charger level, all checked by default', async () => {
  const {element} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  expect(renderer!.root.findByType(Modal).props.visible).toBe(true);
  // No filter applied yet (null) — every row starts checked, i.e. reads
  // "Hide" (tapping it would hide that option).
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide ChargePoint'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide EVgo'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide J1772'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide CCS'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide Level 1'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide Level 2'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide DC Fast'}),
  ).toBeTruthy();
});

it('toggling an option updates the checkmark locally without applying anything yet', async () => {
  const {element, props} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Hide EVgo'})
      .props.onPress();
  });

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show EVgo'}),
  ).toBeTruthy();
  expect(props.onApply).not.toHaveBeenCalled();
});

it('applying submits an allowlist for exactly the sections that were narrowed', async () => {
  const {element, props} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  // Narrow only the network section — leave connectors and chargers fully
  // checked.
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Hide EVgo'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Apply filters'})
      .props.onPress();
  });

  expect(props.onApply).toHaveBeenCalledTimes(1);
  expect(props.onApply).toHaveBeenCalledWith({
    networkKeys: new Set(['ChargePoint']),
    connectorKeys: null,
    chargerLevelKeys: null,
  });
  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);
});

it('applying with everything still checked submits null for every section', async () => {
  const {element, props} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Apply filters'})
      .props.onPress();
  });

  // Everything was checked, so each section means "no filter" — options
  // discovered later via pagination stay visible, unlike an allowlist that
  // happened to list every currently known option.
  expect(props.onApply).toHaveBeenCalledWith({
    networkKeys: null,
    connectorKeys: null,
    chargerLevelKeys: null,
  });
});

it('discards unsubmitted edits when the sheet is closed without pressing Apply', async () => {
  const {element, props} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Hide EVgo'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Close'}).props.onPress();
  });

  expect(props.onApply).not.toHaveBeenCalled();

  await open(renderer!);
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide EVgo'}),
  ).toBeTruthy();
});

it('reopens reflecting whatever selection was last applied, not a stale draft', async () => {
  const {element, props} = renderControl({
    selection: {
      networkKeys: new Set(['ChargePoint']),
      connectorKeys: null,
      chargerLevelKeys: null,
    },
  });
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show EVgo'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide ChargePoint'}),
  ).toBeTruthy();
  expect(props.onApply).not.toHaveBeenCalled();
});

it('hides a network discovered later via pagination that was never part of the applied allowlist', async () => {
  const {element, props} = renderControl({
    selection: {
      networkKeys: new Set(['ChargePoint', 'EVgo']),
      connectorKeys: null,
      chargerLevelKeys: null,
    },
  });
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });

  const grownOptions: NetworkOption[] = [
    ...NETWORK_OPTIONS,
    {key: 'Blink Network', label: 'Blink Network'},
  ];
  await act(async () => {
    renderer!.update(
      <EvFilterControl {...props} networkOptions={grownOptions} />,
    );
  });
  await open(renderer!);

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show Blink Network'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide ChargePoint'}),
  ).toBeTruthy();
});

it('shows Deselect All when every option in a section is selected, and re-checks everything on Select All', async () => {
  const {element} = renderControl({
    selection: {
      networkKeys: new Set(['ChargePoint']),
      connectorKeys: null,
      chargerLevelKeys: null,
    },
  });
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  const selectAll = renderer!.root.findByProps({
    accessibilityLabel: 'Select all EV Network',
  });

  await act(async () => {
    selectAll.props.onPress();
  });

  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide EVgo'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Deselect all EV Network'}),
  ).toBeTruthy();
});

it('hides the active-filter dot when no filters are applied (null everywhere)', async () => {
  const {element} = renderControl();
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });

  expect(() =>
    renderer!.root.findByProps({testID: 'ev-filter-active-dot'}),
  ).toThrow();
});

it('shows the active-filter dot when any section has an applied allowlist', async () => {
  const {element} = renderControl({
    selection: {
      networkKeys: new Set(['ChargePoint']),
      connectorKeys: null,
      chargerLevelKeys: null,
    },
  });
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });

  expect(
    renderer!.root.findByProps({testID: 'ev-filter-active-dot'}),
  ).toBeTruthy();
});

it('shows a fallback message for a section with no options to filter yet', async () => {
  const {element} = renderControl({networkOptions: [], connectorOptions: []});
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  expect(
    renderer!.root.findByProps({children: 'No networks to filter yet.'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({
      children: 'No connector types to filter yet.',
    }),
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

it('Reset re-checks every section in the draft without applying or closing the sheet', async () => {
  const {element, props} = renderControl({
    selection: {
      networkKeys: new Set(['ChargePoint']),
      connectorKeys: new Set(['J1772']),
      chargerLevelKeys: null,
    },
  });
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  // Starts reflecting the narrowed selection...
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Show EVgo'}),
  ).toBeTruthy();

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Reset filters'})
      .props.onPress();
  });

  // ...and Reset re-checks everything in the draft, but stays open and
  // hasn't told the parent anything yet — Reset is staged like every other
  // edit, not a special immediate-apply action.
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide EVgo'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide ChargePoint'}),
  ).toBeTruthy();
  expect(
    renderer!.root.findByProps({accessibilityLabel: 'Hide J1772'}),
  ).toBeTruthy();
  expect(renderer!.root.findByType(Modal).props.visible).toBe(true);
  expect(props.onApply).not.toHaveBeenCalled();
});

it('pressing Apply after Reset submits null for every section', async () => {
  const {element, props} = renderControl({
    selection: {
      networkKeys: new Set(['ChargePoint']),
      connectorKeys: null,
      chargerLevelKeys: null,
    },
  });
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(element);
  });
  await open(renderer!);

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Reset filters'})
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Apply filters'})
      .props.onPress();
  });

  expect(props.onApply).toHaveBeenCalledWith({
    networkKeys: null,
    connectorKeys: null,
    chargerLevelKeys: null,
  });
});
