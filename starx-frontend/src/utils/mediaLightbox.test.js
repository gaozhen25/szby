import assert from "node:assert/strict";
import test from "node:test";

import {
  createImageSlide,
  createMediaSlides,
  createVideoSlide,
  guessMediaFilename,
} from "./mediaLightbox.js";

test("createImageSlide and createVideoSlide normalize preview payloads", () => {
  assert.deepEqual(createImageSlide("https://cdn.test/a.png", { title: "封面" }), {
    type: "image",
    src: "https://cdn.test/a.png",
    title: "封面",
    downloadFilename: "a.png",
  });

  const video = createVideoSlide("https://cdn.test/clip.mp4", {
    title: "成片",
    poster: "https://cdn.test/cover.png",
  });
  assert.equal(video.type, "video");
  assert.equal(video.title, "成片");
  assert.equal(video.poster, "https://cdn.test/cover.png");
  assert.deepEqual(video.sources, [{ src: "https://cdn.test/clip.mp4", type: "video/mp4" }]);
});

test("createMediaSlides drops empty entries and keeps mixed media order", () => {
  const slides = createMediaSlides([
    null,
    { url: "https://cdn.test/1.jpg", label: "图1" },
    { type: "video", url: "https://cdn.test/2.webm", title: "视频" },
    { url: "" },
  ]);
  assert.equal(slides.length, 2);
  assert.equal(slides[0].type, "image");
  assert.equal(slides[1].type, "video");
  assert.equal(slides[1].sources[0].type, "video/webm");
});

test("guessMediaFilename falls back when url has no extension leaf", () => {
  assert.equal(guessMediaFilename("https://cdn.test/path/image.png"), "image.png");
  assert.equal(guessMediaFilename("not-a-url", "fallback.bin"), "fallback.bin");
});
