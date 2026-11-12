import assert from "node:assert/strict";
import test from "node:test";

import {
  addUniqueJobId,
  buildCanvasNodes,
  extractJobImages,
  getSelectedFavoriteImages,
} from "./generationCanvas.js";

test("addUniqueJobId appends a missing id and preserves existing ids", () => {
  assert.deepEqual(addUniqueJobId(["job-1"], "job-2"), ["job-1", "job-2"]);
  assert.deepEqual(addUniqueJobId(["job-1"], "job-1"), ["job-1"]);
  assert.deepEqual(addUniqueJobId(["job-1"], ""), ["job-1"]);
});

test("addUniqueJobId returns the same list when id is missing", () => {
  const current = ["job-1"];
  assert.equal(addUniqueJobId(current, null), current);
});

test("extractJobImages supports object and string image payloads", () => {
  assert.deepEqual(
    extractJobImages({
      resultPayload: {
        images: [{ url: "https://cdn.example/a.png" }, "https://cdn.example/b.png", { src: "ignored" }],
      },
    }),
    [
      { url: "https://cdn.example/a.png", meta: { url: "https://cdn.example/a.png" } },
      { url: "https://cdn.example/b.png", meta: {} },
    ],
  );
});

test("buildCanvasNodes keeps requested job order and filters non image jobs", () => {
  const jobs = [
    {
      id: "job-2",
      jobType: "image",
      status: "completed",
      topicTitle: "Topic B",
      prompt: "Prompt B",
      ratio: "1:1",
      requestedCount: 2,
      resultPayload: { images: ["b.png"] },
      createdAt: "2026-06-17T01:00:00Z",
    },
    {
      id: "job-1",
      jobType: "image",
      status: "running",
      topicTitle: "Topic A",
      prompt: "Prompt A",
      ratio: "3:4",
      requestedCount: 4,
      resultPayload: {},
      createdAt: "2026-06-17T00:00:00Z",
    },
    { id: "prompt-1", jobType: "prompt", status: "completed" },
  ];

  assert.deepEqual(
    buildCanvasNodes(jobs, ["job-1", "prompt-1", "job-2"]).map((node) => ({
      id: node.id,
      title: node.title,
      imageCount: node.images.length,
      x: node.x,
      y: node.y,
    })),
    [
      { id: "job-1", title: "Topic A", imageCount: 0, x: 60, y: 44 },
      { id: "job-2", title: "Topic B", imageCount: 1, x: 460, y: 44 },
    ],
  );
});

test("getSelectedFavoriteImages returns favorites matching selected keys", () => {
  const favorites = [
    { key: "a", url: "a.png" },
    { key: "b", url: "b.png" },
  ];

  assert.deepEqual(getSelectedFavoriteImages(favorites, new Set(["b"])), [{ key: "b", url: "b.png" }]);
});
