import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const readOptional = (url) => existsSync(url) ? readFileSync(url, "utf8") : "";
const loadingSource = readOptional(new URL("./LoadingOverlay.jsx", import.meta.url));
const wizardSource = readOptional(new URL("./StepWizard.jsx", import.meta.url));
const styles = readFileSync(new URL("../../styles/components.css", import.meta.url), "utf8");

test("loading overlay exposes controlled copy, progress, and timer cleanup", () => {
  assert.notEqual(loadingSource, "");
  assert.match(loadingSource, /statusMessage/);
  assert.match(loadingSource, /loading-spinner-ring/);
  assert.match(loadingSource, /loading-progress-fill/);
  assert.match(loadingSource, /return \(\) => window\.clearInterval\(timer\)/);
  assert.match(styles, /\.loading-overlay\s*\{/);
  assert.match(styles, /\.loading-overlay\.loading-overlay-contained\s*\{[\s\S]*position:\s*fixed[\s\S]*left:\s*max\(14\.15%, 178px\)/);
});

test("loading overlay is a real modal without repeated live announcements", () => {
  assert.match(loadingSource, /useRef/);
  assert.match(loadingSource, /showModal\(\)/);
  assert.match(loadingSource, /<dialog/);
  assert.match(loadingSource, /aria-modal="true"/);
  assert.match(loadingSource, /aria-labelledby="creation-loading-title"/);
  assert.doesNotMatch(loadingSource, /aria-live=/);
  assert.match(loadingSource, /const preventCancel = \(event\) => event\.preventDefault\(\)/);
  assert.match(loadingSource, /addEventListener\("cancel", preventCancel\)/);
  assert.match(loadingSource, /removeEventListener\("cancel", preventCancel\)/);
  assert.match(styles, /\.loading-overlay::backdrop\s*\{/);
  assert.match(styles, /dialog\.loading-overlay:not\(\[open\]\)\s*\{[\s\S]*display:\s*none/);
});

test("step wizard stays controlled by its page", () => {
  assert.notEqual(wizardSource, "");
  assert.match(wizardSource, /steps, currentStep, onStepClick, completedSteps = \[\]/);
  assert.match(wizardSource, /onStepClick\?\.\(index\)/);
  assert.doesNotMatch(wizardSource, /fetch\(|starxApi|setInterval/);
});

test("continuous creation animation respects reduced motion", () => {
  assert.match(styles, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(styles, /\.loading-spinner-ring \.ring/);
  assert.match(styles, /animation:\s*none !important/);
});
