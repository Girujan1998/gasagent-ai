import Geolocation from '@react-native-community/geolocation';
import React, {useRef, useState} from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  TouchableWithoutFeedback,
  View,
} from 'react-native';

import {
  ChatMessage,
  EvStation,
  GasStation,
  sendChatMessage,
} from '../api/client';
import EvStationCard from '../components/EvStationCard';
import StationCard from '../components/StationCard';
import {useSharedLocation} from '../store/LocationContext';
import {requestLocationPermission} from '../utils/location';

// What survives a tab switch: the conversation so far, any error from the
// last send attempt, and a shared GPS fix if the user has given one this
// session — sharing it once shouldn't mean re-sharing it every time this
// tab is revisited. There's no server-side session yet (see ChatMessage's
// doc comment in the backend) — the full history is what makes the agent
// aware of earlier turns at all.
//
// Card data for a message is kept in its OWN map, keyed by index into
// `messages`, rather than as a property on the ChatMessage objects
// themselves — `messages` is exactly what gets JSON.stringify'd into the
// next sendChatMessage request body (see handleSend below), so anything
// placed directly on a ChatMessage would round-trip back to the backend
// (and from there, into every future Gemini call) forever. Safe to key by
// index here since messages are only ever appended, never reordered or
// removed.
export type ChatCardsForMessage = {
  gasStations: GasStation[];
  evStations: EvStation[];
};

type Location = {lat: number; lon: number};

export type PersistedChat = {
  messages: ChatMessage[];
  error: string | null;
  cardsByMessageIndex: Record<number, ChatCardsForMessage>;
  gpsLocation: Location | null;
};

export const INITIAL_PERSISTED_CHAT: PersistedChat = {
  messages: [],
  error: null,
  cardsByMessageIndex: {},
  gpsLocation: null,
};

type Props = {
  persistedChat: PersistedChat;
  onChatComplete: (chat: PersistedChat) => void;
  // The Gas tab's last-searched location, if any — a fallback so "gas
  // stations near me" can work in Chat without asking for GPS first, the
  // same value already shared with the Forecasts tab (see App.tsx).
  gasTabLocation: Location | null;
  // Same idea for EV questions, but sourced from the EV tab's last search
  // instead — kept separate from gasTabLocation since the two tabs can be
  // searched at different places.
  evTabLocation: Location | null;
};

function MessageBubble({
  message,
  cards,
}: {
  message: ChatMessage;
  cards?: ChatCardsForMessage;
}): React.JSX.Element {
  const isUser = message.role === 'user';
  return (
    <View>
      <View style={[styles.bubbleRow, isUser && styles.bubbleRowUser]}>
        <View
          style={[
            styles.bubble,
            isUser ? styles.bubbleUser : styles.bubbleAssistant,
          ]}>
          <Text style={[styles.bubbleText, isUser && styles.bubbleTextUser]}>
            {message.content}
          </Text>
        </View>
      </View>
      {cards &&
        (cards.gasStations.length > 0 || cards.evStations.length > 0) && (
          <View style={styles.cardsColumn}>
            {cards.gasStations.map(station => (
              <StationCard key={station.station_id} station={station} />
            ))}
            {cards.evStations.map(station => (
              <EvStationCard key={station.station_id} station={station} />
            ))}
          </View>
        )}
    </View>
  );
}

