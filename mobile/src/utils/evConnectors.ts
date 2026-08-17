import {EvConnectorDetail, EvStation} from '../api/client';

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

// AFDC has no brand_logo_url field the way GasBuddy does — network_web (the
// operator's own site, e.g. "https://www.chargepoint.com") is the only
// thing identifying which network a station belongs to, so the logo is
// derived from that site's own favicon rather than a maintained lookup
// table of network logo URLs.
export function networkLogoUrl(networkWeb: string | null): string | null {
  if (!networkWeb) {
    return null;
  }
  const domain = networkWeb.replace(/^https?:\/\//, '').split('/')[0];
  if (!domain) {
    return null;
  }
  return `https://www.google.com/s2/favicons?sz=64&domain=${encodeURIComponent(
    domain,
  )}`;
}

// OCM-only — AFDC has no per-connector power/voltage/amperage data at all,
// so this returns null for any AFDC-sourced connector. Only the specs that
// are actually reported are included, in the order a driver would care
// about them (how fast, then the electrical detail behind that).
export function formatConnectorSpecs(detail: EvConnectorDetail): string | null {
  const parts: string[] = [];
  if (detail.power_kw != null) {
    parts.push(`${detail.power_kw} kW`);
  }
  if (detail.voltage != null) {
    parts.push(`${detail.voltage} V`);
  }
  if (detail.amps != null) {
    parts.push(`${detail.amps} A`);
  }
  return parts.length > 0 ? parts.join(' · ') : null;
}

// A connector's label for a specs row — includes the quantity only when
// there's more than one of that exact connector (matching specs), since
// "J1772 ×1" reads as noise.
export function connectorSpecLabel(detail: EvConnectorDetail): string {
  const type = formatConnectorType(detail.connector_type);
  return detail.quantity && detail.quantity > 1
    ? `${type} ×${detail.quantity}`
    : type;
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
