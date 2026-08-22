import Geolocation from '@react-native-community/geolocation';
import React, {useRef, useState} from 'react';
import {
  ActivityIndicator,
  FlatList,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';

import {ChatMessage, sendChatMessage} from '../api/client';
import {requestLocationPermission} from '../utils/location';

// What survives a tab switch: the conversation so far, and any error from
// the last send attempt. There's no server-side session yet (see
// ChatMessage's doc comment in the backend) — the full history is
// what makes the agent aware of earlier turns at all. A shared/fallback
// location is deliberately NOT part of this — see gpsLocation below.
export type PersistedChat = {
  messages: ChatMessage[];
  error: string | null;
};

export const INITIAL_PERSISTED_CHAT: PersistedChat = {
  messages: [],
  error: null,
};

type Location = {lat: number; lon: number};

type Props = {
  persistedChat: PersistedChat;
  onChatComplete: (chat: PersistedChat) => void;
  // The Gas tab's last-searched location, if any — a fallback so "gas
  // stations near me" can work in Chat without asking for GPS first, the
  // same value already shared with the Notifications tab (see App.tsx).
  gasTabLocation: Location | null;
};

function MessageBubble({message}: {message: ChatMessage}): React.JSX.Element {
  const isUser = message.role === 'user';
  return (
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
  );
}

function ChatScreen({
  persistedChat,
  onChatComplete,
  gasTabLocation,
}: Props): React.JSX.Element {
  const [messages, setMessages] = useState<ChatMessage[]>(
    persistedChat.messages,
  );
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(persistedChat.error);
  const listRef = useRef<FlatList<ChatMessage>>(null);

  // A fresh GPS fix, requested on demand (same shape as FavoritesScreen's
  // handleShareLocation) — deliberately local, not lifted to App.tsx, so
  // it resets on tab switch just like Favorites' does.
  const [gpsLocation, setGpsLocation] = useState<Location | null>(null);
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);

  // A fresh GPS fix always wins over the Gas tab's possibly-stale last
  // search — recomputed on every send so sharing location mid-conversation
  // takes effect on the very next message.
  const effectiveLocation = gpsLocation ?? gasTabLocation ?? null;

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
        setGpsLocation({
          lat: position.coords.latitude,
          lon: position.coords.longitude,
        });
        setLocating(false);
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
      const response = await sendChatMessage(nextMessages, effectiveLocation);
      const withReply = [...nextMessages, response.message];
      setMessages(withReply);
      onChatComplete({messages: withReply, error: null});
    } catch (err) {
      // The user's own message stays on screen either way — only the
      // reply failed, not their side of the conversation.
      const message =
        err instanceof Error ? err.message : 'Failed to send message.';
      setError(message);
      onChatComplete({messages: nextMessages, error: message});
    } finally {
      setSending(false);
    }
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Chat</Text>
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

      {messages.length === 0 ? (
        <View style={styles.intro}>
          <Text style={styles.introTitle}>Ask the GasAgent.ai assistant</Text>
          <Text style={styles.introSubtitle}>
            Ask about nearby gas stations, prices, or general questions — share
            your location above for stations near you.
          </Text>
        </View>
      ) : (
        <FlatList
          ref={listRef}
          style={styles.list}
          contentContainerStyle={styles.listContent}
          data={messages}
          keyExtractor={(_, index) => String(index)}
          renderItem={({item}) => <MessageBubble message={item} />}
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
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    paddingHorizontal: 16,
    paddingTop: 16,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
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
