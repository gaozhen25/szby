import assert from "node:assert/strict";
import test from "node:test";

import {
  WORKFLOW_STAGES,
  canPublishWorkflowTask,
  getNextWorkflowStatus,
  getPreviousWorkflowStatus,
  matchesWorkflowTask,
  normalizeWorkflowStatus,
} from "./workflowProcess.js";

test("workflow keeps all seven develop stages including shooting", () => {
  assert.deepEqual(WORKFLOW_STAGES.map((stage) => stage.key), [
    "draft",
    "script",
    "shooting",
    "editing",
    "review",
    "pending_review",
    "done",
  ]);
});

test("workflow normalizes legacy status aliases without inventing unknown stages", () => {
  assert.equal(normalizeWorkflowStatus("pending"), "pending_review");
  assert.equal(normalizeWorkflowStatus("pending_publish"), "pending_review");
  assert.equal(normalizeWorkflowStatus("completed"), "done");
  assert.equal(normalizeWorkflowStatus("shooting"), "shooting");
  assert.equal(normalizeWorkflowStatus("unknown"), "unknown");
  assert.equal(getNextWorkflowStatus("unknown"), null);
});

test("workflow advances through shooting before editing", () => {
  assert.equal(getNextWorkflowStatus("script"), "shooting");
  assert.equal(getNextWorkflowStatus("shooting"), "editing");
  assert.equal(getNextWorkflowStatus("done"), null);
  assert.equal(getPreviousWorkflowStatus("editing"), "shooting");
  assert.equal(getPreviousWorkflowStatus("draft"), null);
  assert.equal(getPreviousWorkflowStatus("unknown"), null);
});

test("workflow publishing is available only for linked pending-review tasks", () => {
  assert.equal(canPublishWorkflowTask(null), false);
  assert.equal(canPublishWorkflowTask({ status: "pending_review", creationId: "creation-1" }), true);
  assert.equal(canPublishWorkflowTask({ status: "pending", creationId: "creation-1" }), false);
  assert.equal(canPublishWorkflowTask({ status: "pending_publish", creationId: "creation-1" }), false);
  assert.equal(canPublishWorkflowTask({ status: "review", creationId: "creation-1" }), false);
  assert.equal(canPublishWorkflowTask({ status: "pending_review", creationId: "" }), false);
});

test("workflow task filtering uses real keyword, assignee, stage, and platform fields", () => {
  const task = {
    title: "夏日咖啡探店",
    body: "城市散步",
    assignee: "小美",
    status: "shooting",
    targetPlatform: "抖音",
  };

  assert.equal(matchesWorkflowTask(task, {
    keyword: "咖啡",
    assignee: "小美",
    stage: "shooting",
    platform: "抖音",
  }), true);
  assert.equal(matchesWorkflowTask(task, { keyword: "露营" }), false);
  assert.equal(matchesWorkflowTask(task, { assignee: "小李" }), false);
  assert.equal(matchesWorkflowTask(task, { stage: "editing" }), false);
});
