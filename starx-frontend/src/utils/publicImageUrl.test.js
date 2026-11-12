import assert from "node:assert/strict";
import test from "node:test";

import { browserCompatibleImageUrl } from "./publicImageUrl.js";

test("douyin HEIC avatars use the CDN JPEG variant", () => {
  assert.equal(
    browserCompatibleImageUrl(
      "https://p3.douyinpic.com/aweme/avatar/profile.heic?from=profile"
    ),
    "https://p3.douyinpic.com/aweme/avatar/profile.jpeg?from=profile"
  );
});

test("compatible HTTPS images are preserved and unsafe URLs are rejected", () => {
  assert.equal(
    browserCompatibleImageUrl("https://cdn.example.test/avatar.webp"),
    "https://cdn.example.test/avatar.webp"
  );
  assert.equal(browserCompatibleImageUrl("http://cdn.example.test/avatar.jpg"), "");
  assert.equal(browserCompatibleImageUrl("not-a-url"), "");
});

test("xiaohongshu CDN HTTP covers are upgraded without allowing arbitrary HTTP images", () => {
  assert.equal(
    browserCompatibleImageUrl(
      "http://sns-webpic-qc.xhscdn.com/cover!nd_dft_wlteh_webp_3"
    ),
    "https://sns-webpic-qc.xhscdn.com/cover!nd_dft_wlteh_webp_3"
  );
  assert.equal(
    browserCompatibleImageUrl("http://notxhscdn.com/cover.jpg"),
    ""
  );
});
