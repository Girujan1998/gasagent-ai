/**
 * @format
 */

import Geolocation from '@react-native-community/geolocation';
import React, {useState} from 'react';
import {ActivityIndicator, Alert, FlatList, Text, TextInput} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest, beforeAll, afterEach, afterAll} from '@jest/globals';

import {GasStation, EvStation} from '../src/api/client';
import EvStationCard from '../src/components/EvStationCard';
import StationCard from '../src/components/StationCard';
import ChatScreen, {
  INITIAL_PERSISTED_CHAT,
  PersistedChat,
} from '../src/screens/ChatScreen';
import {FavoritesProvider} from '../src/store/FavoritesContext';

function mockGpsSuccess(lat: number, lon: number) {
  jest.mocked(Geolocation.getCurrentPosition).mockImplementation(success => {
    success({
      coords: {
        latitude: lat,
        longitude: lon,
        altitude: null,
        accuracy: 0,
        altitudeAccuracy: null,
        heading: null,
        speed: null,
      },
      timestamp: 0,
    });
  });
}

// The Send button's `disabled` prop toggles constantly in these tests
// (as the input is typed into, and while a message is sending), and
// TouchableOpacity animates its opacity on every such change — a real
// setTimeout-driven Animated.timing that otherwise keeps running past a
// test's own completion and trips Jest's "cannot log after tests are
// done" check. Fake timers let each test flush that animation itself
// before finishing, rather than leaking it into the next one.
beforeAll(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  act(() => {
    jest.runOnlyPendingTimers();
  });
});

afterAll(() => {
  jest.useRealTimers();
});

function chatResponse(content: string) {
  return {
    ok: true,
    json: () => Promise.resolve({message: {role: 'assistant', content}}),
  };
}

function chatResponseWithStations(
  content: string,
  gasStations: GasStation[] = [],
  evStations: EvStation[] = [],
) {
  return {
    ok: true,
    json: () =>
      Promise.resolve({
        message: {role: 'assistant', content},
        gas_stations: gasStations,
        ev_stations: evStations,
      }),
  };
}

function makeGasStation(name: string): GasStation {
  return {
    station_id: name,
    name,
    brand: name,
    brand_logo_url: null,
    connected_brand: null,
    connected_brand_logo_url: null,
    address: '1 Main St',
    latitude: 43.0,
    longitude: -80.0,
    distance_miles: 0.5,
    regular: {price: 158.9, formatted_price: '158.9¢', last_updated: null},
    midgrade: null,
    premium: null,
    diesel: null,
    star_rating: null,
    ratings_count: null,
    amenities: [],
  };
}

function makeEvStation(name: string): EvStation {
  return {
    station_id: name,
    name,
    network: name,
    network_web: null,
    address: '1 Charger Way',
    latitude: 43.0,
    longitude: -80.0,
    distance_miles: 0.5,
    phone: null,
    access_hours: null,
    access_code: null,
    status_code: null,
    level1_count: null,
    level2_count: 2,
    dc_fast_count: null,
    connector_types: ['J1772'],
    connector_details: [],
    date_last_confirmed: null,
    comments: [],
    photo_urls: [],
  };
}

function texts(renderer: ReactTestRenderer): string[] {
  return renderer.root.findAllByType(Text).map(node =>
    ([] as unknown[])
      .concat(node.props.children)
      .filter(value => typeof value === 'string' || typeof value === 'number')
      .join(''),
  );
}

function sendButton(renderer: ReactTestRenderer) {
  return renderer.root.findByProps({accessibilityLabel: 'Send message'});
}

async function typeAndSend(renderer: ReactTestRenderer, text: string) {
  await act(async () => {
    renderer.root.findByType(TextInput).props.onChangeText(text);
  });
  await act(async () => {
    sendButton(renderer).props.onPress();
  });
}

// Stands in for App.tsx: holds persistedChat in a PARENT component, so it
// survives ChatScreen unmounting/remounting the same way it would when
// switching tabs away and back in the real app.
function Harness({
  mounted,
  gasTabLocation = null,
  evTabLocation = null,
}: {
  mounted: boolean;
  gasTabLocation?: {lat: number; lon: number} | null;
  evTabLocation?: {lat: number; lon: number} | null;
}): React.JSX.Element | null {
  const [persistedChat, setPersistedChat] = useState<PersistedChat>(
    INITIAL_PERSISTED_CHAT,
  );

  if (!mounted) {
    return null;
  }
  return (
    <ChatScreen
      persistedChat={persistedChat}
      onChatComplete={setPersistedChat}
      gasTabLocation={gasTabLocation}
      evTabLocation={evTabLocation}
    />
  );
}

