/**
 * @format
 */

import Geolocation from '@react-native-community/geolocation';
import React, {useState} from 'react';
import {ActivityIndicator, FlatList, Text, TextInput} from 'react-native';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {it, expect, jest, beforeAll, afterEach, afterAll} from '@jest/globals';

import ChatScreen, {
  INITIAL_PERSISTED_CHAT,
  PersistedChat,
} from '../src/screens/ChatScreen';

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
}: {
  mounted: boolean;
  gasTabLocation?: {lat: number; lon: number} | null;
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
        }}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
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
      />,
    );
  });

  await typeAndSend(renderer!, 'Hello');

  expect(texts(renderer!)).toContain('Hello');
  expect(texts(renderer!).join(' ')).toContain('Invalid API Key');
  expect(onChatComplete).toHaveBeenCalledWith({
    messages: [{role: 'user', content: 'Hello'}],
    error: 'Invalid API Key',
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
        }}
        onChatComplete={jest.fn()}
        gasTabLocation={null}
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
      />,
    );
  });

  await typeAndSend(renderer!, 'gas near me?');

  const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
  const body = JSON.parse(init.body as string) as {
    location?: {lat: number; lon: number};
  };
  expect(body.location).toEqual({lat: 41.9, lon: -87.6});
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
    location?: {lat: number; lon: number};
  };
  expect(body.location).toEqual({lat: 1.0, lon: 2.0});
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
      />,
    );
  });

  await typeAndSend(renderer!, 'Hello');

  const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
  const body = JSON.parse(init.body as string) as {location?: unknown};
  expect(body.location).toBeUndefined();
});
