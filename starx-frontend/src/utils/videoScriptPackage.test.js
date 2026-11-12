import assert from "node:assert/strict";
import test from "node:test";

import {
  buildPersistedVideoScriptPackage,
  buildVideoScriptDraftFields,
  normalizeVideoShootingSegments,
  resolveActiveVideoScriptJobId,
  resolveCreationTargetPlatform,
  restoreVideoScriptDraft,
  shouldApplyLegacyScriptRewrite,
} from "./videoScriptPackage.js";
import * as videoScriptPackageState from "./videoScriptPackage.js";

test("maps a completed video script package into editable creation fields", () => {
  const fields = buildVideoScriptDraftFields({
    title: "  三步做好复盘  ",
    draftScript: ["开场痛点", "拆解方法", "行动号召"],
    finalScript: [
      { timeRange: "00:00-00:05", narration: "  你不是不努力。  ", visual: "近景" },
      { timeRange: "00:05-00:12", narration: "先对齐目标，再收集反馈。", visual: "清单动画" },
    ],
    publishCopy: "  复盘不是写总结，而是找到下一步。  ",
    hashtags: ["#职场", "#复盘"],
    bgmSuggestion: "  轻快但克制的节奏  ",
  });

  assert.deepEqual(fields, {
    title: "三步做好复盘",
    draftText: "开场痛点\n拆解方法\n行动号召",
    finalText: "你不是不努力。\n先对齐目标，再收集反馈。",
    body: "你不是不努力。\n先对齐目标，再收集反馈。",
    publishCopy: "复盘不是写总结，而是找到下一步。",
    hashtagsText: "#职场 #复盘",
    bgmSuggestion: "轻快但克制的节奏",
  });
});

test("uses empty strings when optional package notes are missing", () => {
  const fields = buildVideoScriptDraftFields({
    finalScript: [{ narration: "保留有效旁白" }],
  });

  assert.equal(fields.publishCopy, "");
  assert.equal(fields.hashtagsText, "");
  assert.equal(fields.bgmSuggestion, "");
  assert.equal(fields.draftText, "");
});

test("keeps final narration in package order and drops blank lines", () => {
  const fields = buildVideoScriptDraftFields({
    finalScript: [
      { timeRange: "00:10-00:20", narration: "第二段先返回" },
      { timeRange: "00:00-00:10", narration: "第一段后返回" },
      { timeRange: "00:20-00:30", narration: "   " },
      null,
    ],
  });

  assert.equal(fields.finalText, "第二段先返回\n第一段后返回");
  assert.equal(fields.body, fields.finalText);
});

test("maps backend finalScript text and gives nonblank narration explicit precedence", () => {
  const fields = buildVideoScriptDraftFields({
    finalScript: [
      { text: "后端标准文本" },
      { narration: "优先旁白", text: "兼容文本" },
      { narration: "   ", text: "空旁白回退文本" },
    ],
  });

  assert.equal(fields.finalText, "后端标准文本\n优先旁白\n空旁白回退文本");
});

test("maps every backend director field for shooting-card display", () => {
  assert.deepEqual(normalizeVideoShootingSegments({
    finalScript: [{
      timeRange: "00:00-00:05", text: "兼容口播", purpose: "建立注意力",
      visual: "人物近景", shotSizeCamera: "近景 / 平视",
      shootingTechnique: "固定机位轻推", subtitle: "别再无效努力",
      bgmSound: "鼓点 + 提示音",
    }],
  }), [{
    shotNumber: 1,
    timeRange: "00:00-00:05", narration: "兼容口播", purpose: "建立注意力",
    soundNarration: "兼容口播；鼓点 + 提示音",
    visual: "人物近景", shotSizeCamera: "近景 / 平视",
    shootingTechnique: "固定机位轻推", subtitle: "别再无效努力",
    bgmSound: "鼓点 + 提示音",
  }]);
});

