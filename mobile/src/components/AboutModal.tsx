import React, {useState} from 'react';
import {Modal, ScrollView, StyleSheet, Text, TouchableOpacity, View} from 'react-native';

// Kept as plain data rather than inline JSX so the wording is easy to
// review/update as one block, independent of layout.
const SOURCES: {name: string; detail: string}[] = [
  {
    name: 'GasBuddy',
    detail:
      "Gas station listings and prices, retrieved via py-gasbuddy, an " +
      "open-source library that calls GasBuddy's own public GraphQL API.",
  },
  {
    name: "NREL's Alternative Fuel Data Center",
    detail: 'EV charging station listings.',
  },
  {
    name: 'Open Charge Map',
    detail: 'Community-reported EV charging station details and reviews.',
  },
  {
    name: 'U.S. Energy Information Administration (EIA)',
    detail: 'National gas price trend data used for the US price forecast.',
  },
  {
    name: 'Statistics Canada',
    detail:
      'National gas price trend data used for the Canadian price forecast.',
  },
  {
    name: 'Google Gemini',
    detail: "Powers the app's AI agent.",
  },
];

function AboutModal(): React.JSX.Element {
  const [open, setOpen] = useState(false);

  return (
    <>
      <TouchableOpacity
        style={styles.trigger}
        onPress={() => setOpen(true)}
        hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
        accessibilityLabel="About this app">
        <Text style={styles.triggerIcon}>ⓘ</Text>
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
          accessibilityLabel="Close about">
          <View style={styles.sheet}>
            <TouchableOpacity
              style={styles.closeButton}
              onPress={() => setOpen(false)}
              hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
              accessibilityLabel="Close">
              <Text style={styles.closeIcon}>✕</Text>
            </TouchableOpacity>

            <Text style={styles.sheetTitle}>About GasAgent.ai</Text>

            <ScrollView
              style={styles.scrollArea}
              showsVerticalScrollIndicator={false}>
              <Text style={styles.paragraph}>
                GasAgent.ai is an independent personal project built as a
                technical demonstration. It is not affiliated with,
                sponsored by, or endorsed by any of the data sources or
                companies below.
              </Text>

              <Text style={styles.sectionLabel}>Data sources</Text>
              {SOURCES.map(source => (
                <View key={source.name} style={styles.sourceRow}>
                  <Text style={styles.sourceName}>{source.name}</Text>
                  <Text style={styles.sourceDetail}>{source.detail}</Text>
                </View>
              ))}

              <Text style={styles.paragraph}>
                All product names, logos, and brands mentioned above are
                property of their respective owners and are used here only
                to identify where the underlying data comes from.
              </Text>
            </ScrollView>
          </View>
        </TouchableOpacity>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  trigger: {
    width: 30,
    height: 30,
    alignItems: 'center',
    justifyContent: 'center',
  },
  triggerIcon: {
    fontSize: 20,
    color: '#888',
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
  sheetTitle: {
    fontSize: 18,
    fontWeight: '700',
    marginBottom: 12,
  },
  scrollArea: {
    flexGrow: 0,
    flexShrink: 1,
  },
  paragraph: {
    fontSize: 14,
    color: '#444',
    lineHeight: 20,
    marginBottom: 12,
  },
  sectionLabel: {
    fontSize: 12,
    color: '#888',
    textTransform: 'uppercase',
    marginBottom: 8,
  },
  sourceRow: {
    marginBottom: 12,
  },
  sourceName: {
    fontSize: 14,
    fontWeight: '700',
    color: '#222',
  },
  sourceDetail: {
    fontSize: 13,
    color: '#666',
    marginTop: 2,
    lineHeight: 18,
  },
});

export default AboutModal;
