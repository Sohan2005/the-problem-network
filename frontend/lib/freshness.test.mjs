// Run from frontend/: node --experimental-strip-types --test lib/freshness.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { MAX_TIMEOUT_MS, freshness, msUntilDelayed, parseUtcTimestamp } from "./freshness.ts";
import { LIVE_WINDOW_MS, PUBLISH_SCHEDULE } from "./publishSchedule.ts";

const HOUR = 60 * 60 * 1000;
const MINUTE = 60 * 1000;
const NOW = new Date("2026-11-07T11:00:00Z");
const ago = (ms) => new Date(NOW.getTime() - ms);

test("the constants match the daily_publish timer and keep a 3-hour grace period", () => {
  const app = readFileSync(new URL("../../functions/scheduled_pipeline/function_app.py", import.meta.url), "utf8");
  const block = app.slice(app.indexOf('name="daily_publish"'));
  const [, second, minute, hour] = block.match(/schedule="(\d+) (\d+) (\d+) \* \* \*"/);
  assert.equal(Number(second), 0);
  assert.equal(Number(minute), PUBLISH_SCHEDULE.minuteUtc);
  assert.equal(Number(hour), PUBLISH_SCHEDULE.hourUtc);
  assert.equal(PUBLISH_SCHEDULE.cadenceHours, 24);
  assert.equal(PUBLISH_SCHEDULE.graceHours, 3);
  assert.equal(LIVE_WINDOW_MS, 27 * HOUR);
});

test("timestamps without an offset are UTC; bad values are null", () => {
  assert.equal(parseUtcTimestamp("2026-11-07T10:00:05.123456").toISOString(), "2026-11-07T10:00:05.123Z");
  assert.equal(parseUtcTimestamp("2026-11-07T10:00:05").toISOString(), "2026-11-07T10:00:05.000Z");
  assert.equal(parseUtcTimestamp("2026-11-07T10:00:05Z").toISOString(), "2026-11-07T10:00:05.000Z");
  assert.equal(parseUtcTimestamp("2026-11-07T04:00:05-06:00").toISOString(), "2026-11-07T10:00:05.000Z");
  assert.equal(parseUtcTimestamp("2026-11-07").toISOString(), "2026-11-07T00:00:00.000Z");
  assert.equal(parseUtcTimestamp(null), null);
  assert.equal(parseUtcTimestamp(""), null);
  assert.equal(parseUtcTimestamp("not a date"), null);
});

test("live below 27 hours old, delayed from exactly 27 hours", () => {
  assert.equal(freshness(ago(26 * HOUR + 59 * MINUTE), NOW, LIVE_WINDOW_MS), "live");
  assert.equal(freshness(ago(27 * HOUR - 1), NOW, LIVE_WINDOW_MS), "live");
  assert.equal(freshness(ago(27 * HOUR), NOW, LIVE_WINDOW_MS), "delayed");
  assert.equal(freshness(ago(3 * 24 * HOUR), NOW, LIVE_WINDOW_MS), "delayed");
});

test("a missing or unparsable timestamp is delayed; a future one is live", () => {
  assert.equal(freshness(null, NOW, LIVE_WINDOW_MS), "delayed");
  assert.equal(freshness(parseUtcTimestamp("not a date"), NOW, LIVE_WINDOW_MS), "delayed");
  assert.equal(freshness(ago(-2 * HOUR), NOW, LIVE_WINDOW_MS), "live");
});

test("the timer fires when the newest posting reaches 27 hours old, capped at the setTimeout maximum", () => {
  assert.equal(msUntilDelayed(ago(26 * HOUR + 59 * MINUTE), NOW, LIVE_WINDOW_MS), MINUTE);
  assert.equal(msUntilDelayed(ago(0), NOW, LIVE_WINDOW_MS), 27 * HOUR);
  assert.equal(msUntilDelayed(ago(-2 * HOUR), NOW, LIVE_WINDOW_MS), 29 * HOUR);
  assert.equal(msUntilDelayed(ago(-60 * 24 * HOUR), NOW, LIVE_WINDOW_MS), MAX_TIMEOUT_MS);
  assert.equal(msUntilDelayed(ago(27 * HOUR), NOW, LIVE_WINDOW_MS), null);
  assert.equal(msUntilDelayed(ago(3 * 24 * HOUR), NOW, LIVE_WINDOW_MS), null);
  assert.equal(msUntilDelayed(null, NOW, LIVE_WINDOW_MS), null);
});
