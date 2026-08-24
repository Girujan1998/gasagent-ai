import React from 'react';
import {StyleSheet, Text, TouchableOpacity, View} from 'react-native';

export type TabKey = 'home' | 'search' | 'chat' | 'favorites' | 'personal';

// Most tabs use a plain emoji glyph; a tab can instead provide a custom
// icon (built from Views, like the filter button's sliders icon) when no
// emoji reads as the right shape — an EV charging station, here.
type TabConfig = {
  key: TabKey;
  label: string;
  icon: string | ((active: boolean) => React.JSX.Element);
};

// A charging-station silhouette (body + display + bolt + plug) built from
// Views — no single emoji reads as "EV charger", so this mirrors the
// filter button's icon, which is built the same way for the same reason.
function EVChargerIcon({active}: {active: boolean}): React.JSX.Element {
  return (
    <View
      style={[styles.evIconWrap, active && styles.iconActive]}
      testID="ev-charger-icon">
      <View style={styles.evBody}>
        <View style={styles.evScreen} />
        <Text style={styles.evBolt}>⚡</Text>
      </View>
      <View style={styles.evPlugCord} />
      <View style={styles.evPlugHead} />
    </View>
  );
}

const LEFT_TABS: TabConfig[] = [
  {key: 'home', label: 'Gas', icon: '⛽'},
  {
    key: 'search',
    label: 'EV',
    icon: active => <EVChargerIcon active={active} />,
  },
];

const RIGHT_TABS: TabConfig[] = [
  {key: 'favorites', label: 'Favorites', icon: '⭐'},
  {key: 'personal', label: 'Forecasts', icon: '📈'},
];

// Always a plain emoji, unlike TabConfig — the raised center button never
// needs a custom icon, so this stays simpler than accommodating one.
const CENTER_TAB: {key: TabKey; label: string; icon: string} = {
  key: 'chat',
  label: 'Chat',
  icon: '💬',
};

const CENTER_BUTTON_SIZE = 56;

type Props = {
  activeTab: TabKey;
  onTabPress: (tab: TabKey) => void;
};

function TabButton({
  tab,
  active,
  onPress,
}: {
  tab: TabConfig;
  active: boolean;
  onPress: (tab: TabKey) => void;
}): React.JSX.Element {
  return (
    <TouchableOpacity
      style={styles.tab}
      activeOpacity={0.6}
      onPress={() => onPress(tab.key)}
      accessibilityLabel={tab.label}>
      {typeof tab.icon === 'string' ? (
        <Text style={[styles.icon, active && styles.iconActive]}>
          {tab.icon}
        </Text>
      ) : (
        tab.icon(active)
      )}
      <Text style={[styles.label, active && styles.labelActive]}>
        {tab.label}
      </Text>
    </TouchableOpacity>
  );
}

function BottomNavBar({activeTab, onTabPress}: Props): React.JSX.Element {
  return (
    <View style={styles.container}>
      <View style={styles.centerSlot} />
      <View style={styles.bar}>
        {LEFT_TABS.map(tab => (
          <TabButton
            key={tab.key}
            tab={tab}
            active={activeTab === tab.key}
            onPress={onTabPress}
          />
        ))}

        <View style={styles.centerSpacer} />

        {RIGHT_TABS.map(tab => (
          <TabButton
            key={tab.key}
            tab={tab}
            active={activeTab === tab.key}
            onPress={onTabPress}
          />
        ))}
      </View>

      <TouchableOpacity
        style={styles.centerButton}
        hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
        onPress={() => onTabPress(CENTER_TAB.key)}
        accessibilityLabel={CENTER_TAB.label}>
        <Text style={styles.centerIcon}>{CENTER_TAB.icon}</Text>
      </TouchableOpacity>
      <Text
        style={[
          styles.centerLabel,
          styles.centerLabelNonInteractive,
          activeTab === CENTER_TAB.key && styles.labelActive,
        ]}>
        {CENTER_TAB.label}
      </Text>
    </View>
  );
}

const ACCENT = '#4285f4';

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#fff',
  },
  centerSlot: {
    height: CENTER_BUTTON_SIZE / 2,
  },
  bar: {
    flexDirection: 'row',
    // 'stretch' (not 'center') so each tab's touchable area fills the
    // bar's full height — with 'center' the TouchableOpacity shrinks to
    // hug its icon+label content, leaving dead space above/below that
    // looks tappable but isn't.
    alignItems: 'stretch',
    paddingTop: 6,
    paddingBottom: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#e5e5e5',
  },
  tab: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  centerSpacer: {
    flex: 1,
  },
  icon: {
    fontSize: 20,
    opacity: 0.5,
  },
  iconActive: {
    opacity: 1,
  },
  evIconWrap: {
    width: 20,
    height: 20,
    alignItems: 'center',
    justifyContent: 'center',
    opacity: 0.5,
  },
  evBody: {
    width: 12,
    height: 17,
    borderWidth: 1.4,
    borderColor: '#333',
    borderRadius: 3,
    alignItems: 'center',
    paddingTop: 2,
  },
  evScreen: {
    width: 6,
    height: 3.5,
    borderWidth: 1,
    borderColor: '#333',
    borderRadius: 1,
  },
  evBolt: {
    fontSize: 7,
    lineHeight: 8,
    marginTop: 1,
  },
  evPlugCord: {
    position: 'absolute',
    right: 1,
    top: 9,
    width: 4,
    height: 1.3,
    backgroundColor: '#333',
    borderRadius: 1,
  },
  evPlugHead: {
    position: 'absolute',
    right: -2,
    top: 6.5,
    width: 3.5,
    height: 6,
    backgroundColor: '#333',
    borderRadius: 1,
  },
  label: {
    marginTop: 2,
    fontSize: 11,
    color: '#888',
  },
  labelActive: {
    color: ACCENT,
    fontWeight: '600',
  },
  centerButton: {
    position: 'absolute',
    top: 0,
    left: '50%',
    marginLeft: -CENTER_BUTTON_SIZE / 2,
    width: CENTER_BUTTON_SIZE,
    height: CENTER_BUTTON_SIZE,
    borderRadius: CENTER_BUTTON_SIZE / 2,
    backgroundColor: ACCENT,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 4,
    borderColor: '#fff',
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 3},
    shadowOpacity: 0.25,
    shadowRadius: 5,
    elevation: 8,
  },
  centerIcon: {
    fontSize: 22,
  },
  centerLabel: {
    position: 'absolute',
    top: CENTER_BUTTON_SIZE + 2,
    left: 0,
    right: 0,
    textAlign: 'center',
    fontSize: 11,
    color: '#888',
  },
  // Spans the full bar width (left:0, right:0) even though only "Chat"
  // renders in the middle — without this, its invisible hit-testable box
  // sits right at label height and swallows taps meant for Search/Favorites.
  centerLabelNonInteractive: {
    pointerEvents: 'none',
  },
});

export default BottomNavBar;
