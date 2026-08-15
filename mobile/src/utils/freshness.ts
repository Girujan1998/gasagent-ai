type ColorStop = {minutes: number; rgb: [number, number, number]};

// Applied directly as text color (no background chip), so these need to be
// dark/saturated enough to read on the card's white background — close
// relatives of the app's existing status colors (#2e7d32 green, #f5a623
// amber, #c62828 red). Continuous scale — the minute values below are
// reference points the color passes through, not hard cutoffs; everything
// in between is linearly interpolated.
const STOPS: ColorStop[] = [
  {minutes: 0, rgb: [27, 122, 61]}, // fresh — green
  {minutes: 30, rgb: [183, 121, 31]}, // amber
  {minutes: 60, rgb: [194, 84, 12]}, // orange
  {minutes: 90, rgb: [185, 28, 28]}, // red — holds flat past this point
];

function lerp(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t);
}

function toRgbString([r, g, b]: [number, number, number]): string {
  return `rgb(${r}, ${g}, ${b})`;
}

export function freshnessColor(minutesAgo: number): string {
  const clamped = Math.max(0, minutesAgo);
  const last = STOPS[STOPS.length - 1];

  if (clamped >= last.minutes) {
    return toRgbString(last.rgb);
  }

  for (let i = 0; i < STOPS.length - 1; i++) {
    const from = STOPS[i];
    const to = STOPS[i + 1];
    if (clamped >= from.minutes && clamped <= to.minutes) {
      const t = (clamped - from.minutes) / (to.minutes - from.minutes);
      return toRgbString([
        lerp(from.rgb[0], to.rgb[0], t),
        lerp(from.rgb[1], to.rgb[1], t),
        lerp(from.rgb[2], to.rgb[2], t),
      ]);
    }
  }

  return toRgbString(last.rgb);
}
