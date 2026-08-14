export function timeAgo(isoTimestamp: string | null | undefined): string {
  if (!isoTimestamp) {
    return 'unknown';
  }

  const then = new Date(isoTimestamp).getTime();
  if (Number.isNaN(then)) {
    return 'unknown';
  }

  const diffMinutes = Math.floor((Date.now() - then) / 60000);
  if (diffMinutes < 1) {
    return 'just now';
  }
  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`;
  }

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) {
    return `${diffHours}h ago`;
  }

  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}
