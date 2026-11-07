export interface PublishSchedule {
  hourUtc: number;
  minuteUtc: number;
  graceHours: number;
}

export type Freshness = "live" | "delayed";

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

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

/** The most recent scheduled publish time at or before now: today's once it has passed, otherwise yesterday's. */
export function expectedPublishAt(now: Date, schedule: PublishSchedule): Date {
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), schedule.hourUtc, schedule.minuteUtc);
  return new Date(today <= now.getTime() ? today : today - DAY_MS);
}

/**
 * Live when the newest posting is at or after the most recent expected publish time, or while now is inside the
 * grace period after it (the end of the grace period itself counts as passed). Delayed otherwise, including when
 * there is no timestamp.
 */
export function freshness(lastPublished: Date | null, now: Date, schedule: PublishSchedule): Freshness {
  const expected = expectedPublishAt(now, schedule).getTime();
  if (lastPublished && lastPublished.getTime() >= expected) return "live";
  return now.getTime() < expected + schedule.graceHours * HOUR_MS ? "live" : "delayed";
}

/** When a live state turns delayed if nothing newer is published; null when it is already delayed. */
export function delayedAt(lastPublished: Date | null, now: Date, schedule: PublishSchedule): Date | null {
  if (freshness(lastPublished, now, schedule) === "delayed") return null;
  const expected = expectedPublishAt(now, schedule).getTime();
  const due = lastPublished && lastPublished.getTime() >= expected ? expected + DAY_MS : expected;
  return new Date(due + schedule.graceHours * HOUR_MS);
}
