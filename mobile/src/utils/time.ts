export function minutesSince(
  isoTimestamp: string | null | undefined,
): number | null {
  if (!isoTimestamp) {
    return null;
  }

  const then = new Date(isoTimestamp).getTime();
  if (Number.isNaN(then)) {
    return null;
  }

  return Math.floor((Date.now() - then) / 60000);
}

export function timeAgo(isoTimestamp: string | null | undefined): string {
  const diffMinutes = minutesSince(isoTimestamp);
  if (diffMinutes === null) {
    return 'unknown';
  }

  if (diffMinutes < 1) {
    return 'just now';
  }
  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`;
  }

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) {
    const remainingMinutes = diffMinutes % 60;
    return remainingMinutes > 0
      ? `${diffHours}h ${remainingMinutes}m ago`
      : `${diffHours}h ago`;
  }

  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}
