import assert from "node:assert/strict";
import test from "node:test";

import { pickInitialLinkReference } from "./extractHistory.js";

test("pickInitialLinkReference prefers extract history bound to the opened workflow task", () => {
  const histories = [
    {
      id: "eh_creation_only",
      creationId: "creation_1",
      taskId: "",
      url: "https://example.test/older",
      title: "同创作未绑定任务",
    },
    {
      id: "eh_bound",
      creationId: "creation_1",
      taskId: "task_1",
      url: "https://example.test/bound",
      title: "绑定任务的解析链接",
    },
  ];

  assert.equal(
    pickInitialLinkReference(histories, { creationId: "creation_1", sourceTaskId: "task_1" })?.id,
    "eh_bound"
  );
});

test("pickInitialLinkReference falls back to creation-linked extract history", () => {
  const histories = [
    {
      id: "eh_other",
      creationId: "creation_2",
      taskId: "task_2",
      url: "https://example.test/other",
    },
    {
      id: "eh_creation",
      creationId: "creation_1",
      taskId: "",
      url: "https://example.test/creation",
    },
  ];

  assert.equal(
    pickInitialLinkReference(histories, { creationId: "creation_1", sourceTaskId: "task_missing" })?.id,
    "eh_creation"
  );
});
