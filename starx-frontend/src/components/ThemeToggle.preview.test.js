import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const topBarSource = readFileSync(new URL("./TopBar.jsx", import.meta.url), "utf8");
const authSource = readFileSync(new URL("./AuthScreen.jsx", import.meta.url), "utf8");
const appSource = readFileSync(new URL("../App.jsx", import.meta.url), "utf8");
const variablesSource = readFileSync(new URL("../styles/variables.css", import.meta.url), "utf8");
const themeLightSource = readFileSync(new URL("../styles/theme-light.css", import.meta.url), "utf8");
const indexSource = readFileSync(new URL("../../index.html", import.meta.url), "utf8");

test("top bar and auth screen both expose theme toggle", () => {
  assert.match(topBarSource, /ThemeToggle/);
  assert.match(topBarSource, /theme=\{theme\}/);
  assert.match(authSource, /ThemeToggle/);
  assert.match(authSource, /auth-theme-toggle/);
  assert.match(appSource, /useTheme/);
  assert.match(appSource, /theme=\{theme\}/);
});

test("light theme tokens and antiflicker bootstrap exist", () => {
  assert.match(variablesSource, /\[data-theme="light"\]/);
  assert.match(themeLightSource, /\[data-theme="light"\] \.starfield/);
  assert.match(indexSource, /starx_theme/);
  assert.match(indexSource, /dataset\.theme/);
});
