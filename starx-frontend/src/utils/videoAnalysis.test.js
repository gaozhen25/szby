import assert from "node:assert/strict";
import test from "node:test";

import {
  buildVideoAnalysisDraftFields,
  buildVideoScriptPackageFromAnalysis,
} from "./videoAnalysis.js";
import { normalizeVideoShootingSegments } from "./videoScriptPackage.js";

test("maps analyzed source-video shots into the standard storyboard package", () => {
  const packageResult = buildVideoScriptPackageFromAnalysis({
    videoScript: [
      { timeRange: "00:00-00:03", text: "别再这样拍产品了。" },
      { timeRange: "00:03-00:08", text: "先给用户一个真实使用场景。" },
    ],
    shotBreakdown: [{
      shot: 1,
      image: "手拿产品入镜",
      timeRange: "00:00-00:03",
      script: "别再这样拍产品了。",
      scriptRole: "三秒钩子",
      visualContent: "产品从画面右侧推入，背景保持干净",
      shotSizeCamera: "近景 / 平视",
      shootingTechnique: "手持轻推",
      bgmSound: "轻快鼓点",
    }],
    publishCopy: "原片拆解完成。",
    replicationPrompt: "开头先反常识，再给动作建议。",
  }, {
    title: "爆款原片拆解",
    hashtags: ["产品", "#短视频"],
  });

  assert.equal(packageResult.sourceType, "video_analysis");
  assert.equal(packageResult.title, "爆款原片拆解");
  assert.deepEqual(packageResult.draftScript, [
    "[00:00-00:03] 别再这样拍产品了。",
    "[00:03-00:08] 先给用户一个真实使用场景。",
  ]);
  assert.deepEqual(packageResult.hashtags, ["#产品", "#短视频"]);

  const segments = normalizeVideoShootingSegments(packageResult);
  assert.equal(segments.length, 1);
  assert.equal(segments[0].narration, "别再这样拍产品了。");
  assert.equal(segments[0].visual, "产品从画面右侧推入，背景保持干净");
  assert.equal(segments[0].shotSizeCamera, "近景 / 平视");
  assert.equal(segments[0].shootingTechnique, "手持轻推");
  assert.equal(segments[0].bgmSound, "轻快鼓点");
});

test("keeps draft fields compatible with analyzed source-video package", () => {
  const result = {
    videoScript: [{ timeRange: "00:00-00:02", text: "开场台词" }],
    shotBreakdown: [{ shot: 1, timeRange: "00:00-00:02", script: "开场台词", visualContent: "人物近景" }],
    rewriteReferences: [{ script: ["仿写结构"] }],
    replicationPrompt: "复刻节奏",
    publishCopy: "发布文案",
  };

  const fields = buildVideoAnalysisDraftFields(result);
  const packageResult = buildVideoScriptPackageFromAnalysis(result);

  assert.equal(fields.scriptOriginalText, "镜头1 00:00-00:02 开场台词");
  assert.equal(fields.scriptRewrittenText, "仿写结构\n\n复刻节奏");
  assert.equal(packageResult.finalScript[0].narration, "开场台词");
});
