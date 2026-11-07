// Run from frontend/: node --experimental-strip-types --test lib/freshness.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { delayedAt, expectedPublishAt, freshness, parseUtcTimestamp } from "./freshness.ts";
import { PUBLISH_SCHEDULE } from "./publishSchedule.ts";

const SCHEDULE = { hourUtc: 10, minuteUtc: 0, graceHours: 3 };
const at = (iso) => new Date(iso);

test("the constants match the daily_publish timer and keep a 3-hour grace period", () => {
  const app = readFileSync(new URL("../../functions/scheduled_pipeline/function_app.py", import.meta.url), "utf8");
  const block = app.slice(app.indexOf('name="daily_publish"'));
  const [, second, minute, hour] = block.match(/schedule="(\d+) (\d+) (\d+) \* \* \*"/);
  assert.equal(Number(second), 0);
  assert.equal(Number(minute), PUBLISH_SCHEDULE.minuteUtc);
  assert.equal(Number(hour), PUBLISH_SCHEDULE.hourUtc);
  assert.equal(PUBLISH_SCHEDULE.graceHours, 3);
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

test("expected publish time is yesterday's before 10:00 UTC and today's from 10:00 UTC exactly", () => {
  assert.equal(expectedPublishAt(at("2026-11-07T09:59:59Z"), SCHEDULE).toISOString(), "2026-11-06T10:00:00.000Z");
  assert.equal(expectedPublishAt(at("2026-11-07T10:00:00Z"), SCHEDULE).toISOString(), "2026-11-07T10:00:00.000Z");
  assert.equal(expectedPublishAt(at("2026-11-07T23:59:59Z"), SCHEDULE).toISOString(), "2026-11-07T10:00:00.000Z");
  assert.equal(expectedPublishAt(at("2027-01-01T00:30:00Z"), SCHEDULE).toISOString(), "2026-12-31T10:00:00.000Z");
});

test("before today's publish time the newest posting is compared with yesterday's", () => {
  assert.equal(freshness(at("2026-11-06T10:00:07Z"), at("2026-11-07T08:00:00Z"), SCHEDULE), "live");
  assert.equal(freshness(at("2026-11-05T10:00:07Z"), at("2026-11-07T08:00:00Z"), SCHEDULE), "delayed");
});

test("exact boundaries: publish time, a posting at that instant, and the end of the grace period", () => {
  const yesterday = at("2026-11-06T10:00:07Z");
  assert.equal(freshness(yesterday, at("2026-11-07T10:00:00Z"), SCHEDULE), "live");
  assert.equal(freshness(at("2026-11-07T10:00:00Z"), at("2026-11-07T10:00:00Z"), SCHEDULE), "live");
  assert.equal(freshness(yesterday, at("2026-11-07T12:59:59.999Z"), SCHEDULE), "live");
  assert.equal(freshness(yesterday, at("2026-11-07T13:00:00Z"), SCHEDULE), "delayed");
  assert.equal(freshness(at("2026-11-07T09:59:59.999Z"), at("2026-11-07T13:00:00Z"), SCHEDULE), "delayed");
});

test("inside the grace window, Live needs a posting at or after yesterday's publish time", () => {
  const now = at("2026-11-07T11:00:00Z");
  assert.equal(freshness(at("2026-11-06T10:05:00Z"), now, SCHEDULE), "live");
  assert.equal(freshness(at("2026-11-06T10:00:00Z"), now, SCHEDULE), "live");
  assert.equal(freshness(at("2026-11-06T09:59:59.999Z"), now, SCHEDULE), "delayed");
  assert.equal(freshness(at("2026-11-04T10:05:00Z"), now, SCHEDULE), "delayed");
  assert.equal(freshness(null, now, SCHEDULE), "delayed");
});

test("today's posting keeps the state live for the rest of the day", () => {
  assert.equal(freshness(at("2026-11-07T10:00:07Z"), at("2026-11-07T23:59:59Z"), SCHEDULE), "live");
});

test("a very old, missing or future timestamp", () => {
  const old = at("2020-01-01T00:00:00Z");
  assert.equal(freshness(old, at("2026-11-07T15:00:00Z"), SCHEDULE), "delayed");
  assert.equal(freshness(old, at("2026-11-07T11:00:00Z"), SCHEDULE), "delayed");
  assert.equal(freshness(null, at("2026-11-07T15:00:00Z"), SCHEDULE), "delayed");
  assert.equal(freshness(at("2026-11-08T10:00:00Z"), at("2026-11-07T15:00:00Z"), SCHEDULE), "live");
});

test("delayedAt is the end of the grace period that would pass without a newer posting", () => {
  assert.equal(delayedAt(at("2026-11-06T10:00:07Z"), at("2026-11-07T08:00:00Z"), SCHEDULE).toISOString(), "2026-11-07T13:00:00.000Z");
  assert.equal(delayedAt(at("2026-11-06T10:00:07Z"), at("2026-11-07T11:00:00Z"), SCHEDULE).toISOString(), "2026-11-07T13:00:00.000Z");
  assert.equal(delayedAt(at("2026-11-07T10:00:07Z"), at("2026-11-07T11:00:00Z"), SCHEDULE).toISOString(), "2026-11-08T13:00:00.000Z");
  assert.equal(delayedAt(at("2026-11-05T10:00:07Z"), at("2026-11-07T08:00:00Z"), SCHEDULE), null);
  assert.equal(delayedAt(at("2026-11-06T10:00:00Z"), at("2026-11-07T10:00:00Z"), SCHEDULE).toISOString(), "2026-11-07T13:00:00.000Z");
  assert.equal(delayedAt(at("2026-11-04T10:05:00Z"), at("2026-11-07T11:00:00Z"), SCHEDULE), null);
  assert.equal(delayedAt(null, at("2026-11-07T11:00:00Z"), SCHEDULE), null);
});
