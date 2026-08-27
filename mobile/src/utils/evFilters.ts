import {EvStation} from '../api/client';
import {formatConnectorType} from './evConnectors';

export const UNKNOWN_NETWORK_KEY = '__unknown_network__';
export const UNKNOWN_NETWORK_LABEL = 'Unknown Network';

export type NetworkOption = {key: string; label: string};

function networkKey(station: EvStation): string {
  return station.network || UNKNOWN_NETWORK_KEY;
}

// Unlike gas's brandKey, an EV network name is used as-is rather than
// matched against a well-known list — both the directory and community
// sources already report a single canonical operator name (e.g.
// "ChargePoint", "EVgo"), so there's
// no spelling variance to normalize away. Stations with no reported
// network are bucketed under Unknown (sorted last), the same way gas
// stations with no brand fall into Other, rather than becoming
// unfilterable.
export function networkOptionsFromStations(
  stations: EvStation[],
): NetworkOption[] {
  const names = new Set<string>();
  let hasUnknown = false;
  for (const station of stations) {
    if (station.network) {
      names.add(station.network);
    } else {
      hasUnknown = true;
    }
  }
  const options: NetworkOption[] = Array.from(names)
    .sort((a, b) => a.localeCompare(b))
    .map(name => ({key: name, label: name}));
  if (hasUnknown) {
    options.push({key: UNKNOWN_NETWORK_KEY, label: UNKNOWN_NETWORK_LABEL});
  }
  return options;
}

// `selectedKeys` is an allowlist, not a blacklist — same reasoning as
// filterStationsByBrands: null means unfiltered (including networks
// discovered later via "load more"), a Set means show only those exact
// networks.
export function filterStationsByNetworks(
  stations: EvStation[],
  selectedKeys: Set<string> | null,
): EvStation[] {
  if (selectedKeys === null) {
    return stations;
  }
  return stations.filter(station => selectedKeys.has(networkKey(station)));
}

export const UNKNOWN_CONNECTOR_KEY = '__unknown_connector__';
export const UNKNOWN_CONNECTOR_LABEL = 'Unknown';

export type ConnectorOption = {key: string; label: string};

function connectorKeysForStation(station: EvStation): string[] {
  return station.connector_types.length > 0
    ? station.connector_types
    : [UNKNOWN_CONNECTOR_KEY];
}

export function connectorOptionsFromStations(
  stations: EvStation[],
): ConnectorOption[] {
  const codes = new Set<string>();
  let hasUnknown = false;
  for (const station of stations) {
    if (station.connector_types.length === 0) {
      hasUnknown = true;
    }
    station.connector_types.forEach(code => codes.add(code));
  }
  const options: ConnectorOption[] = Array.from(codes)
    .sort((a, b) =>
      formatConnectorType(a).localeCompare(formatConnectorType(b)),
    )
    .map(code => ({key: code, label: formatConnectorType(code)}));
  if (hasUnknown) {
    options.push({key: UNKNOWN_CONNECTOR_KEY, label: UNKNOWN_CONNECTOR_LABEL});
  }
  return options;
}

// A station can offer several connector types (e.g. both CCS and
// CHAdeMO) — it matches as long as at least one is in the allowlist,
// same "any of" logic filterStationsByChargerLevels uses.
export function filterStationsByConnectors(
  stations: EvStation[],
  selectedKeys: Set<string> | null,
): EvStation[] {
  if (selectedKeys === null) {
    return stations;
  }
  return stations.filter(station =>
    connectorKeysForStation(station).some(key => selectedKeys.has(key)),
  );
}

export type ChargerLevelKey = 'level1' | 'level2' | 'dc_fast';

export type ChargerLevelOption = {key: ChargerLevelKey; label: string};

// Fixed, unlike networks/connectors — mirrors how gas's fuel grade chips
// are always the same three options regardless of what's actually nearby,
// so a level doesn't disappear from the sheet just because nothing in the
// current results happens to report it.
export const CHARGER_LEVEL_OPTIONS: ChargerLevelOption[] = [
  {key: 'level1', label: 'Level 1'},
  {key: 'level2', label: 'Level 2'},
  {key: 'dc_fast', label: 'DC Fast'},
];

function chargerLevelsForStation(station: EvStation): ChargerLevelKey[] {
  const levels: ChargerLevelKey[] = [];
  if (station.level1_count) {
    levels.push('level1');
  }
  if (station.level2_count) {
    levels.push('level2');
  }
  if (station.dc_fast_count) {
    levels.push('dc_fast');
  }
  return levels;
}

export function filterStationsByChargerLevels(
  stations: EvStation[],
  selectedKeys: Set<ChargerLevelKey> | null,
): EvStation[] {
  if (selectedKeys === null) {
    return stations;
  }
  return stations.filter(station =>
    chargerLevelsForStation(station).some(level => selectedKeys.has(level)),
  );
}
