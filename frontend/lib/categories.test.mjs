// Run from frontend/: node --experimental-strip-types --test lib/categories.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { ALL_LABEL, CATEGORIES, EMPTY_CATEGORY_MESSAGE, categoryHref, categoryItems, parseCategory } from "./categories.ts";

test("known slugs are accepted in any case; missing or unknown values mean All", () => {
  assert.equal(parseCategory("developer-tools"), "developer-tools");
  assert.equal(parseCategory(" AI "), "ai");
  for (const value of [null, undefined, "", "web-apps", "all"]) {
    assert.equal(parseCategory(value), null);
  }
});

test("category links set or remove only the category parameter", () => {
  assert.equal(categoryHref("ai"), "/?category=ai");
  assert.equal(categoryHref(null), "/");
  assert.equal(categoryHref("data", "category=ai&ref=share"), "/?category=data&ref=share");
  assert.equal(categoryHref(null, "category=ai&ref=share"), "/?ref=share");
});

test("All comes first with the total, then every category in order", () => {
  const counts = Object.fromEntries(CATEGORIES.map((category, index) => [category.slug, index]));
  const items = categoryItems(counts, null);
  assert.deepEqual(items[0], { slug: null, label: ALL_LABEL, count: 45 });
  assert.deepEqual(items.slice(1).map((item) => item.slug), CATEGORIES.map((category) => category.slug));
  assert.equal(items.find((item) => item.slug === "data").count, 2);
});

test("Other is listed only when it has postings or is selected; missing counts are zero", () => {
  assert.equal(categoryItems({ ai: 3 }, null).some((item) => item.slug === "other"), false);
  assert.equal(categoryItems({ ai: 3, other: 1 }, null).some((item) => item.slug === "other"), true);
  assert.equal(categoryItems({ ai: 3 }, "other").some((item) => item.slug === "other"), true);
  assert.equal(categoryItems({ ai: 3 }, null).find((item) => item.slug === "mobile").count, 0);
});

test("the empty category message matches the design doc", () => {
  assert.equal(EMPTY_CATEGORY_MESSAGE, "No postings in this category yet");
});
