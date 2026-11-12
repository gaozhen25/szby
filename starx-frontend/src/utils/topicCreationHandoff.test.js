import assert from "node:assert/strict";
import test from "node:test";

import {
  applyImagePromptStartFailure,
  applyImagePromptJobResult,
  canRetryImagePromptPlan,
  requireImagePromptJobId,
  resolveActiveImagePromptJobId,
  submitTopicCreation,
  startImageTopicPromptPlan,
} from "./topicCreationHandoff.js";

const preferences = {
  targetPlatform: "小红书",
  imageCount: 3,
  collectionMode: "series",
  ratio: "3:4",
  creativityLevel: "medium",
  visualStyle: "lifestyle_editorial",
  customRequirements: "同一人物，奶油色调",
};

test("image topic handoff starts only the structured prompt-plan job", async () => {
  const calls = [];
  const api = {
    createTopicPromptJob: async (accountId, payload) => {
      calls.push({ type: "prompt", accountId, payload });
      return { id: "wf_image_plan" };
    },
    createImageJob: async () => calls.push({ type: "image" }),
  };

  const job = await startImageTopicPromptPlan({
    api,
    accountId: "acc_1",
    topicId: "topic_1",
    preferences,
  });

  assert.deepEqual(job, { id: "wf_image_plan" });
  assert.deepEqual(calls, [{
    type: "prompt",
    accountId: "acc_1",
    payload: { topicId: "topic_1", ...preferences },
  }]);
});

test("image topic handoff forwards parsed hot-note originals for prompt reversal", async () => {
  const calls = [];
  const referenceUrls = ["https://cdn.example.test/hot-cover.jpg"];
  await startImageTopicPromptPlan({
    api: {
      createTopicPromptJob: async (accountId, payload) => {
        calls.push({ accountId, payload });
        return { id: "wf_reference_plan" };
      },
    },
    accountId: "acc_1",
    topicId: "topic_1",
    preferences,
    referenceUrls,
  });

  assert.deepEqual(calls[0].payload, {
    topicId: "topic_1",
    ...preferences,
    referenceUrls,
  });
});

test("image topic handoff rejects an abnormal response without a job id", async () => {
  await assert.rejects(
    startImageTopicPromptPlan({
      api: { createTopicPromptJob: async () => ({ status: "pending" }) },
      accountId: "acc_1",
      topicId: "topic_1",
      preferences,
    }),
    /未返回任务 ID/
  );
  assert.throws(() => requireImagePromptJobId(null), /未返回任务 ID/);
});

test("image prompt handoff stores preferences and both prompt job aliases for its creation", () => {
  const creation = {
    creationId: "creation_1",
    creationState: { retained: true },
  };

  assert.deepEqual(
    applyImagePromptJobResult(creation, {
      creationId: "creation_1",
      jobId: "wf_image_plan",
      preferences,
    }),
    {
      creationId: "creation_1",
      creationState: {
        retained: true,
        imagePromptJobId: "wf_image_plan",
        promptJobId: "wf_image_plan",
        imageCreationPreferences: preferences,
        imagePromptPlan: null,
      },
    }
  );
});

test("late image prompt jobs cannot overwrite a different active creation", () => {
  const creation = { creationId: "creation_2", creationState: {} };
  assert.equal(
    applyImagePromptJobResult(creation, {
      creationId: "creation_1",
      jobId: "wf_old",
      preferences,
    }),
    creation
  );
});

test("late autostart image prompt cannot replace a newer prompt owned by the same creation", () => {
  const creation = {
    creationId: "creation_1",
    creationState: { promptJobId: "wf_newer" },
  };
  assert.equal(
    applyImagePromptJobResult(creation, {
      creationId: "creation_1",
      jobId: "wf_late_autostart",
      preferences,
    }),
    creation
  );
});

test("late canonical image prompt id is adopted only while local ownership is empty", () => {
  assert.equal(resolveActiveImagePromptJobId("", "wf_late"), "wf_late");
  assert.equal(resolveActiveImagePromptJobId("wf_newer", "wf_late"), "wf_newer");
  assert.equal(resolveActiveImagePromptJobId("wf_newer", ""), "wf_newer");
});

test("topic creation orchestration closes preferences only after skeleton success", async () => {
  const events = [];
  const result = await submitTopicCreation({
    topic: { id: "topic_1" },
    preferences,
    generateCreation: async (...args) => events.push(["generate", ...args]),
    onSuccess: () => events.push(["close"]),
    onFailure: () => events.push(["failure"]),
  });

  assert.equal(result.ok, true);
  assert.deepEqual(events, [
    ["generate", "topic_1", "小红书", preferences],
    ["close"],
  ]);
});

test("topic creation orchestration catches skeleton failure and retains retry preferences", async () => {
  const failure = new Error("骨架创建失败");
  const events = [];
  const result = await submitTopicCreation({
    topic: { id: "topic_1" },
    preferences,
    generateCreation: async () => { throw failure; },
    onSuccess: () => events.push(["close"]),
    onFailure: (error, retainedPreferences) => events.push(["failure", error, retainedPreferences]),
  });

  assert.deepEqual(result, { ok: false, error: failure });
  assert.deepEqual(events, [["failure", failure, preferences]]);
});

test("a prompt-plan POST failure without a job id remains retryable without clearing edits", () => {
  const creation = {
    creationId: "creation_image_1",
    topicId: "topic_1",
    creationState: {
      imageCreationPreferences: { targetPlatform: "抖音", imageCount: 2 },
      imagePromptPlan: { cards: [{ prompt: "用户已编辑" }] },
    },
  };
  const failed = applyImagePromptStartFailure(creation, {
    creationId: creation.creationId,
    error: new Error("network down"),
  });

  assert.equal(failed.creationState.imagePromptPlanStartError, "network down");
  assert.equal(failed.creationState.imagePromptPlan.cards[0].prompt, "用户已编辑");
  assert.equal(canRetryImagePromptPlan({
    topicId: failed.topicId,
    preferences: failed.creationState.imageCreationPreferences,
    startError: failed.creationState.imagePromptPlanStartError,
  }), true);
});

test("prompt-plan retry is blocked while a replacement request is submitting", () => {
  assert.equal(canRetryImagePromptPlan({
    topicId: "topic_1",
    preferences: { imageCount: 2 },
    startError: "failed",
    isRetrying: true,
  }), false);
});
