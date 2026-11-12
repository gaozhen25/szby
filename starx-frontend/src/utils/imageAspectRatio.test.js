import assert from "node:assert/strict";
import test from "node:test";

import {
  closestSupportedImageRatio,
  DEFAULT_IMAGE_RATIO,
  inferImageRatioFromReferences,
} from "./imageAspectRatio.js";

test("image generation defaults to 9:16 without a reference image", async () => {
  assert.equal(DEFAULT_IMAGE_RATIO, "9:16");
  assert.equal(await inferImageRatioFromReferences([]), "9:16");
});

test("reference dimensions select the nearest supported image ratio", async () => {
  assert.equal(await inferImageRatioFromReferences([{ width: 1080, height: 1440 }]), "3:4");
  assert.equal(await inferImageRatioFromReferences([{ width: 1080, height: 1920 }]), "9:16");
  assert.equal(await inferImageRatioFromReferences([{ width: 1920, height: 1080 }]), "16:9");
});

test("unusual reference dimensions use the closest supported ratio", () => {
  assert.equal(closestSupportedImageRatio(1200, 1000), "4:3");
  assert.equal(closestSupportedImageRatio(800, 1200), "3:4");
});
