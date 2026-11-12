import assert from "node:assert/strict";
import test from "node:test";

import {
  buildImagePublishMediaCandidates,
  buildGenerationSlots,
  getSelectedVariantAssets,
  mergeImageGroups,
  normalizeImageGroups,
  selectFirstVariants,
} from "./imageVariants.js";

test("buildGenerationSlots creates slots from link reference images", () => {
  assert.deepEqual(
    buildGenerationSlots({
      files: [],
      imagePreviews: [],
      linkReferenceImages: [{ url: "https://cdn.example.test/ref.png" }],
      count: "same",
      fallbackCount: 1,
    }),
    [
      {
        slotId: "link_1",
        sourceType: "link_reference",
        sourceUrl: "https://cdn.example.test/ref.png",
        sourcePrompt: "",
      },
    ],
  );
});

test("buildGenerationSlots creates manual slots when no references exist", () => {
  assert.deepEqual(
    buildGenerationSlots({
      files: [],
      imagePreviews: [],
      linkReferenceImages: [],
      count: "3",
      fallbackCount: 1,
    }).map((slot) => slot.slotId),
    ["manual_1", "manual_2", "manual_3"],
  );
});

test("normalizeImageGroups prefers structured groups and falls back to flat images", () => {
  assert.deepEqual(
    normalizeImageGroups({
      resultPayload: {
        imageGroups: [{ slotId: "slot_1", variants: [{ variantId: "v1", url: "a.png" }] }],
        images: [{ url: "ignored.png" }],
      },
    }),
    [
      {
        slotId: "slot_1",
        sourceType: "manual",
        sourceUrl: "",
        sourcePrompt: "",
        refinement: "",
        variants: [{ variantId: "v1", variantIndex: 0, url: "a.png" }],
      },
    ],
  );

  assert.deepEqual(
    normalizeImageGroups({ resultPayload: { images: [{ url: "a.png" }, { url: "b.png" }] } }).map(
      (group) => group.slotId,
    ),
    ["legacy_1", "legacy_2"],
  );
});

test("mergeImageGroups appends a regenerated candidate and preserves the original", () => {
  const current = [
    { slotId: "slot_1", variants: [{ variantId: "old", url: "old.png" }] },
    { slotId: "slot_2", variants: [{ variantId: "keep", url: "keep.png" }] },
  ];
  const incoming = [{ slotId: "slot_1", variants: [{ variantId: "new", url: "new.png" }] }];

  assert.deepEqual(mergeImageGroups(current, incoming).map((group) => group.variants.map((variant) => variant.variantId)), [["old", "new"], ["keep"]]);
  const merged = mergeImageGroups(current, incoming);
  assert.strictEqual(mergeImageGroups(merged, incoming), merged, "重复轮询不应反复追加或触发状态保存");
});

test("getSelectedVariantAssets returns only selected variants", () => {
  const groups = [
    { slotId: "slot_1", variants: [{ variantId: "a", url: "a.png" }, { variantId: "b", url: "b.png" }] },
    { slotId: "slot_2", variants: [{ variantId: "c", url: "c.png" }] },
  ];

  assert.deepEqual(getSelectedVariantAssets(groups, { slot_1: "b", slot_2: "c" }), [
    { variantId: "b", url: "b.png", slotId: "slot_1" },
    { variantId: "c", url: "c.png", slotId: "slot_2" },
  ]);
});

test("buildImagePublishMediaCandidates reflects regenerated selected variants", () => {
  const groups = [
    {
      slotId: "slot_1",
      variants: [
        { variantId: "old", url: "https://oss.example.test/old.png" },
        { variantId: "regenerated", url: "https://oss.example.test/regenerated.png" },
      ],
    },
  ];

  assert.deepEqual(
    buildImagePublishMediaCandidates(groups, { slot_1: "regenerated" }),
    [{
      url: "https://oss.example.test/regenerated.png",
      kind: "image",
      label: "生成图片 1",
    }],
  );
});

test("selectFirstVariants selects the regenerated result when the old variant disappeared", () => {
  const regeneratedGroups = [
    {
      slotId: "slot_1",
      variants: [{ variantId: "regenerated", url: "https://oss.example.test/regenerated.png" }],
    },
  ];

  assert.deepEqual(
    selectFirstVariants(regeneratedGroups, { slot_1: "old" }),
    { slot_1: "regenerated" },
  );
});