test("maps analyzed video shotBreakdown when finalScript is absent", () => {
  assert.deepEqual(normalizeVideoShootingSegments({
    shotBreakdown: [{
      shot: 7,
      timeRange: "00:12-00:18",
      script: "展示船票价格。",
      scriptRole: "信息交代",
      visualContent: "手持电子船票特写",
      shotSizeCamera: "近景 / 平视",
      shootingTechnique: "缓慢推镜",
      bgmSound: "轻快拨弦",
    }],
  }), [{
    shotNumber: 7,
    timeRange: "00:12-00:18",
    narration: "展示船票价格。",
    soundNarration: "展示船票价格。；轻快拨弦",
    purpose: "信息交代",
    visual: "手持电子船票特写",
    shotSizeCamera: "近景 / 平视",
    shootingTechnique: "缓慢推镜",
    subtitle: "",
    bgmSound: "轻快拨弦",
  }]);
});

test("late parent job id fills an empty local id but cannot replace a newer local regeneration", () => {
  assert.equal(resolveActiveVideoScriptJobId("", "wf_late"), "wf_late");
  assert.equal(resolveActiveVideoScriptJobId("wf_local", "wf_late"), "wf_local");
  assert.equal(resolveActiveVideoScriptJobId("wf_local", ""), "wf_local");

  let activeJobId = resolveActiveVideoScriptJobId("", "wf_autostart_a");
  activeJobId = "wf_regeneration_b";
  activeJobId = resolveActiveVideoScriptJobId(activeJobId, "wf_autostart_a");
  assert.equal(activeJobId, "wf_regeneration_b");
});

test("canonical autostart updater keeps the newer regeneration active across remount", () => {
  assert.equal(typeof videoScriptPackageState.applyAutostartVideoScriptJobResult, "function");

  const creationId = "creation_video_1";
  const autostartA = {
    creationId,
    jobId: "wf_autostart_a",
    preferences: {
      targetPlatform: "小红书",
      durationSeconds: 60,
      contentGoal: "auto",
      videoFormat: "auto",
      toneStyle: "auto",
      customRequirements: "A preferences",
    },
  };
  let canonicalCreation = { creationId, creationState: {} };

  const autostartOwnedCreation = videoScriptPackageState.applyAutostartVideoScriptJobResult(
    canonicalCreation,
    autostartA
  );
  assert.equal(autostartOwnedCreation.creationState.activeVideoScriptJobId, "wf_autostart_a");
  assert.equal(autostartOwnedCreation.creationState.videoScriptCustomRequirements, "A preferences");

  // A starts, then the user starts B before A's request returns.
  canonicalCreation = {
    ...canonicalCreation,
    creationState: {
      ...canonicalCreation.creationState,
      activeVideoScriptJobId: "wf_regeneration_b",
      videoScriptCustomRequirements: "B preferences",
    },
  };
  canonicalCreation = videoScriptPackageState.applyAutostartVideoScriptJobResult(
    canonicalCreation,
    autostartA
  );

  // A remount restores exclusively from the canonical creation state.
  const remountedActiveJobId = canonicalCreation.creationState.activeVideoScriptJobId;
  assert.equal(remountedActiveJobId, "wf_regeneration_b");
  assert.equal(canonicalCreation.creationState.videoScriptCustomRequirements, "B preferences");
});

test("three consecutive active-job refresh failures become a bounded visible tracking error", () => {
  assert.equal(typeof videoScriptPackageState.advanceVideoScriptRefreshFailure, "function");
  const first = videoScriptPackageState.advanceVideoScriptRefreshFailure(0, new Error("forbidden"), 3);
  const second = videoScriptPackageState.advanceVideoScriptRefreshFailure(first.count, new Error("forbidden"), 3);
  const third = videoScriptPackageState.advanceVideoScriptRefreshFailure(second.count, new Error("forbidden"), 3);

  assert.deepEqual(first, { count: 1, blocked: false, message: "forbidden" });
  assert.deepEqual(second, { count: 2, blocked: false, message: "forbidden" });
  assert.deepEqual(third, { count: 3, blocked: true, message: "forbidden" });
});

