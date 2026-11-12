import assert from "node:assert/strict";
import test from "node:test";

import {
  buildFieldsFromExtract,
  extractHashTags,
  stripHashTagsFromDescription,
} from "./contentExtraction.js";

test("extractHashTags keeps unique hash-prefixed tags from parsed copy", () => {
  assert.deepEqual(extractHashTags("正文 #热梗 #失败者联盟 #热梗 plain"), ["#热梗", "#失败者联盟"]);
});

test("buildFieldsFromExtract separates parsed description from tags", () => {
  const fields = buildFieldsFromExtract({
    title: "失败者联盟",
    description: "正文内容 #热梗 #失败者联盟",
  });

  assert.equal(fields.title, "失败者联盟");
  assert.equal(fields.body, "正文内容");
  assert.deepEqual(fields.hashtags, ["#热梗", "#失败者联盟"]);
});

test("stripHashTagsFromDescription removes Xiaohongshu topic suffixes", () => {
  assert.equal(
    stripHashTagsFromDescription(
      "先卖你解决方案——这不就是医疗版无限套娃吗？ #医疗美容[话题]# #消费陷阱[话题]# #容貌焦虑[话题]#",
    ),
    "先卖你解决方案——这不就是医疗版无限套娃吗？",
  );
});

test("buildFieldsFromExtract preserves API hashtags while cleaning the description", () => {
  const fields = buildFieldsFromExtract({
    description: "正文 #医疗美容[话题]#",
    hashtags: ["#医疗美容", "#消费陷阱"],
  });

  assert.equal(fields.body, "正文");
  assert.deepEqual(fields.hashtags, ["#医疗美容", "#消费陷阱"]);
});
