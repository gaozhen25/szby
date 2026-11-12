import assert from "node:assert/strict";
import test from "node:test";

import {
  CONTENT_GOAL_OPTIONS,
  DURATION_OPTIONS,
  TONE_STYLE_OPTIONS,
  VIDEO_FORMAT_OPTIONS,
  getInitialCreationPreferences,
  getInitialImagePreferences,
  normalizeCreationPreferences,
  normalizeImagePreferences,
  resolveCreationPreferenceVariant,
  updateImagePreference,
} from "./creationPreferences.js";

test("initial preferences choose the first recommended platform configured on the account", () => {
  const preferences = getInitialCreationPreferences(
    { platforms: ["快手", "抖音", "小红书"] },
    { platforms: ["小红书", "抖音"] }
  );

  assert.equal(preferences.targetPlatform, "抖音");
});

test("initial preferences fall back from recommendations to the account platform", () => {
  assert.equal(
    getInitialCreationPreferences(
      { platforms: ["快手"] },
      { platforms: ["视频号", "小红书"], platform: "抖音" }
    ).targetPlatform,
    "视频号"
  );
  assert.equal(
    getInitialCreationPreferences({}, { platform: "抖音" }).targetPlatform,
    "抖音"
  );
  assert.equal(getInitialCreationPreferences({}, {}).targetPlatform, "小红书");
});

test("initial video preferences use the approved defaults", () => {
  assert.deepEqual(getInitialCreationPreferences({}, {}), {
    targetPlatform: "小红书",
    durationSeconds: 60,
    contentGoal: "auto",
    videoFormat: "auto",
    toneStyle: "auto",
    customRequirements: "",
  });
});

test("video preference options match the approved values", () => {
  assert.deepEqual(DURATION_OPTIONS.map(({ value }) => value), [30, 60, 90, 180]);
  assert.deepEqual(CONTENT_GOAL_OPTIONS.map(({ value }) => value), [
    "auto",
    "exposure",
    "acquisition",
    "conversion",
    "persona",
  ]);
  assert.deepEqual(VIDEO_FORMAT_OPTIONS.map(({ value }) => value), [
    "auto",
    "list_talking_head",
    "knowledge_explainer",
    "vlog_workday",
    "story_case",
    "product_service_showcase",
    "interview_dialogue",
  ]);
  assert.deepEqual(TONE_STYLE_OPTIONS.map(({ value }) => value), [
    "auto",
    "professional",
    "conversational",
    "sharp",
    "humorous",
    "empathetic_story",
  ]);
});

test("normalization truncates custom requirements to 500 characters", () => {
  const preferences = normalizeCreationPreferences(
    { customRequirements: "需".repeat(501) },
    {},
    {}
  );

  assert.equal(preferences.customRequirements.length, 500);
  assert.equal(preferences.customRequirements, "需".repeat(500));
});

test("normalization rejects unsupported video option values", () => {
  const preferences = normalizeCreationPreferences(
    {
      targetPlatform: "未配置平台",
      durationSeconds: 45,
      contentGoal: "engagement",
      videoFormat: "cinematic",
      toneStyle: "dramatic",
    },
    { platforms: ["抖音"] },
    { platforms: ["抖音"] }
  );

  assert.deepEqual(preferences, {
    targetPlatform: "抖音",
    durationSeconds: 60,
    contentGoal: "auto",
    videoFormat: "auto",
    toneStyle: "auto",
    customRequirements: "",
  });
});

test("initial image preferences use the approved defaults and recommended platform", () => {
  assert.deepEqual(
    getInitialImagePreferences(
      { platforms: ["抖音", "小红书"] },
      { platforms: ["小红书", "抖音"] }
    ),
    {
      targetPlatform: "抖音",
      imageCount: 1,
      collectionMode: "independent",
      ratio: "9:16",
      creativityLevel: "medium",
      visualStyle: "auto",
      customRequirements: "",
    }
  );
});

test("image preference normalization clamps counts and resets one image to independent", () => {
  assert.deepEqual(
    normalizeImagePreferences(
      {
        targetPlatform: "小红书",
        imageCount: 0,
        collectionMode: "series",
        ratio: "9:16",
        creativityLevel: "high",
        visualStyle: "illustration",
        customRequirements: "奶油色调",
      },
      {},
      { platforms: ["小红书"] }
    ),
    {
      targetPlatform: "小红书",
      imageCount: 1,
      collectionMode: "independent",
      ratio: "9:16",
      creativityLevel: "high",
      visualStyle: "illustration",
      customRequirements: "奶油色调",
    }
  );
  assert.equal(normalizeImagePreferences({ imageCount: 9 }, {}, {}).imageCount, 4);
});

test("reducing image count to one immediately resets series mode", () => {
  assert.deepEqual(
    updateImagePreference(
      { imageCount: 4, collectionMode: "series" },
      "imageCount",
      1
    ),
    { imageCount: 1, collectionMode: "independent" }
  );
});

test("an explicit video variant stays video even when the caller topic has no type", () => {
  assert.equal(resolveCreationPreferenceVariant("video"), "video");
  assert.equal(resolveCreationPreferenceVariant("image"), "image");
  assert.throws(() => resolveCreationPreferenceVariant(""), /创作偏好类型/);
});