test("legacy rewrite only applies to video when the legacy flow is explicitly active", () => {
  assert.equal(shouldApplyLegacyScriptRewrite({
    creationType: "video",
    activeVideoScriptJobId: "wf_package",
    trackedScriptRewriteJobId: "wf_legacy",
    completedJobId: "wf_legacy",
  }), false);
  assert.equal(shouldApplyLegacyScriptRewrite({
    creationType: "video",
    activeVideoScriptJobId: "",
    trackedScriptRewriteJobId: "wf_legacy",
    completedJobId: "wf_legacy",
    legacyVideoFlowActive: false,
  }), false);
  assert.equal(shouldApplyLegacyScriptRewrite({
    creationType: "video",
    activeVideoScriptJobId: "",
    trackedScriptRewriteJobId: "wf_legacy",
    completedJobId: "wf_legacy",
    legacyVideoFlowActive: true,
  }), true);
  assert.equal(shouldApplyLegacyScriptRewrite({
    creationType: "video",
    activeVideoScriptJobId: "",
    trackedScriptRewriteJobId: "wf_other",
    completedJobId: "wf_legacy",
  }), false);
});

test("confirmed video platform overrides the creation platform only in video mode", () => {
  assert.equal(resolveCreationTargetPlatform("video", "小红书", "抖音"), "抖音");
  assert.equal(resolveCreationTargetPlatform("image", "小红书", "抖音"), "小红书");
  assert.equal(resolveCreationTargetPlatform("video", "小红书", ""), "小红书");
});

test("persists and restores every editable field before the first successful package", () => {
  const persisted = buildPersistedVideoScriptPackage(null, {
    title: "用户编辑标题",
    draftText: "",
    finalText: "优化稿",
    body: "正文",
    publishCopy: "发布文案",
    hashtagsText: "#一个 #两个",
    bgmSuggestion: "轻音乐",
  });

  assert.deepEqual(persisted, {
    editableTitle: "用户编辑标题",
    editableDraftText: "",
    editableFinalText: "优化稿",
    editableBody: "正文",
    editablePublishCopy: "发布文案",
    editableHashtagsText: "#一个 #两个",
    editableBgmSuggestion: "轻音乐",
  });

  assert.deepEqual(restoreVideoScriptDraft({
    packageResult: persisted,
    content: {
      title: "旧标题",
      scriptOriginal: ["旧初稿"],
      scriptRewritten: ["旧优化稿"],
      body: "旧正文",
      hashtags: ["#旧标签"],
      bgmSuggestion: "旧音乐",
    },
    videoPublishText: "旧发布文案",
    topicTitle: "选题标题",
  }), {
    title: "用户编辑标题",
    draftText: "",
    finalText: "优化稿",
    body: "正文",
    publishCopy: "发布文案",
    hashtagsText: "#一个 #两个",
    bgmSuggestion: "轻音乐",
  });
});

test("restore precedence is editable state, then saved content, then generated package", () => {
  const restored = restoreVideoScriptDraft({
    packageResult: {
      title: "生成标题",
      draftScript: ["生成初稿"],
      finalScript: [{ text: "生成终稿" }],
      publishCopy: "生成发布文案",
      hashtags: ["#生成"],
      bgmSuggestion: "生成音乐",
    },
    content: {
      title: "内容标题",
      scriptOriginal: ["内容初稿"],
      scriptRewritten: ["内容终稿"],
      body: "内容正文",
      hashtags: ["#内容"],
      bgmSuggestion: "内容音乐",
    },
    videoPublishText: "内容发布文案",
    topicTitle: "选题标题",
  });

  assert.deepEqual(restored, {
    title: "内容标题",
    draftText: "内容初稿",
    finalText: "内容终稿",
    body: "内容正文",
    publishCopy: "内容发布文案",
    hashtagsText: "#内容",
    bgmSuggestion: "内容音乐",
  });
});
