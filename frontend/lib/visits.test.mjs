// Run from frontend/: node --experimental-strip-types --test lib/visits.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { VISIT_FLAG, recordVisitOnce, visitCountLabel } from "./visits.ts";

function memoryStorage() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)), values };
}

test("a visit is sent once per session, however many pages load", () => {
  const storage = memoryStorage();
  let sent = 0;
  const env = { getStorage: () => storage };
  const results = [1, 2, 3].map(() => recordVisitOnce(env, () => sent++));
  assert.deepEqual(results, [true, false, false]);
  assert.equal(sent, 1);
  assert.equal(storage.values.get(VISIT_FLAG), "1");
});

test("a new session (empty sessionStorage) counts again", () => {
  let sent = 0;
  recordVisitOnce({ getStorage: memoryStorage }, () => sent++);
  recordVisitOnce({ getStorage: memoryStorage }, () => sent++);
  assert.equal(sent, 2);
});

test("automated browsers and unavailable storage are not counted", () => {
  let sent = 0;
  assert.equal(recordVisitOnce({ getStorage: memoryStorage, webdriver: true }, () => sent++), false);
  const throwing = () => { throw new Error("SecurityError"); };
  assert.equal(recordVisitOnce({ getStorage: throwing }, () => sent++), false);
  const blocked = { getItem: () => null, setItem: () => { throw new Error("QuotaExceededError"); } };
  assert.equal(recordVisitOnce({ getStorage: () => blocked }, () => sent++), false);
  assert.equal(sent, 0);
});

test("the counter is hidden on failure, while loading and with no visits", () => {
  assert.equal(visitCountLabel({ isError: true, data: undefined }), null);
  assert.equal(visitCountLabel({ isError: true, data: { total: 5 } }), null);
  assert.equal(visitCountLabel({ isError: false, data: undefined }), null);
  assert.equal(visitCountLabel({ isError: false, data: { total: 0 } }), null);
  assert.equal(visitCountLabel({ isError: false, data: { total: Number.NaN } }), null);
  assert.equal(visitCountLabel({ isError: false, data: {} }), null);
});

test("the counter text", () => {
  assert.equal(visitCountLabel({ isError: false, data: { total: 1 } }), "1 visit");
  assert.equal(visitCountLabel({ isError: false, data: { total: 12345 } }), "12,345 visits");
});
