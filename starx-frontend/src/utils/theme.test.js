import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_THEME, normalizeTheme } from "./theme.js";

test("normalizeTheme falls back to dark for invalid values", () => {
  assert.equal(normalizeTheme("light"), "light");
  assert.equal(normalizeTheme("dark"), "dark");
  assert.equal(normalizeTheme("neon"), DEFAULT_THEME);
  assert.equal(normalizeTheme(""), DEFAULT_THEME);
  assert.equal(normalizeTheme(null), DEFAULT_THEME);
});
