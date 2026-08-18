// Framed the way a driver actually cares about it: a price going up is
// bad news (red), a price going down is good news (green) — based purely
// on the change value's own sign. Shared by both forecast cards so a
// delta's color never depends on anything else (e.g. which column it's
// shown in, or the separate "flat" trend classification used for the
// overall Rising/Falling/Steady label).
export function priceChangeColor(value: number | null): string {
  if (value == null || value === 0) {
    return '#888';
  }
  return value > 0 ? '#c62828' : '#2e7d32';
}
