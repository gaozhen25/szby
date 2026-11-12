import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(
  new URL("./DigitalHumanGenerator.jsx", import.meta.url),
  "utf8",
);

test("digital human task detail shows editing and audio quality parameters", () => {
  assert.match(source, /背景音乐 Gain/);
  assert.match(source, /editing\.backgroundMusicUrl/);
  assert.match(source, /editing\.backgroundUrl/);
  assert.match(source, /editing\.bubbleUrl/);
  assert.match(source, /backgroundMusicMeta/);
  assert.match(source, /mediaInfo/);
  assert.match(source, /integratedLoudnessLufs/);
  assert.match(source, /truePeakDbtp/);
  assert.match(source, /video\/mp4/);
  assert.match(source, /\.mp4/);
});

test("supplier raw video opens a preview and has a separate download action", () => {
  assert.match(source, /createVideoSlide\(rawVideoUrl/);
  assert.match(source, /查看供应商原片/);
  assert.match(source, /下载供应商原片/);
  assert.match(source, /downloadMedia\(rawVideoUrl, rawVideoFilename\)/);
  assert.doesNotMatch(
    source,
    /href=\{job\.resultPayload\.rawVideoUrl\}[^>]*>查看供应商原片/,
  );
});

test("generated source audio can be played and downloaded from task detail", () => {
  assert.match(source, /asset\.assetType === "source_audio"/);
  assert.match(source, /<strong>生成音轨<\/strong>/);
  assert.match(source, /<audio src=\{sourceAudioUrl\} controls preload="metadata">/);
  assert.match(source, /downloadMedia\(sourceAudioUrl, sourceAudioFilename\)/);
  assert.match(source, /下载音轨/);
});

test("digital human generation history uses backend pagination metadata", () => {
  assert.match(source, /getDigitalHumanVideoJobs/);
  assert.match(source, /pageSize: HISTORY_PAGE_SIZE/);
  assert.match(source, /creationId: creationId \|\| undefined/);
  assert.match(source, /setHistoryTotal\(Number\(response\?\.total \|\| 0\)\)/);
  assert.match(source, /Math\.ceil\(total \/ HISTORY_PAGE_SIZE\)/);
  assert.doesNotMatch(source, /limit: 100/);
});
