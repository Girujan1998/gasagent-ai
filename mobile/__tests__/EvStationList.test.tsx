/**
 * @format
 */

import React from 'react';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Linking,
  Modal,
  Text,
} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest} from '@jest/globals';

import {EvStation} from '../src/api/client';
import EvStationList from '../src/components/EvStationList';

const station: EvStation = {
  station_id: 'abc',
  name: 'Downtown Charging Hub',
  network: 'ChargePoint Network',
  network_web: 'https://www.chargepoint.com',
  address: '1 Main St, Springfield, IL',
  latitude: 41.9,
  longitude: -87.6,
  distance_miles: 1.5,
  phone: '888-758-4389',
  access_hours: '24 hours daily',
  access_code: 'public',
  status_code: 'E',
  level1_count: null,
  level2_count: 2,
  dc_fast_count: 1,
  connector_types: ['J1772', 'J1772COMBO'],
  connector_details: [],
  date_last_confirmed: '2026-08-16T00:00:00.000Z',
  comments: [],
  photo_urls: [],
};

it('opens a detail modal on tap, and closes it via the close button', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList stations={[station]} loading={false} error={null} />,
    );
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);

  const joinedTexts = () =>
    renderer!.root.findAllByType(Text).map(node =>
      ([] as unknown[])
        .concat(node.props.children)
        .filter(value => typeof value === 'string')
        .join(''),
    );

  // The card itself (before opening anything) shows distance in
  // kilometers, not miles — 1.5 miles.
  expect(joinedTexts()).toContain('2.4 km');
  expect(joinedTexts()).toContain('ChargePoint Network');

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(true);
  const textNodes = joinedTexts();

  expect(textNodes).toContain('2.4 km away');
  expect(textNodes).toContain('CCS');
  expect(textNodes).toEqual(expect.arrayContaining(['J1772', 'CCS']));

  await act(async () => {
    renderer!.root.findByProps({accessibilityLabel: 'Close'}).props.onPress();
  });

  expect(renderer!.root.findByType(Modal).props.visible).toBe(false);
});

it("shows the network's logo in both the card and the detail modal, falling back to the bolt icon in the modal on load failure", async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList stations={[station]} loading={false} error={null} />,
    );
  });

  // The card's own logo (from earlier work).
  expect(renderer!.root.findAllByType(Image)).toHaveLength(1);
  expect(renderer!.root.findByType(Image).props.source.uri).toBe(
    'https://www.google.com/s2/favicons?sz=64&domain=www.chargepoint.com',
  );

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });

  // Now both the card (still rendered behind the modal) and the modal's
  // own logo are present.
  const images = renderer!.root.findAllByType(Image);
  expect(images).toHaveLength(2);
  images.forEach(image => {
    expect(image.props.source.uri).toBe(
      'https://www.google.com/s2/favicons?sz=64&domain=www.chargepoint.com',
    );
  });

  await act(async () => {
    images[1].props.onError();
  });

  // The modal's logo falls back to the bolt icon; the card's is untouched.
  expect(renderer!.root.findAllByType(Image)).toHaveLength(1);
});

it('hides the connector chips section for a station with none reported', async () => {
  const stationWithNoConnectors: EvStation = {...station, connector_types: []};

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[stationWithNoConnectors]}
        loading={false}
        error={null}
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });

  expect(
    renderer!.root.findAllByProps({children: 'Connector Types'}),
  ).toHaveLength(0);
});

it('shows per-connector Amps/Voltage/PowerKW specs in the detail modal when reported', async () => {
  const stationWithSpecs: EvStation = {
    ...station,
    connector_details: [
      {
        connector_type: 'J1772COMBO',
        quantity: 2,
        amps: 125,
        voltage: 400,
        power_kw: 50,
      },
      {
        connector_type: 'CHADEMO',
        quantity: 1,
        amps: null,
        voltage: null,
        power_kw: null,
      },
    ],
  };

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[stationWithSpecs]}
        loading={false}
        error={null}
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });

  const texts = renderer!.root
    .findAllByType(Text)
    .map(node => node.props.children);
  expect(texts).toContain('Charger Specs');
  expect(texts).toContain('CCS ×2');
  expect(texts).toContain('50 kW · 400 V · 125 A');
  // The CHAdeMO connector has no reported specs, so its row is omitted
  // (via DetailRow's own null-value handling) even though the type
  // itself is in connector_details.
  expect(texts).not.toContain('CHAdeMO');
});

it('hides the Charger Specs section when the station has no connector details', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList stations={[station]} loading={false} error={null} />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });

  expect(
    renderer!.root.findAllByProps({children: 'Charger Specs'}),
  ).toHaveLength(0);
});

it('shows a scrollable strip of community photos when the station has any', async () => {
  const stationWithPhotos: EvStation = {
    ...station,
    photo_urls: [
      'https://example.com/photo1.jpg',
      'https://example.com/photo2.jpg',
    ],
  };

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[stationWithPhotos]}
        loading={false}
        error={null}
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });

  const photoUris = renderer!.root
    .findAllByType(Image)
    .map(node => node.props.source?.uri)
    .filter(Boolean);
  expect(photoUris).toEqual(
    expect.arrayContaining([
      'https://example.com/photo1.jpg',
      'https://example.com/photo2.jpg',
    ]),
  );
});

