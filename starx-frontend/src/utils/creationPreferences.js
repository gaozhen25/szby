import { DEFAULT_IMAGE_RATIO } from "./imageAspectRatio.js";

export const DURATION_OPTIONS = [
  { value: 30, label: "30 秒" },
  { value: 60, label: "60 秒" },
  { value: 90, label: "90 秒" },
  { value: 180, label: "180 秒" },
];

export const CONTENT_GOAL_OPTIONS = [
  { value: "auto", label: "自动判断" },
  { value: "exposure", label: "曝光" },
  { value: "acquisition", label: "获客" },
  { value: "conversion", label: "成交" },
  { value: "persona", label: "人设" },
];

export const VIDEO_FORMAT_OPTIONS = [
  { value: "auto", label: "自动推荐" },
  { value: "list_talking_head", label: "清单口播" },
  { value: "knowledge_explainer", label: "知识讲解" },
  { value: "vlog_workday", label: "Vlog / 工作日常" },
  { value: "story_case", label: "故事 / 案例" },
  { value: "product_service_showcase", label: "产品 / 服务展示" },
  { value: "interview_dialogue", label: "访谈 / 对话" },
];

export const TONE_STYLE_OPTIONS = [
  { value: "auto", label: "自动推荐" },
  { value: "professional", label: "专业可信" },
  { value: "conversational", label: "自然口语" },
  { value: "sharp", label: "犀利直接" },
  { value: "humorous", label: "轻松幽默" },
  { value: "empathetic_story", label: "共情叙事" },
];

export const IMAGE_COUNT_OPTIONS = [1, 2, 3, 4].map((value) => ({
  value,
  label: `${value} 张`,
}));

export const IMAGE_RATIO_OPTIONS = ["1:1", "3:4", "9:16", "4:3", "16:9"].map((value) => ({
  value,
  label: value,
}));

export const CREATIVITY_LEVEL_OPTIONS = [
  { value: "low", label: "稳妥写实" },
  { value: "medium", label: "平衡推荐" },
  { value: "high", label: "大胆创意" },
];

export const VISUAL_STYLE_OPTIONS = [
  { value: "auto", label: "自动推荐" },
  { value: "realistic_photography", label: "真实摄影" },
  { value: "commercial_poster", label: "商业海报" },
  { value: "lifestyle_editorial", label: "生活方式杂志" },
  { value: "illustration", label: "插画" },
  { value: "minimal_graphic", label: "极简图形" },
];

const valuesOf = (options) => options.map(({ value }) => value);

const DURATION_VALUES = valuesOf(DURATION_OPTIONS);
const CONTENT_GOAL_VALUES = valuesOf(CONTENT_GOAL_OPTIONS);
const VIDEO_FORMAT_VALUES = valuesOf(VIDEO_FORMAT_OPTIONS);
const TONE_STYLE_VALUES = valuesOf(TONE_STYLE_OPTIONS);
const IMAGE_RATIO_VALUES = valuesOf(IMAGE_RATIO_OPTIONS);
const CREATIVITY_LEVEL_VALUES = valuesOf(CREATIVITY_LEVEL_OPTIONS);
const VISUAL_STYLE_VALUES = valuesOf(VISUAL_STYLE_OPTIONS);

export function resolveCreationPreferenceVariant(variant) {
  if (variant === "video" || variant === "image") return variant;
  throw new Error("必须明确指定创作偏好类型");
}

function getConfiguredPlatforms(account) {
  return account?.platforms?.length ? account.platforms : [account?.platform].filter(Boolean);
}

export function getInitialCreationPreferences(topic, account) {
  const configured = getConfiguredPlatforms(account);
  const targetPlatform = (topic?.platforms || []).find((item) => configured.includes(item)) || configured[0] || "小红书";
  return {
    targetPlatform,
    durationSeconds: 60,
    contentGoal: "auto",
    videoFormat: "auto",
    toneStyle: "auto",
    customRequirements: "",
  };
}

export function normalizeCreationPreferences(preferences, topic, account) {
  const initial = getInitialCreationPreferences(topic, account);
  const configured = getConfiguredPlatforms(account);
  const requestedPlatform = preferences?.targetPlatform;
  const targetPlatform = configured.includes(requestedPlatform) ? requestedPlatform : initial.targetPlatform;
  const durationSeconds = Number(preferences?.durationSeconds);

  return {
    targetPlatform,
    durationSeconds: DURATION_VALUES.includes(durationSeconds) ? durationSeconds : initial.durationSeconds,
    contentGoal: CONTENT_GOAL_VALUES.includes(preferences?.contentGoal) ? preferences.contentGoal : initial.contentGoal,
    videoFormat: VIDEO_FORMAT_VALUES.includes(preferences?.videoFormat) ? preferences.videoFormat : initial.videoFormat,
    toneStyle: TONE_STYLE_VALUES.includes(preferences?.toneStyle) ? preferences.toneStyle : initial.toneStyle,
    customRequirements: String(preferences?.customRequirements || "").slice(0, 500),
  };
}

export function getInitialImagePreferences(topic, account) {
  const { targetPlatform } = getInitialCreationPreferences(topic, account);
  return {
    targetPlatform,
    imageCount: 1,
    collectionMode: "independent",
    ratio: DEFAULT_IMAGE_RATIO,
    creativityLevel: "medium",
    visualStyle: "auto",
    customRequirements: "",
  };
}

export function normalizeImagePreferences(preferences, topic, account) {
  const initial = getInitialImagePreferences(topic, account);
  const configured = getConfiguredPlatforms(account);
  const requestedCount = Math.trunc(Number(preferences?.imageCount));
  const imageCount = Number.isFinite(requestedCount)
    ? Math.min(4, Math.max(1, requestedCount))
    : initial.imageCount;
  const requestedPlatform = preferences?.targetPlatform;
  const targetPlatform = configured.includes(requestedPlatform)
    ? requestedPlatform
    : initial.targetPlatform;
  const collectionMode = imageCount > 1 && preferences?.collectionMode === "series"
    ? "series"
    : "independent";

  return {
    targetPlatform,
    imageCount,
    collectionMode,
    ratio: IMAGE_RATIO_VALUES.includes(preferences?.ratio) ? preferences.ratio : initial.ratio,
    creativityLevel: CREATIVITY_LEVEL_VALUES.includes(preferences?.creativityLevel)
      ? preferences.creativityLevel
      : initial.creativityLevel,
    visualStyle: VISUAL_STYLE_VALUES.includes(preferences?.visualStyle)
      ? preferences.visualStyle
      : initial.visualStyle,
    customRequirements: String(preferences?.customRequirements || "").slice(0, 500),
  };
}

export function updateImagePreference(preferences, key, value) {
  if (key === "imageCount") {
    const imageCount = Number(value);
    return {
      ...preferences,
      imageCount,
      collectionMode: imageCount === 1 ? "independent" : preferences.collectionMode,
    };
  }
  return { ...preferences, [key]: value };
}
