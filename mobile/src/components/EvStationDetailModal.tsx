import React, {useState} from 'react';
import {
  Image,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';

import {EvStation, EvStationComment} from '../api/client';
import {milesToKm} from '../utils/distance';
import {
  chargerCountSummary,
  connectorSpecLabel,
  formatConnectorSpecs,
  formatConnectorType,
  networkLogoUrl,
} from '../utils/evConnectors';
import {openDirections} from '../utils/maps';

type Props = {
  station: EvStation | null;
  onClose: () => void;
};

function NavigateIcon(): React.JSX.Element {
  return (
    <View style={styles.navigateIconCircle}>
      <View style={styles.navigateIconArrow} />
    </View>
  );
}

function NetworkLogo({url}: {url: string | null}): React.JSX.Element {
  const [failed, setFailed] = useState(false);

  if (url && !failed) {
    return (
      <Image
        source={{uri: url}}
        style={styles.iconWrap}
        resizeMode="contain"
        onError={() => setFailed(true)}
      />
    );
  }

  return (
    <View style={styles.iconWrap}>
      <Text style={styles.iconText}>⚡</Text>
    </View>
  );
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// AFDC dates are either a bare date or a full ISO timestamp — only the date
// part is meaningful for "last confirmed", so the time (if present) is
// dropped rather than shown.
function formatConfirmedDate(date: string): string {
  return date.split('T')[0];
}

function DetailRow({
  label,
  value,
}: {
  label: string;
  value: string | null;
}): React.JSX.Element | null {
  if (!value) {
    return null;
  }

  return (
    <View style={styles.detailRow}>
      <Text style={styles.detailRowLabel}>{label}</Text>
      <Text style={styles.detailRowValue}>{value}</Text>
    </View>
  );
}

function CommentCard({
  comment,
}: {
  comment: EvStationComment;
}): React.JSX.Element {
  return (
    <View style={styles.commentCard}>
      <View style={styles.commentHeader}>
        <Text style={styles.commentAuthor} numberOfLines={1}>
          {comment.author}
        </Text>
        {comment.date && (
          <Text style={styles.commentDate}>
            {formatConfirmedDate(comment.date)}
          </Text>
        )}
      </View>
      {comment.checkin_status && (
        <Text
          style={[
            styles.commentStatus,
            comment.checkin_is_positive === true &&
              styles.commentStatusPositive,
            comment.checkin_is_positive === false &&
              styles.commentStatusNegative,
          ]}>
          {comment.checkin_status}
        </Text>
      )}
      <Text style={styles.commentText}>{comment.text}</Text>
    </View>
  );
}

function EvStationDetailModal({station, onClose}: Props): React.JSX.Element {
  return (
    <Modal
      visible={station !== null}
      animationType="slide"
      transparent
      onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <TouchableOpacity
            style={styles.closeButton}
            onPress={onClose}
            hitSlop={{top: 8, bottom: 8, left: 8, right: 8}}
            accessibilityLabel="Close">
            <Text style={styles.closeIcon}>✕</Text>
          </TouchableOpacity>

          {station && (
            <ScrollView
              showsVerticalScrollIndicator={false}
              contentContainerStyle={styles.scrollContent}>
              <View style={styles.header}>
                <NetworkLogo
                  // Forces a fresh mount when a different station is
                  // selected, so a previous station's failed logo doesn't
                  // stick around as the fallback for this one — the modal
                  // itself never unmounts between selections.
                  key={station.station_id}
                  url={networkLogoUrl(station.network_web)}
                />
                <View style={styles.headerText}>
                  <Text style={styles.name} numberOfLines={2}>
                    {station.name}
                  </Text>
                  {station.network && (
                    <Text style={styles.network}>{station.network}</Text>
                  )}
                  {station.address && (
                    <Text style={styles.address}>{station.address}</Text>
                  )}
                  {station.distance_miles != null && (
                    <Text style={styles.distance}>
                      {milesToKm(station.distance_miles).toFixed(1)} km away
                    </Text>
                  )}
                </View>
              </View>

              {station.connector_types.length > 0 && (
                <View style={styles.chipsSection}>
                  <Text style={styles.chipsLabel}>Connector Types</Text>
                  <View style={styles.chipsList}>
                    {station.connector_types.map(type => (
                      <View key={type} style={styles.chip}>
                        <Text style={styles.chipText}>
                          {formatConnectorType(type)}
                        </Text>
                      </View>
                    ))}
                  </View>
                </View>
              )}

              {station.connector_details.length > 0 && (
                <View style={styles.chipsSection}>
                  <Text style={styles.chipsLabel}>Charger Specs</Text>
                  {station.connector_details.map((detail, index) => (
                    <DetailRow
                      key={`${detail.connector_type}-${index}`}
                      label={connectorSpecLabel(detail)}
                      value={formatConnectorSpecs(detail)}
                    />
                  ))}
                </View>
              )}

              <View style={styles.detailsSection}>
                <DetailRow
                  label="Chargers"
                  value={chargerCountSummary(station)}
                />
                <DetailRow
                  label="Access"
                  value={
                    station.access_code ? capitalize(station.access_code) : null
                  }
                />
                <DetailRow label="Hours" value={station.access_hours} />
                <DetailRow label="Phone" value={station.phone} />
                <DetailRow
                  label="Last confirmed"
                  value={
                    station.date_last_confirmed
                      ? formatConfirmedDate(station.date_last_confirmed)
                      : null
                  }
                />
              </View>

              {station.photo_urls.length > 0 && (
                <View style={styles.photosSection}>
                  <Text style={styles.chipsLabel}>Photos</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                    {station.photo_urls.map(url => (
                      <Image
                        key={url}
                        source={{uri: url}}
                        style={styles.photoThumbnail}
                        resizeMode="cover"
                      />
                    ))}
                  </ScrollView>
                </View>
              )}

              {station.comments.length > 0 && (
                <View style={styles.commentsSection}>
                  <Text style={styles.chipsLabel}>Community Notes</Text>
                  {station.comments.map(comment => (
                    <CommentCard
                      key={`${comment.author}-${comment.date}-${comment.text}`}
                      comment={comment}
                    />
                  ))}
                </View>
              )}

              <TouchableOpacity
                style={styles.navigateButton}
                disabled={station.latitude == null || station.longitude == null}
                onPress={() =>
                  station.latitude != null &&
                  station.longitude != null &&
                  openDirections(
                    station.latitude,
                    station.longitude,
                    station.name,
                  )
                }
                accessibilityLabel="Navigate to this station">
                <View style={styles.navigateButtonContent}>
                  <NavigateIcon />
                  <Text style={styles.navigateButtonText}>Navigate</Text>
                </View>
              </TouchableOpacity>
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0, 0, 0, 0.4)',
  },
  sheet: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingTop: 20,
    paddingHorizontal: 20,
    // Comments/photos can make the content tall enough to otherwise push
    // the top of the sheet off-screen (it's anchored to the bottom, not
    // centered) — capped and scrollable instead of growing unbounded.
    maxHeight: '85%',
  },
  scrollContent: {
    paddingBottom: 32,
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
  header: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginTop: 8,
    paddingRight: 36,
  },
  iconWrap: {
    width: 48,
    height: 48,
    borderRadius: 10,
    marginRight: 12,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#e3f3e6',
  },
  iconText: {
    fontSize: 24,
  },
  headerText: {
    flex: 1,
  },
  name: {
    fontSize: 20,
    fontWeight: '700',
  },
  network: {
    marginTop: 3,
    fontSize: 13,
    color: '#888',
  },
  address: {
    marginTop: 2,
    fontSize: 13,
    color: '#888',
  },
  distance: {
    marginTop: 4,
    fontSize: 13,
    color: '#666',
  },
  chipsSection: {
    marginTop: 20,
  },
  chipsLabel: {
    fontSize: 12,
    color: '#888',
    textTransform: 'uppercase',
    marginBottom: 8,
  },
  chipsList: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  chip: {
    backgroundColor: '#e3f3e6',
    borderRadius: 12,
    paddingVertical: 5,
    paddingHorizontal: 10,
  },
  chipText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#2e7d32',
  },
  detailsSection: {
    marginTop: 20,
  },
  detailRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#eee',
  },
  detailRowLabel: {
    fontSize: 14,
    color: '#444',
  },
  detailRowValue: {
    fontSize: 14,
    fontWeight: '600',
    color: '#222',
    flexShrink: 1,
    textAlign: 'right',
    marginLeft: 12,
  },
  navigateButton: {
    marginTop: 20,
    backgroundColor: '#2e7d32',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  navigateButtonContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  navigateButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  navigateIconCircle: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 1.5,
    borderColor: '#fff',
    backgroundColor: '#1b5e20',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 8,
  },
  navigateIconArrow: {
    width: 0,
    height: 0,
    borderLeftWidth: 4,
    borderRightWidth: 4,
    borderBottomWidth: 8,
    borderLeftColor: 'transparent',
    borderRightColor: 'transparent',
    borderBottomColor: '#fff',
    transform: [{rotate: '45deg'}],
    marginBottom: 1,
  },
  photosSection: {
    marginTop: 20,
  },
  photoThumbnail: {
    width: 96,
    height: 72,
    borderRadius: 10,
    marginRight: 8,
    backgroundColor: '#f2f2f2',
  },
  commentsSection: {
    marginTop: 20,
  },
  commentCard: {
    backgroundColor: '#f7f7f7',
    borderRadius: 10,
    padding: 12,
    marginBottom: 8,
  },
  commentHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  commentAuthor: {
    fontSize: 13,
    fontWeight: '700',
    color: '#333',
    flexShrink: 1,
    marginRight: 8,
  },
  commentDate: {
    fontSize: 11,
    color: '#999',
  },
  commentStatus: {
    marginTop: 4,
    fontSize: 11,
    fontWeight: '700',
    color: '#888',
    textTransform: 'uppercase',
  },
  commentStatusPositive: {
    color: '#2e7d32',
  },
  commentStatusNegative: {
    color: '#c62828',
  },
  commentText: {
    marginTop: 4,
    fontSize: 13,
    color: '#444',
  },
});

export default EvStationDetailModal;