function ChatScreen({
  persistedChat,
  onChatComplete,
  gasTabLocation,
  evTabLocation,
}: Props): React.JSX.Element {
  const {location: sharedLocation, setSharedGpsLocation} = useSharedLocation();
  const [messages, setMessages] = useState<ChatMessage[]>(
    persistedChat.messages,
  );
  const [cardsByMessageIndex, setCardsByMessageIndex] = useState<
    Record<number, ChatCardsForMessage>
  >(persistedChat.cardsByMessageIndex);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(persistedChat.error);
  const listRef = useRef<FlatList<ChatMessage>>(null);

  // A fresh GPS fix, requested on demand (same shape as FavoritesScreen's
  // handleShareLocation) — seeded from persistedChat and written back to
  // it in handleShareLocation, so sharing it once carries across tab
  // switches instead of asking again every time.
  const [gpsLocation, setGpsLocation] = useState<Location | null>(
    persistedChat.gpsLocation,
  );
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);

  // A fresh GPS fix always wins over either tab's possibly-stale last
  // search — recomputed on every send so sharing location mid-conversation
  // takes effect on the very next message. Gas and EV questions fall back
  // to their own tab's last search rather than sharing one fallback, since
  // the two tabs can be searched at different places. `sharedLocation` is
  // the last resort — a location shared from Favorites (or any tab before
  // either Gas or EV has ever been searched this session) still gives Chat
  // something to work with instead of nothing.
  const gasLocation = gpsLocation ?? gasTabLocation ?? sharedLocation ?? null;
  const evLocation = gpsLocation ?? evTabLocation ?? sharedLocation ?? null;

  const handleShareLocation = async () => {
    setLocationError(null);
    setLocating(true);

    const hasPermission = await requestLocationPermission();
    if (!hasPermission) {
      setLocationError('Location permission denied.');
      setLocating(false);
      return;
    }

    Geolocation.getCurrentPosition(
      position => {
        const nextGpsLocation = {
          lat: position.coords.latitude,
          lon: position.coords.longitude,
        };
        setGpsLocation(nextGpsLocation);
        setSharedGpsLocation(nextGpsLocation);
        setLocating(false);
        onChatComplete({
          messages,
          error,
          cardsByMessageIndex,
          gpsLocation: nextGpsLocation,
        });
      },
      err => {
        setLocationError(err.message || 'Could not get current location.');
        setLocating(false);
      },
      {enableHighAccuracy: true, timeout: 15000},
    );
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) {
      return;
    }

    const nextMessages = [...messages, {role: 'user', content: text} as const];
    setMessages(nextMessages);
    setInput('');
    setError(null);
    setSending(true);

    try {
      const response = await sendChatMessage(
        nextMessages,
        gasLocation,
        evLocation,
      );
      const withReply = [...nextMessages, response.message];
      setMessages(withReply);

      // The reply lands at this index in `withReply` — record its cards
      // there (never on the ChatMessage itself, see PersistedChat's own
      // comment on why) only when there actually are any, to keep most
      // turns out of this map entirely. Defensive `?? []`: the backend
      // always sends these today, but a response missing them shouldn't
      // crash the send.
      const replyIndex = withReply.length - 1;
      const gasStations = response.gas_stations ?? [];
      const evStations = response.ev_stations ?? [];
      const hasCards = gasStations.length > 0 || evStations.length > 0;
      const nextCardsByMessageIndex = hasCards
        ? {
            ...cardsByMessageIndex,
            [replyIndex]: {gasStations, evStations},
          }
        : cardsByMessageIndex;
      setCardsByMessageIndex(nextCardsByMessageIndex);

      onChatComplete({
        messages: withReply,
        error: null,
        cardsByMessageIndex: nextCardsByMessageIndex,
        gpsLocation,
      });
    } catch (err) {
      // The user's own message stays on screen either way — only the
      // reply failed, not their side of the conversation.
      const message =
        err instanceof Error ? err.message : 'Failed to send message.';
      setError(message);
      onChatComplete({
        messages: nextMessages,
        error: message,
        cardsByMessageIndex,
        gpsLocation,
      });
    } finally {
      setSending(false);
    }
  };

  const handleClearChat = () => {
    Alert.alert(
      'Start a new chat?',
      "This deletes the current conversation. This can't be undone.",
      [
        {text: 'Cancel', style: 'cancel'},
        {
          text: 'Start New Chat',
          style: 'destructive',
          onPress: () => {
            setMessages([]);
            setCardsByMessageIndex({});
            setError(null);
            // gpsLocation deliberately survives a "New Chat" — starting a
            // fresh conversation doesn't mean the user's physical location
            // changed, so there's no reason to make them re-share it.
            onChatComplete({
              messages: [],
              error: null,
              cardsByMessageIndex: {},
              gpsLocation,
            });
          },
        },
      ],
    );
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={styles.container}>
        {/* TouchableWithoutFeedback deliberately does NOT wrap the FlatList
            below — nesting a scrollable list inside one is a known way to
            break its scroll gesture on a real device (not always caught by
            the Simulator or by tests). The list dismisses the keyboard on
            its own via keyboardDismissMode instead; this only covers the
            static header/banner area above it. */}
        <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
          <View>
            <View style={styles.header}>
              <Text style={styles.title}>Chat</Text>
              {messages.length > 0 && (
                <TouchableOpacity
                  onPress={handleClearChat}
                  accessibilityLabel="Start a new chat">
                  <Text style={styles.clearButtonText}>New Chat</Text>
                </TouchableOpacity>
              )}
            </View>

            {!gpsLocation && (
              <TouchableOpacity
                style={styles.locationBanner}
                onPress={handleShareLocation}
                disabled={locating}
                accessibilityLabel="Share your location">
                {locating ? (
                  <ActivityIndicator size="small" color="#1565c0" />
                ) : (
                  <Text style={styles.locationBannerText}>
                    {gasTabLocation
                      ? '📍 Using your last searched location — tap to use your current location instead'
                      : '📍 Share your location to find gas stations near you'}
                  </Text>
                )}
              </TouchableOpacity>
            )}
            {locationError && (
              <Text style={styles.locationError}>{locationError}</Text>
            )}
          </View>
        </TouchableWithoutFeedback>

        {messages.length === 0 ? (
          <TouchableWithoutFeedback
            onPress={Keyboard.dismiss}
            accessible={false}>
            <View style={styles.intro}>
              <Text style={styles.introTitle}>
                Ask the GasAgent.ai assistant
              </Text>
              <Text style={styles.introSubtitle}>
                Ask about nearby gas stations, prices, or general questions —
                share your location above for stations near you.
              </Text>
            </View>
          </TouchableWithoutFeedback>
        ) : (
          <FlatList
            ref={listRef}
            style={styles.list}
            contentContainerStyle={styles.listContent}
            data={messages}
            keyExtractor={(_, index) => String(index)}
            renderItem={({item, index}) => (
              <MessageBubble
                message={item}
                cards={cardsByMessageIndex[index]}
              />
            )}
            // Lets the user dismiss the keyboard by dragging the list,
            // same as most chat apps — "handled" keeps taps on cards
            // (e.g. a favorite star) working normally instead of the
            // first tap only closing the keyboard.
            keyboardDismissMode="on-drag"
            keyboardShouldPersistTaps="handled"
            // onContentSizeChange alone isn't reliable for a fresh mount
            // with an already-long history (e.g. switching back to this
            // tab) — it can fire before the list has actually laid out, so
            // scrollToEnd silently no-ops and the user lands mid-scroll.
            // onLayout fires once the list itself is actually laid out, so
            // it catches that case with an instant (non-animated) jump;
            // onContentSizeChange still handles a genuinely new message
            // arriving mid-session with its animated scroll.
            onLayout={() => listRef.current?.scrollToEnd({animated: false})}
            onContentSizeChange={() =>
              listRef.current?.scrollToEnd({animated: true})
            }
          />
        )}

        {sending && (
          <View style={styles.typingRow}>
            <ActivityIndicator size="small" color="#1565c0" />
            <Text style={styles.typingText}>Thinking…</Text>
          </View>
        )}

        {error && <Text style={styles.error}>⚠️ {error}</Text>}
      </View>

      <View style={styles.composerRow}>
        <TextInput
          style={styles.input}
          value={input}
          onChangeText={setInput}
          placeholder="Message the assistant…"
          placeholderTextColor="#999"
          multiline
          editable={!sending}
        />
        <TouchableOpacity
          style={[
            styles.sendButton,
            (!input.trim() || sending) && styles.sendButtonDisabled,
          ]}
          onPress={handleSend}
          disabled={!input.trim() || sending}
          accessibilityLabel="Send message">
          <Text style={styles.sendButtonText}>Send</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 16,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
  },
  clearButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1565c0',
  },
  locationBanner: {
    marginHorizontal: 16,
    marginTop: 12,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 12,
    backgroundColor: '#dbe6f6',
    alignItems: 'center',
  },
  locationBannerText: {
    fontSize: 13,
    color: '#1565c0',
    fontWeight: '600',
    textAlign: 'center',
  },
  locationError: {
    marginTop: 8,
    marginHorizontal: 16,
    fontSize: 12,
    color: '#c62828',
    textAlign: 'center',
  },
  intro: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  introTitle: {
    fontSize: 17,
    fontWeight: '700',
    textAlign: 'center',
  },
  introSubtitle: {
    fontSize: 14,
    color: '#666',
    marginTop: 8,
    textAlign: 'center',
  },
  list: {
    flex: 1,
  },
  listContent: {
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  bubbleRow: {
    flexDirection: 'row',
    marginVertical: 4,
  },
  bubbleRowUser: {
    justifyContent: 'flex-end',
  },
  bubble: {
    maxWidth: '80%',
    borderRadius: 16,
    paddingVertical: 10,
    paddingHorizontal: 14,
  },
  bubbleAssistant: {
    backgroundColor: '#f0f0f0',
  },
  bubbleUser: {
    backgroundColor: '#1565c0',
  },
  bubbleText: {
    fontSize: 15,
    color: '#222',
    lineHeight: 20,
  },
  bubbleTextUser: {
    color: '#fff',
  },
  cardsColumn: {
    marginTop: 8,
    marginBottom: 4,
    gap: 8,
    // StationCard/EvStationCard both carry their own marginHorizontal:16
    // (sized for the Gas/EV tabs' own edge-to-edge lists) — this list's
    // own paddingHorizontal:16 would double that indent otherwise, so it
    // cancels out here to keep cards flush with the bubbles above them.
    marginHorizontal: -16,
  },
  typingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingBottom: 6,
    gap: 8,
  },
  typingText: {
    fontSize: 13,
    color: '#888',
  },
  error: {
    fontSize: 13,
    color: '#c62828',
    paddingHorizontal: 16,
    paddingBottom: 6,
  },
  composerRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingHorizontal: 16,
    paddingBottom: 16,
    paddingTop: 8,
    gap: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#eee',
  },
  input: {
    flex: 1,
    maxHeight: 120,
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    backgroundColor: '#f2f2f2',
    fontSize: 15,
    color: '#222',
  },
  sendButton: {
    borderRadius: 20,
    paddingHorizontal: 18,
    paddingVertical: 12,
    backgroundColor: '#1565c0',
  },
  sendButtonDisabled: {
    backgroundColor: '#b7c9de',
  },
  sendButtonText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '700',
  },
});

export default ChatScreen;
