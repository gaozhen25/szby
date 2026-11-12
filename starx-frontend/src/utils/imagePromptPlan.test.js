import assert from "node:assert/strict";
import test from "node:test";

import {
  buildEditableImagePromptPlan,
  buildPromptPlanGenerationPayload,
  buildPromptPlanSlots,
  normalizePromptCards,
  reindexPromptCards,
  restorePersistedImagePromptPlan,
  shouldApplyImagePromptPlanJob,
} from "./imagePromptPlan.js";

test("normalizePromptCards clones backend cards and assigns stable missing IDs", () => {
  const source = {
    prompts: [
      { slotId: "topic_cover", role: "cover", title: "封面", prompt: "封面提示词" },
      { role: "ending", title: "收尾", prompt: "收尾提示词" },
    ],
  };

  const cards = normalizePromptCards(source);

  assert.deepEqual(cards, [
    { slotId: "topic_cover", role: "cover", title: "封面", prompt: "封面提示词" },
    { slotId: "topic_2", role: "ending", title: "收尾", prompt: "收尾提示词" },
  ]);
  assert.notEqual(cards[0], source.prompts[0]);
});

test("buildPromptPlanSlots creates one manual slot per edited non-empty prompt", () => {
  assert.deepEqual(buildPromptPlanSlots([
    { slotId: "topic_1", prompt: " edited cover " },
    { slotId: "topic_2", prompt: "edited body" },
    { slotId: "topic_3", prompt: "  " },
  ]), [
    { slotId: "topic_1", sourceType: "manual", sourceUrl: "", sourcePrompt: "edited cover" },
    { slotId: "topic_2", sourceType: "manual", sourceUrl: "", sourcePrompt: "edited body" },
  ]);
});

test("reindexPromptCards follows reordered series positions without replacing stable IDs", () => {
  const result = reindexPromptCards([
    { slotId: "topic_3", prompt: "moved first" },
    { slotId: "topic_1", prompt: "moved middle" },
    { slotId: "topic_2", prompt: "moved last" },
  ], "series");

  assert.equal(result.collectionMode, "series");
  assert.deepEqual(result.cards.map(({ slotId, role, prompt }) => ({ slotId, role, prompt })), [
    { slotId: "topic_3", role: "cover", prompt: "moved first" },
    { slotId: "topic_1", role: "content", prompt: "moved middle" },
    { slotId: "topic_2", role: "ending", prompt: "moved last" },
  ]);
});

test("reindexPromptCards switches one remaining card to independent standalone", () => {
  assert.deepEqual(reindexPromptCards([{ slotId: "topic_4", prompt: "keep edit" }], "series"), {
    collectionMode: "independent",
    cards: [{ slotId: "topic_4", prompt: "keep edit", role: "standalone" }],
  });
});

test("completed plan maps all editable fields and preferences without aliasing backend result", () => {
  const result = {
    imageCount: 2,
    collectionMode: "series",
    targetPlatform: "小红书",
    ratio: "3:4",
    creativityLevel: "medium",
    visualStyle: "lifestyle_editorial",
    sharedStyle: "统一人物和奶油色调",
    negativePrompt: "模糊",
    publishCopy: "发布正文",
    hashtags: ["#职场", "#成长"],
    prompts: [
      { slotId: "topic_1", role: "cover", title: "封面", prompt: "封面方向" },
      { slotId: "topic_2", role: "ending", title: "收尾", prompt: "收尾方向" },
    ],
  };

  const plan = buildEditableImagePromptPlan(result, { customRequirements: "不要夸张" }, "job_new");

  assert.deepEqual(plan, {
    schemaVersion: 1,
    sourceJobId: "job_new",
    imageCount: 2,
    collectionMode: "series",
    targetPlatform: "小红书",
    ratio: "3:4",
    creativityLevel: "medium",
    visualStyle: "lifestyle_editorial",
    customRequirements: "不要夸张",
    sharedStyle: "统一人物和奶油色调",
    negativePrompt: "模糊",
    publishCopy: "发布正文",
    hashtags: ["#职场", "#成长"],
    cards: normalizePromptCards(result),
  });
  plan.cards[0].prompt = "用户编辑";
  assert.equal(result.prompts[0].prompt, "封面方向");
});

