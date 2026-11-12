import { DEFAULT_IMAGE_RATIO } from "./imageAspectRatio.js";

export const SERIES_ROLES_BY_COUNT = Object.freeze({
  2: ["cover", "ending"],
  3: ["cover", "content", "ending"],
  4: ["cover", "content", "content", "ending"],
});

const text = (value) => String(value || "").trim();

export function normalizePromptCards(result = {}) {
  const prompts = Array.isArray(result) ? result : result?.prompts;
  return (Array.isArray(prompts) ? prompts : []).slice(0, 4).map((item, index) => ({
    slotId: text(item?.slotId) || `topic_${index + 1}`,
    role: text(item?.role) || "standalone",
    title: text(item?.title),
    prompt: String(item?.prompt || ""),
  }));
}

export function reindexPromptCards(cards = [], collectionMode = "independent") {
  const safeCards = (Array.isArray(cards) ? cards : []).slice(0, 4).map((card, index) => ({
    ...card,
    slotId: text(card?.slotId) || `topic_${index + 1}`,
  }));
  const nextMode = collectionMode === "series" && safeCards.length > 1
    ? "series"
    : "independent";
  const roles = nextMode === "series" ? SERIES_ROLES_BY_COUNT[safeCards.length] : null;
  return {
    collectionMode: nextMode,
    cards: safeCards.map((card, index) => ({
      ...card,
      role: roles?.[index] || "standalone",
    })),
  };
}

export function buildPromptPlanSlots(cards = []) {
  return (Array.isArray(cards) ? cards : [])
    .map((card, index) => ({
      slotId: text(card?.slotId) || `topic_${index + 1}`,
      sourceType: "manual",
      sourceUrl: "",
      sourcePrompt: text(card?.prompt),
    }))
    .filter((slot) => slot.sourcePrompt);
}

export function buildEditableImagePromptPlan(result = {}, preferences = {}, sourceJobId = "") {
  const requestedMode = result.collectionMode || preferences.collectionMode;
  const cards = normalizePromptCards(result).map((card) => ({
    ...card,
    prompt: requestedMode === "series"
      ? cardOnlyPrompt(card.prompt, result.sharedStyle)
      : card.prompt,
  }));
  const indexed = reindexPromptCards(cards, requestedMode);
  return {
    schemaVersion: Number(result.schemaVersion) || 1,
    sourceJobId: text(sourceJobId),
    imageCount: indexed.cards.length,
    collectionMode: indexed.collectionMode,
    targetPlatform: text(result.targetPlatform || preferences.targetPlatform),
    ratio: text(result.ratio || preferences.ratio) || DEFAULT_IMAGE_RATIO,
    creativityLevel: text(result.creativityLevel || preferences.creativityLevel) || "medium",
    visualStyle: text(result.visualStyle || preferences.visualStyle) || "auto",
    customRequirements: String(preferences.customRequirements || ""),
    sharedStyle: indexed.collectionMode === "series" ? String(result.sharedStyle || "") : "",
    negativePrompt: String(result.negativePrompt || ""),
    publishCopy: String(result.publishCopy || ""),
    hashtags: (Array.isArray(result.hashtags) ? result.hashtags : []).map(text).filter(Boolean),
    cards: indexed.cards,
  };
}

export function shouldApplyImagePromptPlanJob(activeJobId, job, appliedJobIds = new Set()) {
  const jobId = text(job?.id);
  const mode = job?.inputPayload?.mode || job?.input_payload?.mode;
  return Boolean(
    jobId
    && jobId === text(activeJobId)
    && job?.status === "completed"
    && mode === "topic_image_plan"
    && !appliedJobIds?.has(jobId)
  );
}

export function restorePersistedImagePromptPlan(savedPlan) {
  if (!savedPlan || !Array.isArray(savedPlan.cards) || savedPlan.cards.length < 1 || savedPlan.cards.length > 4) {
    return null;
  }
  return {
    ...savedPlan,
    hashtags: Array.isArray(savedPlan.hashtags) ? [...savedPlan.hashtags] : [],
    cards: savedPlan.cards.map((card, index) => ({
      slotId: text(card?.slotId) || `topic_${index + 1}`,
      role: text(card?.role) || "standalone",
      title: String(card?.title || ""),
      prompt: String(card?.prompt || ""),
    })),
  };
}

function cardOnlyPrompt(prompt, sharedStyle = "") {
  let value = text(prompt);
  for (const marker of ["\n本页画面要求：", "\n页面内容："]) {
    const markerIndex = value.indexOf(marker);
    if (markerIndex >= 0) return value.slice(markerIndex + marker.length).trim();
  }
  const exactPrefix = `共享视觉约束：${text(sharedStyle)}`;
  if (text(sharedStyle) && value.startsWith(exactPrefix)) {
    value = value.slice(exactPrefix.length).trim();
  }
  return value
    .replace(/^共享视觉约束：[^\n]*\n?/u, "")
    .replace(/^(?:本页画面要求|页面内容)：/u, "")
    .trim();
}

export function buildPromptPlanGenerationPayload({
  cards = [],
  ratio = DEFAULT_IMAGE_RATIO,
  negativePrompt = "",
  collectionMode = "independent",
  sharedStyle = "",
  sourcePromptWorkflowId = "",
} = {}) {
  if (!Array.isArray(cards) || cards.length < 1 || cards.length > 4) {
    throw new Error("图片计划需要保留 1–4 张图片");
  }
  if (cards.some((card) => !text(card?.prompt))) {
    throw new Error("每张图片都需要填写提示词");
  }
  if (collectionMode === "series" && !text(sharedStyle)) {
    throw new Error("系列图需要填写共享视觉约束");
  }
  const preparedCards = cards.map((card) => ({
    ...card,
    prompt: cardOnlyPrompt(card.prompt, sharedStyle),
  }));
  const slots = buildPromptPlanSlots(preparedCards);
  return {
    prompt: collectionMode === "series"
      ? `共享视觉约束：${text(sharedStyle)}`
      : "仅生成当前卡片描述的一张图片，不得混入其他卡片内容。",
    negativePrompt: String(negativePrompt || ""),
    count: slots.length,
    ratio: text(ratio) || DEFAULT_IMAGE_RATIO,
    slots,
    variantsPerSlot: 2,
    ...(text(sourcePromptWorkflowId) ? { sourcePromptWorkflowId: text(sourcePromptWorkflowId) } : {}),
  };
}