it('hides the Photos section when the station has none', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList stations={[station]} loading={false} error={null} />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });

  expect(renderer!.root.findAllByProps({children: 'Photos'})).toHaveLength(0);
});

it("shows community comments in the detail modal, color-coded by the check-in's positive/negative signal", async () => {
  const stationWithComments: EvStation = {
    ...station,
    comments: [
      {
        author: 'Celso Azevedo',
        text: 'Changed operator, still works fine.',
        date: '2025-06-14T18:44:21.44Z',
        checkin_status: 'Charged Successfully',
        checkin_is_positive: true,
      },
      {
        author: 'Someone Else',
        text: 'Broken when I arrived.',
        date: '2024-01-01T00:00:00Z',
        checkin_status: 'Failed to Charge (Equipment Not Operational)',
        checkin_is_positive: false,
      },
    ],
  };

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[stationWithComments]}
        loading={false}
        error={null}
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });

  const texts = renderer!.root
    .findAllByType(Text)
    .map(node => node.props.children);
  expect(texts).toContain('Community Notes');
  expect(texts).toContain('Celso Azevedo');
  expect(texts).toContain('Changed operator, still works fine.');
  expect(texts).toContain('Someone Else');
  expect(texts).toContain('Broken when I arrived.');

  const positiveStatus = renderer!.root.findByProps({
    children: 'Charged Successfully',
  });
  const negativeStatus = renderer!.root.findByProps({
    children: 'Failed to Charge (Equipment Not Operational)',
  });
  // RN merges a style array left-to-right, later entries overriding
  // earlier ones for the same property — so the *last* style with a
  // `color` wins, not the first.
  const flattenColor = (style: unknown) =>
    ([] as Record<string, unknown>[])
      .concat(style as never)
      .filter(Boolean)
      .reverse()
      .find(s => s.color)?.color;
  expect(flattenColor(positiveStatus.props.style)).toBe('#2e7d32');
  expect(flattenColor(negativeStatus.props.style)).toBe('#c62828');
});

it('hides the Community Notes section when the station has no comments', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList stations={[station]} loading={false} error={null} />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });

  expect(
    renderer!.root.findAllByProps({children: 'Community Notes'}),
  ).toHaveLength(0);
});

it('opens the device maps app with the station location when Navigate is pressed', async () => {
  const openURLSpy = jest
    .spyOn(Linking, 'openURL')
    .mockResolvedValue(undefined as never);

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList stations={[station]} loading={false} error={null} />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({
        accessibilityLabel: 'View details for Downtown Charging Hub',
      })
      .props.onPress();
  });
  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Navigate to this station'})
      .props.onPress();
  });

  expect(openURLSpy).toHaveBeenCalledTimes(1);
  const url = openURLSpy.mock.calls[0][0];
  expect(url).toContain('41.9');
  expect(url).toContain('-87.6');

  openURLSpy.mockRestore();
});

it('shows a Load More button when canLoadMore is true, and calls onLoadMore when pressed', async () => {
  const onLoadMore = jest.fn();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[station]}
        loading={false}
        error={null}
        canLoadMore
        onLoadMore={onLoadMore}
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Load more stations'})
      .props.onPress();
  });

  expect(onLoadMore).toHaveBeenCalledTimes(1);
});

it('shows a spinner instead of the Load More button while loadingMore is true', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[station]}
        loading={false}
        error={null}
        canLoadMore
        loadingMore
      />,
    );
  });

  expect(
    renderer!.root.findAllByProps({accessibilityLabel: 'Load more stations'}),
  ).toHaveLength(0);
  expect(renderer!.root.findByType(ActivityIndicator)).toBeTruthy();
});

it('hides the Load More button when canLoadMore is false', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[station]}
        loading={false}
        error={null}
        canLoadMore={false}
      />,
    );
  });

  expect(
    renderer!.root.findAllByProps({accessibilityLabel: 'Load more stations'}),
  ).toHaveLength(0);
});

it("wires refreshing and onRefresh into the list's pull-to-refresh control", async () => {
  const onRefresh = jest.fn();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList
        stations={[station]}
        loading={false}
        error={null}
        refreshing
        onRefresh={onRefresh}
      />,
    );
  });

  const refreshControl =
    renderer!.root.findByType(FlatList).props.refreshControl;
  expect(refreshControl.props.refreshing).toBe(true);

  refreshControl.props.onRefresh();
  expect(onRefresh).toHaveBeenCalledTimes(1);
});

it('shows the default empty message when there are no stations', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <EvStationList stations={[]} loading={false} error={null} />,
    );
  });

  const texts = renderer!.root
    .findAllByType(Text)
    .map(node => node.props.children);
  expect(texts).toContain('No EV chargers found nearby.');
});