it('shows an intro message when there is no conversation yet', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  expect(texts(renderer!).join(' ')).toContain('Ask the GasAgent.ai assistant');
});

it('disables Send until there is text to send', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  expect(sendButton(renderer!).props.disabled).toBe(true);

  await act(async () => {
    renderer!.root.findByType(TextInput).props.onChangeText('Hello');
  });

  expect(sendButton(renderer!).props.disabled).toBe(false);
});

it('sends the message, shows the reply, and clears the input', async () => {
  const fetchMock = jest.fn(() => Promise.resolve(chatResponse('Hi there!')));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  await typeAndSend(renderer!, 'What is a good tire pressure?');

  const allTexts = texts(renderer!);
  expect(allTexts).toContain('What is a good tire pressure?');
  expect(allTexts).toContain('Hi there!');
  expect(renderer!.root.findByType(TextInput).props.value).toBe('');

  const url = (fetchMock.mock.calls[0] as unknown[])[0] as string;
  expect(url).toContain('/chat');
});

it('shows a typing indicator while waiting for the reply', async () => {
  let resolveFetch: (value: unknown) => void = () => {};
  global.fetch = jest.fn(
    () => new Promise(resolve => (resolveFetch = resolve)),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  await act(async () => {
    renderer!.root.findByType(TextInput).props.onChangeText('Hi');
  });
  await act(async () => {
    sendButton(renderer!).props.onPress();
  });

  expect(renderer!.root.findByType(ActivityIndicator)).toBeTruthy();

  await act(async () => {
    resolveFetch(chatResponse('Hello!'));
  });
});

it('sends the full conversation history, not just the newest message', async () => {
  const fetchMock = jest.fn(() => Promise.resolve(chatResponse('ok')));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={{
          messages: [
            {role: 'user', content: 'First'},
            {role: 'assistant', content: 'First reply'},
          ],
          error: null,
          cardsByMessageIndex: {},
        }}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  await typeAndSend(renderer!, 'Second');

  const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
  const body = JSON.parse(init.body as string) as {
    messages: {role: string; content: string}[];
  };
  expect(body.messages).toEqual([
    {role: 'user', content: 'First'},
    {role: 'assistant', content: 'First reply'},
    {role: 'user', content: 'Second'},
  ]);
});

it('keeps the user message and shows an error when the reply fails, without losing it on retry', async () => {
  const onChatComplete = jest.fn();
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok: false,
      status: 502,
      json: () => Promise.resolve({detail: 'Invalid API Key'}),
    }),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={onChatComplete}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  await typeAndSend(renderer!, 'Hello');

  expect(texts(renderer!)).toContain('Hello');
  expect(texts(renderer!).join(' ')).toContain('Invalid API Key');
  expect(onChatComplete).toHaveBeenCalledWith({
    messages: [{role: 'user', content: 'Hello'}],
    error: 'Invalid API Key',
    cardsByMessageIndex: {},
  });
});

it('restores the conversation across a tab switch without resending anything', async () => {
  const fetchMock = jest.fn(() => Promise.resolve(chatResponse('Hi!')));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(<Harness mounted />);
  });

  await typeAndSend(renderer!, 'Hello');
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(texts(renderer!)).toContain('Hi!');

  // Leaving the Chat tab unmounts it; coming back mounts a fresh instance
  // seeded from whatever was last persisted.
  await act(async () => {
    renderer!.update(<Harness mounted={false} />);
  });
  await act(async () => {
    renderer!.update(<Harness mounted />);
  });

  expect(fetchMock).toHaveBeenCalledTimes(1);
  const allTexts = texts(renderer!);
  expect(allTexts).toContain('Hello');
  expect(allTexts).toContain('Hi!');
});

it('scrolls to the bottom instantly once the list lays out, so a returning tab shows the last message without scrolling', async () => {
  // onContentSizeChange alone doesn't reliably fire scrollToEnd on a
  // fresh mount with an already-long history (the bug this covers) — it
  // can run before the list has actually laid out. onLayout is the fix:
  // it fires once the list itself is laid out, so this simulates
  // exactly that (react-test-renderer doesn't trigger real layout
  // events on its own).
  const scrollToEndSpy = jest
    .spyOn(FlatList.prototype, 'scrollToEnd')
    .mockImplementation(() => {});

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={{
          messages: [
            {role: 'user', content: 'First'},
            {role: 'assistant', content: 'First reply'},
          ],
          error: null,
          cardsByMessageIndex: {},
        }}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  const list = renderer!.root.findByType(FlatList);
  await act(async () => {
    list.props.onLayout({
      nativeEvent: {layout: {x: 0, y: 0, width: 0, height: 0}},
    });
  });

  expect(scrollToEndSpy).toHaveBeenCalledWith({animated: false});

  scrollToEndSpy.mockRestore();
});

