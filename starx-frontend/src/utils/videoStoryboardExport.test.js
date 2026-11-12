import assert from "node:assert/strict";
import test from "node:test";

import { buildVideoStoryboardCsv } from "./videoStoryboardExport.js";

test("exports hook and every storyboard production column as Excel-friendly CSV", () => {
  const csv = buildVideoStoryboardCsv({
    title: "三步写好周报",
    hookSuggestion: "周报写不出来，不是你没做事。",
    finalScript: [{
      shotNumber: 1,
      timeRange: "00:00-00:04",
      shotSizeCamera: "近景 / 平视",
      visual: "人物直视镜头，抛出问题",
      narration: "周报写不出来，不是你没做事。",
      soundNarration: "旁白清晰，开头加入提示音",
      shootingTechnique: "固定机位轻推",
      subtitle: "不是你没做事",
      bgmSound: "轻提示音",
    }],
  });

  assert.ok(csv.startsWith("\uFEFF"));
  assert.match(csv, /"开场钩子","周报写不出来，不是你没做事。"/);
  assert.match(csv, /"镜号","时间","景别 \/ 机位","画面内容","声音 \/ 旁白","拍摄 \/ 运镜","字幕"/);
  assert.match(csv, /"1","00:00-00:04","近景 \/ 平视"/);
});
