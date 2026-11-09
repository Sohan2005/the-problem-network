// Run from frontend/: node --experimental-strip-types --test lib/importance.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { IMPORTANCE_FILTER_NOTE, IMPORTANCE_LEVELS, IMPORTANCE_TOOLTIP, importanceLabel } from "./importance.ts";

test("filter options match the levels the API stores", () => {
  assert.deepEqual(IMPORTANCE_LEVELS.map((level) => level.value), ["high", "medium", "everyday"]);
});

test("each stored level has a badge label", () => {
  assert.equal(importanceLabel("high"), "High importance");
  assert.equal(importanceLabel("medium"), "Medium importance");
  assert.equal(importanceLabel("everyday"), "Everyday importance");
});

test("unrated or unknown values show no badge", () => {
  for (const value of [null, undefined, "", "High", "critical"]) {
    assert.equal(importanceLabel(value), null);
  }
});

test("the filter note and tooltip say what the rating is", () => {
  assert.equal(IMPORTANCE_FILTER_NOTE, "Filter by real-world importance: how much the problem matters to the people facing it.");
  assert.match(IMPORTANCE_TOOLTIP, /estimate/i);
});