it('shows the "share your location" banner when neither source is available', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  const banner = renderer!.root.findByProps({
    accessibilityLabel: 'Share your location',
  });
  expect(texts(renderer!).join(' ')).toContain(
    'Share your location to find gas stations near you',
  );
  expect(banner.props.disabled).toBe(false);
});

it('shows the "using last searched location" banner when only the Gas tab has one', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={{lat: 41.9, lon: -87.6}}
        evTabLocation={null}
      />,
    );
  });

  expect(texts(renderer!).join(' ')).toContain(
    'Using your last searched location',
  );
});

it('hides the banner once the user shares a fresh GPS location', async () => {
  mockGpsSuccess(41.95, -87.65);

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Share your location'})
      .props.onPress();
  });

  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Share your location'}),
  ).toThrow();
});

it('includes the Gas-tab location in the request body when no GPS fix has been shared', async () => {
  const fetchMock = jest.fn(() => Promise.resolve(chatResponse('ok')));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={{lat: 41.9, lon: -87.6}}
        evTabLocation={null}
      />,
    );
  });

  await typeAndSend(renderer!, 'gas near me?');

  const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
  const body = JSON.parse(init.body as string) as {
    gas_location?: {lat: number; lon: number};
    ev_location?: {lat: number; lon: number};
  };
  expect(body.gas_location).toEqual({lat: 41.9, lon: -87.6});
  expect(body.ev_location).toBeUndefined();
});

it('includes the EV-tab location in the request body when no GPS fix has been shared, independently of the Gas tab', async () => {
  const fetchMock = jest.fn(() => Promise.resolve(chatResponse('ok')));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={{lat: 41.9, lon: -87.6}}
        evTabLocation={{lat: 10.0, lon: 20.0}}
      />,
    );
  });

  await typeAndSend(renderer!, 'where can I charge my EV?');

  const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
  const body = JSON.parse(init.body as string) as {
    gas_location?: {lat: number; lon: number};
    ev_location?: {lat: number; lon: number};
  };
  expect(body.ev_location).toEqual({lat: 10.0, lon: 20.0});
  expect(body.gas_location).toEqual({lat: 41.9, lon: -87.6});
});

it('prefers a freshly shared GPS location over the Gas-tab fallback in the request body', async () => {
  mockGpsSuccess(1.0, 2.0);
  const fetchMock = jest.fn(() => Promise.resolve(chatResponse('ok')));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={{lat: 41.9, lon: -87.6}}
        evTabLocation={null}
      />,
    );
  });

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Share your location'})
      .props.onPress();
  });

  await typeAndSend(renderer!, 'gas near me?');

  const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
  const body = JSON.parse(init.body as string) as {
    gas_location?: {lat: number; lon: number};
  };
  expect(body.gas_location).toEqual({lat: 1.0, lon: 2.0});
});

it('omits location from the request body when neither source is available', async () => {
  const fetchMock = jest.fn(() => Promise.resolve(chatResponse('ok')));
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  await typeAndSend(renderer!, 'Hello');

  const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
  const body = JSON.parse(init.body as string) as {
    gas_location?: unknown;
    ev_location?: unknown;
  };
  expect(body.gas_location).toBeUndefined();
  expect(body.ev_location).toBeUndefined();
});

it('renders station cards when the reply includes gas/EV stations', async () => {
  global.fetch = jest.fn(() =>
    Promise.resolve(
      chatResponseWithStations(
        'Here are some options:',
        [makeGasStation('Shell'), makeGasStation('Esso')],
        [makeEvStation('ChargePoint')],
      ),
    ),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <ChatScreen
          persistedChat={INITIAL_PERSISTED_CHAT}
          onChatComplete={jest.fn()}
          gasTabLocation={null}
          evTabLocation={null}
        />
      </FavoritesProvider>,
    );
  });

  await typeAndSend(renderer!, 'gas and ev near me?');

  expect(renderer!.root.findAllByType(StationCard)).toHaveLength(2);
  expect(renderer!.root.findAllByType(EvStationCard)).toHaveLength(1);
});

