import React, {useEffect, useRef, useState} from 'react';
import {
  Animated,
  Image,
  LayoutAnimation,
  PanResponder,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  UIManager,
  View,
} from 'react-native';

import {GasStation} from '../api/client';
import {moveInArray} from '../utils/reorder';

// LayoutAnimation is opt-in on Android (already the default on iOS) — this
// is a one-time, module-level flag, not per-render setup.
if (
  Platform.OS === 'android' &&
  UIManager.setLayoutAnimationEnabledExperimental
) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

const ROW_HEIGHT = 68;
const ROW_SPACING = 10;
const SLOT_HEIGHT = ROW_HEIGHT + ROW_SPACING;

type Props = {
  stations: GasStation[];
  onReorder: (stations: GasStation[]) => void;
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

// Keeps a ref in sync with the latest value on every render, so a
// long-lived callback (like PanResponder's, created once via useRef and
// never recreated) can read current props/state instead of whatever was
// captured the first time it ran.
function useLatest<T>(value: T): React.MutableRefObject<T> {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}

function BrandGlyph({url}: {url: string | null}): React.JSX.Element {
  const [failed, setFailed] = useState(false);

  if (url && !failed) {
    return (
      <Image
        source={{uri: url}}
        style={styles.logo}
        resizeMode="contain"
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <View style={[styles.logo, styles.logoFallback]}>
      <Text style={styles.logoFallbackIcon}>⛽</Text>
    </View>
  );
}

// Exported only so tests can drive the reorder logic directly (calling
// onDragStart/onMove/onDragEnd as the real PanResponder handlers would) —
// simulating a raw touch gesture accurately enough to exercise
// PanResponder's own internal gesture math isn't practical in a component
// test, and isn't app logic that needs re-testing here anyway.
export function ReorderableRow({
  station,
  currentIndex,
  count,
  isDragging,
  onMove,
  onDragStart,
  onDragEnd,
}: {
  station: GasStation;
  currentIndex: number;
  count: number;
  isDragging: boolean;
  onMove: (fromIndex: number, toIndex: number) => void;
  onDragStart: (stationId: string) => void;
  onDragEnd: () => void;
}): React.JSX.Element {
  const translateY = useRef(new Animated.Value(0)).current;

  // The row's own index/count/callbacks all change over time (as other
  // rows are dragged, or as this row itself moves from a previous drag),
  // but the PanResponder below is created exactly once — so every value
  // it needs mid-gesture is read from one of these refs, not closed over
  // directly, to avoid acting on stale data from whenever it was created.
  const currentIndexRef = useLatest(currentIndex);
  const countRef = useLatest(count);
  const onMoveRef = useLatest(onMove);
  const onDragStartRef = useLatest(onDragStart);
  const onDragEndRef = useLatest(onDragEnd);

  // Set once per gesture (in onPanResponderGrant) — the slot this row
  // started the drag from, which gestureState.dy is always measured
  // relative to.
  const startIndexRef = useRef(currentIndex);
  // The slot this row currently occupies mid-gesture, so a further move
  // only fires onMove when the hovered slot actually changes.
  const liveIndexRef = useRef(currentIndex);

  const panResponder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onPanResponderGrant: () => {
        startIndexRef.current = currentIndexRef.current;
        liveIndexRef.current = currentIndexRef.current;
        onDragStartRef.current(station.station_id);
      },
      onPanResponderMove: (_evt, gesture) => {
        translateY.setValue(gesture.dy);
        const hoverIndex = clamp(
          Math.round(startIndexRef.current + gesture.dy / SLOT_HEIGHT),
          0,
          countRef.current - 1,
        );
        if (hoverIndex !== liveIndexRef.current) {
          onMoveRef.current(liveIndexRef.current, hoverIndex);
          liveIndexRef.current = hoverIndex;
        }
      },
      onPanResponderRelease: () => {
        Animated.spring(translateY, {
          toValue: 0,
          useNativeDriver: true,
          friction: 9,
        }).start();
        onDragEndRef.current();
      },
      onPanResponderTerminate: () => {
        Animated.spring(translateY, {
          toValue: 0,
          useNativeDriver: true,
          friction: 9,
        }).start();
        onDragEndRef.current();
      },
    }),
  ).current;

  return (
    <Animated.View
      style={[
        styles.row,
        {top: currentIndex * SLOT_HEIGHT, transform: [{translateY}]},
        isDragging && styles.rowDragging,
      ]}>
      <BrandGlyph url={station.brand_logo_url} />
      <View style={styles.rowText}>
        <Text style={styles.rowName} numberOfLines={1}>
          {station.brand || station.name}
        </Text>
        {station.address && (
          <Text style={styles.rowAddress} numberOfLines={1}>
            {station.address}
          </Text>
        )}
      </View>
      <View
        style={styles.handle}
        {...panResponder.panHandlers}
        accessibilityLabel={`Drag to reorder ${station.brand || station.name}`}>
        <Text style={styles.handleIcon}>☰</Text>
      </View>
    </Animated.View>
  );
}

function ReorderableFavoritesList({
  stations,
  onReorder,
}: Props): React.JSX.Element {
  // A local working copy, updated live (with a smooth LayoutAnimation)
  // as rows swap past each other mid-drag — onReorder (which persists to
  // AsyncStorage via FavoritesContext) only fires once, on drop, not on
  // every slot crossing.
  const [order, setOrder] = useState(stations);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const orderRef = useLatest(order);
  const draggingIdRef = useLatest(draggingId);

  // Resyncs if the underlying favorites change for a reason other than
  // this component's own drags (e.g. a favorite removed from another
  // screen) — never while a drag is actually in progress, so it can't
  // yank a row out from under the user's finger.
  useEffect(() => {
    if (draggingIdRef.current === null) {
      setOrder(stations);
    }
  }, [stations, draggingIdRef]);

  const handleMove = (fromIndex: number, toIndex: number) => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setOrder(prev => moveInArray(prev, fromIndex, toIndex));
  };

  const handleDragEnd = () => {
    setDraggingId(null);
    onReorder(orderRef.current);
  };

  return (
    <ScrollView
      style={styles.container}
      scrollEnabled={draggingId === null}
      contentContainerStyle={{
        height: order.length * SLOT_HEIGHT + ROW_SPACING,
      }}>
      {order.map((station, index) => (
        <ReorderableRow
          key={station.station_id}
          station={station}
          currentIndex={index}
          count={order.length}
          isDragging={draggingId === station.station_id}
          onMove={handleMove}
          onDragStart={setDraggingId}
          onDragEnd={handleDragEnd}
        />
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  row: {
    position: 'absolute',
    left: 16,
    right: 16,
    height: ROW_HEIGHT,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 14,
    paddingHorizontal: 14,
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 1},
    shadowOpacity: 0.1,
    shadowRadius: 3,
    elevation: 2,
  },
  rowDragging: {
    zIndex: 1,
    shadowOpacity: 0.25,
    shadowRadius: 8,
    elevation: 6,
  },
  logo: {
    width: 26,
    height: 26,
    borderRadius: 6,
    marginRight: 10,
    backgroundColor: '#f2f2f2',
  },
  logoFallback: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#dbe6f6',
  },
  logoFallbackIcon: {
    fontSize: 14,
  },
  rowText: {
    flex: 1,
    marginRight: 8,
  },
  rowName: {
    fontSize: 15,
    fontWeight: '700',
  },
  rowAddress: {
    fontSize: 12,
    color: '#888',
    marginTop: 2,
  },
  handle: {
    width: 32,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  handleIcon: {
    fontSize: 20,
    color: '#aaa',
  },
});

export default ReorderableFavoritesList;
