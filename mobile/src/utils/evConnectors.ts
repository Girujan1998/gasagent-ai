import {EvStation} from '../api/client';

// AFDC's own connector codes, mapped to the names drivers actually
// recognize. Anything not in this table (a code AFDC adds later, or an
// unusual one) is passed through as-is rather than hidden.
const CONNECTOR_LABELS: Record<string, string> = {
  J1772: 'J1772',
  CHADEMO: 'CHAdeMO',
  J1772COMBO: 'CCS',
  NEMA1450: 'NEMA 14-50',
  TESLA: 'Tesla',
};

export function formatConnectorType(type: string): string {
  return CONNECTOR_LABELS[type.toUpperCase()] ?? type;
}

// Only counts that are actually reported (non-null, non-zero) are included
// — most stations only have one or two of the three levels.
export function chargerCountSummary(station: EvStation): string | null {
  const parts: string[] = [];
  if (station.level1_count) {
    parts.push(`${station.level1_count} Level 1`);
  }
  if (station.level2_count) {
    parts.push(`${station.level2_count} Level 2`);
  }
  if (station.dc_fast_count) {
    parts.push(`${station.dc_fast_count} DC Fast`);
  }
  return parts.length > 0 ? parts.join(' · ') : null;
}
