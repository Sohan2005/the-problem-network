// Run from frontend/: node --experimental-strip-types --test lib/sidebar.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { SIDEBAR_STORAGE_KEY, readSidebarCollapsed, writeSidebarCollapsed } from "./sidebar.ts";

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)), values };
}

test("the first visit (nothing stored) starts with the sidebar shown", () => {
  assert.equal(readSidebarCollapsed(() => memoryStorage()), false);
});

test("a stored choice is read back", () => {
  assert.equal(readSidebarCollapsed(() => memoryStorage({ [SIDEBAR_STORAGE_KEY]: "true" })), true);
  assert.equal(readSidebarCollapsed(() => memoryStorage({ [SIDEBAR_STORAGE_KEY]: "false" })), false);
});

test("invalid stored values mean the sidebar is shown", () => {
  for (const value of ["", "1", "yes", "TRUE", " true", "null", "{}"]) {
    assert.equal(readSidebarCollapsed(() => memoryStorage({ [SIDEBAR_STORAGE_KEY]: value })), false, value);
  }
});

test("unavailable storage reads as shown and writing does not throw", () => {
  const throwing = () => { throw new Error("SecurityError"); };
  assert.equal(readSidebarCollapsed(throwing), false);
  assert.doesNotThrow(() => writeSidebarCollapsed(throwing, true));
  const full = { setItem: () => { throw new Error("QuotaExceededError"); } };
  assert.doesNotThrow(() => writeSidebarCollapsed(() => full, true));
});

test("writing stores true or false under the sidebar key and reads back", () => {
  const storage = memoryStorage();
  writeSidebarCollapsed(() => storage, true);
  assert.equal(storage.values.get(SIDEBAR_STORAGE_KEY), "true");
  assert.equal(readSidebarCollapsed(() => storage), true);
  writeSidebarCollapsed(() => storage, false);
  assert.equal(storage.values.get(SIDEBAR_STORAGE_KEY), "false");
  assert.equal(readSidebarCollapsed(() => storage), false);
});