test("only the active owned completed topic plan job may autofill", () => {
  const completed = { id: "job_active", status: "completed", inputPayload: { mode: "topic_image_plan" } };
  assert.equal(shouldApplyImagePromptPlanJob("job_active", completed, new Set()), true);
  assert.equal(shouldApplyImagePromptPlanJob("job_new", completed, new Set()), false);
  assert.equal(shouldApplyImagePromptPlanJob("job_active", { ...completed, status: "running" }, new Set()), false);
  assert.equal(shouldApplyImagePromptPlanJob("job_active", { ...completed, inputPayload: { mode: "rewrite" } }, new Set()), false);
  assert.equal(shouldApplyImagePromptPlanJob("job_active", completed, new Set(["job_active"])), false);
});

test("generation payload gives every edited card a primary image and one variant", () => {
  assert.deepEqual(buildPromptPlanGenerationPayload({
    cards: [
      { slotId: "topic_1", prompt: "edited cover" },
      { slotId: "topic_2", prompt: "edited ending" },
    ],
    ratio: "9:16",
    negativePrompt: "低质量",
    collectionMode: "series",
    sharedStyle: "同一人物、奶油色调",
    sourcePromptWorkflowId: "wf_prompt_selected_platform",
  }), {
    prompt: "共享视觉约束：同一人物、奶油色调",
    negativePrompt: "低质量",
    count: 2,
    ratio: "9:16",
    slots: [
      { slotId: "topic_1", sourceType: "manual", sourceUrl: "", sourcePrompt: "edited cover" },
      { slotId: "topic_2", sourceType: "manual", sourceUrl: "", sourcePrompt: "edited ending" },
    ],
    variantsPerSlot: 2,
    sourcePromptWorkflowId: "wf_prompt_selected_platform",
  });
});

test("top-level prompt contains no other card and each slot owns exactly one card", () => {
  const payload = buildPromptPlanGenerationPayload({
    cards: [
      { slotId: "a", prompt: "A卡唯一内容" },
      { slotId: "b", prompt: "B卡唯一内容" },
    ],
    collectionMode: "independent",
  });

  assert.doesNotMatch(payload.prompt, /A卡唯一内容|B卡唯一内容/);
  assert.match(payload.slots[0].sourcePrompt, /A卡唯一内容/);
  assert.doesNotMatch(payload.slots[0].sourcePrompt, /B卡唯一内容/);
  assert.match(payload.slots[1].sourcePrompt, /B卡唯一内容/);
  assert.doesNotMatch(payload.slots[1].sourcePrompt, /A卡唯一内容/);
  assert.equal(payload.variantsPerSlot, 2);
});

test("series cards strip the backend shared block before editing and generation", () => {
  const sharedStyle = "统一人物\n奶油色调\n顶部留白";
  const backendPrompt = `共享视觉约束：${sharedStyle}\n本页画面要求：人物拿着产品看镜头`;
  const plan = buildEditableImagePromptPlan({
    collectionMode: "series",
    sharedStyle,
    prompts: [{ slotId: "topic_1", title: "封面", prompt: backendPrompt }],
  }, { collectionMode: "series" }, "wf_prompt");

  assert.equal(plan.cards[0].prompt, "人物拿着产品看镜头");
  const payload = buildPromptPlanGenerationPayload({
    cards: plan.cards,
    collectionMode: "series",
    sharedStyle,
  });
  assert.equal(payload.prompt, `共享视觉约束：${sharedStyle}`);
  assert.equal(payload.slots[0].sourcePrompt, "人物拿着产品看镜头");
});

test("generation payload rejects incomplete current card sets", () => {
  assert.throws(() => buildPromptPlanGenerationPayload({
    cards: [{ slotId: "topic_1", prompt: "ok" }, { slotId: "topic_2", prompt: " " }],
    ratio: "3:4",
  }), /每张图片都需要填写提示词/);
});

test("persisted user edits restore without mutating the saved state", () => {
  const saved = {
    schemaVersion: 1,
    sourceJobId: "job_active",
    collectionMode: "series",
    ratio: "3:4",
    sharedStyle: "edited shared style",
    negativePrompt: "edited negative",
    publishCopy: "edited publish copy",
    hashtags: ["#edited"],
    cards: [
      { slotId: "topic_2", role: "cover", title: "edited title", prompt: "edited prompt" },
      { slotId: "topic_1", role: "ending", title: "edited ending", prompt: "edited ending prompt" },
    ],
  };

  const restored = restorePersistedImagePromptPlan(saved);

  assert.deepEqual(restored.cards, saved.cards);
  restored.cards[0].prompt = "new local edit";
  assert.equal(saved.cards[0].prompt, "edited prompt");
});
