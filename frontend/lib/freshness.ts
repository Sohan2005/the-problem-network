export type Freshness = "live" | "delayed";

// Larger setTimeout delays overflow and fire immediately.
export const MAX_TIMEOUT_MS = 2 ** 31 - 1;

/**
 * A stats timestamp as a Date. briefs.created_at is naive UTC, so a value without an offset is read as UTC.
 * Null when missing or unparsable.
 */
export function parseUtcTimestamp(value: string | null | undefined): Date | null {
  if (!value) return null;
  let text = value.trim().replace(/(\.\d{3})\d+/, "$1");
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += "T00:00:00";
  if (!/(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(text)) text += "Z";
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Live while the newest posting is younger than the live window (a future timestamp counts as live); delayed from
 * the exact end of the window on, and when there is no timestamp.
 */
export function freshness(lastPublished: Date | null, now: Date, liveWindowMs: number): Freshness {
  if (!lastPublished) return "delayed";
  return now.getTime() - lastPublished.getTime() < liveWindowMs ? "live" : "delayed";
}

/** Milliseconds until a live state turns delayed, capped at MAX_TIMEOUT_MS; null when it is already delayed. */
export function msUntilDelayed(lastPublished: Date | null, now: Date, liveWindowMs: number): number | null {
  if (freshness(lastPublished, now, liveWindowMs) === "delayed") return null;
  return Math.min(lastPublished!.getTime() + liveWindowMs - now.getTime(), MAX_TIMEOUT_MS);
}