it('renders no cards for a plain text-only reply', async () => {
  global.fetch = jest.fn(() =>
    Promise.resolve(chatResponse('Just a plain answer.')),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  await typeAndSend(renderer!, 'what is a good tire pressure?');

  expect(renderer!.root.findAllByType(StationCard)).toHaveLength(0);
  expect(renderer!.root.findAllByType(EvStationCard)).toHaveLength(0);
});

it('keeps cards attached to their message across a tab switch', async () => {
  global.fetch = jest.fn(() =>
    Promise.resolve(
      chatResponseWithStations('Here you go:', [makeGasStation('Shell')]),
    ),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <Harness mounted />
      </FavoritesProvider>,
    );
  });

  await typeAndSend(renderer!, 'gas near me?');
  expect(renderer!.root.findAllByType(StationCard)).toHaveLength(1);

  await act(async () => {
    renderer!.update(
      <FavoritesProvider>
        <Harness mounted={false} />
      </FavoritesProvider>,
    );
  });
  await act(async () => {
    renderer!.update(
      <FavoritesProvider>
        <Harness mounted />
      </FavoritesProvider>,
    );
  });

  expect(renderer!.root.findAllByType(StationCard)).toHaveLength(1);
});

it('never sends station card data back to the backend on the next message', async () => {
  const fetchMock = jest.fn(
    () => Promise.resolve(chatResponseWithStations('ok', [makeGasStation('Shell')])),
  );
  global.fetch = fetchMock as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <FavoritesProvider>
        <ChatScreen
          persistedChat={INITIAL_PERSISTED_CHAT}
          onChatComplete={jest.fn()}
          gasTabLocation={null}
          evTabLocation={null}
        />
      </FavoritesProvider>,
    );
  });

  await typeAndSend(renderer!, 'gas near me?');

  // The next send resends the full history — confirm it's still exactly
  // {role, content} per message, with nothing about the cards leaked in.
  global.fetch = jest.fn(() => Promise.resolve(chatResponse('ok'))) as unknown as typeof fetch;
  await typeAndSend(renderer!, 'anything cheaper?');

  const secondCallInit = (
    (global.fetch as jest.Mock).mock.calls[0] as unknown[]
  )[1] as RequestInit;
  const body = JSON.parse(secondCallInit.body as string) as {
    messages: Record<string, unknown>[];
  };
  for (const message of body.messages) {
    expect(Object.keys(message).sort()).toEqual(['content', 'role']);
  }
});

function pressAlertButton(
  alertSpy: ReturnType<typeof jest.spyOn>,
  buttonText: string,
) {
  const lastCall = alertSpy.mock.calls[alertSpy.mock.calls.length - 1];
  const buttons = lastCall[2] as {text: string; onPress?: () => void}[];
  buttons.find(b => b.text === buttonText)?.onPress?.();
}

it('does not show the New Chat button when there is no conversation yet', async () => {
  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  expect(() =>
    renderer!.root.findByProps({accessibilityLabel: 'Start a new chat'}),
  ).toThrow();
});

it('shows New Chat once a conversation exists, and clears everything when confirmed', async () => {
  const alertSpy = jest.spyOn(Alert, 'alert');
  global.fetch = jest.fn(() =>
    Promise.resolve(chatResponse('Hi there!')),
  ) as unknown as typeof fetch;
  const onChatComplete = jest.fn();

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={onChatComplete}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  await typeAndSend(renderer!, 'Hello');
  expect(texts(renderer!)).toContain('Hi there!');

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Start a new chat'})
      .props.onPress();
  });

  expect(alertSpy).toHaveBeenCalled();
  await act(async () => {
    pressAlertButton(alertSpy, 'Start New Chat');
  });

  expect(texts(renderer!).join(' ')).not.toContain('Hi there!');
  expect(texts(renderer!).join(' ')).toContain('Ask the GasAgent.ai assistant');
  expect(onChatComplete).toHaveBeenLastCalledWith({
    messages: [],
    error: null,
    cardsByMessageIndex: {},
  });

  alertSpy.mockRestore();
});

it('keeps the conversation when New Chat is cancelled', async () => {
  const alertSpy = jest.spyOn(Alert, 'alert');
  global.fetch = jest.fn(() =>
    Promise.resolve(chatResponse('Hi there!')),
  ) as unknown as typeof fetch;

  let renderer: ReactTestRenderer;
  await act(async () => {
    renderer = create(
      <ChatScreen
        persistedChat={INITIAL_PERSISTED_CHAT}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
        evTabLocation={null}
      />,
    );
  });

  await typeAndSend(renderer!, 'Hello');

  await act(async () => {
    renderer!.root
      .findByProps({accessibilityLabel: 'Start a new chat'})
      .props.onPress();
  });
  await act(async () => {
    pressAlertButton(alertSpy, 'Cancel');
  });

  expect(texts(renderer!).join(' ')).toContain('Hi there!');

  alertSpy.mockRestore();
});
