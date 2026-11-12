import assert from "node:assert/strict";
import test from "node:test";

const mediaPreview = await import("./mediaPreview.js").catch(() => ({}));

test("aweme playback entry gets a per-preview cache key", () => {
  assert.equal(typeof mediaPreview.buildVideoPreviewUrl, "function");
  assert.equal(
    mediaPreview.buildVideoPreviewUrl(
      "https://aweme.snssdk.com/aweme/v1/playwm/?video_id=video-1",
      12345,
    ),
    "https://aweme.snssdk.com/aweme/v1/playwm/?video_id=video-1&starx_preview=12345",
  );
});

test("signed CDN video URLs stay unchanged", () => {
  assert.equal(typeof mediaPreview.buildVideoPreviewUrl, "function");
  const url = "https://v5-ali-northeast.douyinvod.com/video.mp4?signature=abc";
  assert.equal(mediaPreview.buildVideoPreviewUrl(url, 12345), url);
});
