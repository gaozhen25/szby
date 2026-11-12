import assert from "node:assert/strict";
import test from "node:test";

import {
  activeCompetitorWorkflowIds,
  createCompetitorRequestGate,
  createCompetitorWorkflowPolling,
  isCurrentCompetitorAccount,
  markCompetitorTargetsRefreshing,
} from "./useCompetitorMonitoring.js";


function createFakeScheduler() {
  const tasks = new Map();
  let nextId = 1;
  return {
    setTimeout(callback) {
      const id = nextId++;
      tasks.set(id, callback);
      return id;
    },
    clearTimeout(id) {
      tasks.delete(id);
    },
    get size() {
      return tasks.size;
    },
    async runNext() {
      const [id, callback] = tasks.entries().next().value || [];
      if (!id) return;
      tasks.delete(id);
      await callback();
    },
  };
}


test("request gate rejects stale responses after an account switch", () => {
  const gate = createCompetitorRequestGate();
  const first = gate.begin("acc1");
  const second = gate.begin("acc2");

  assert.equal(gate.accept(first, "acc1"), false);
  assert.equal(gate.accept(second, "acc2"), true);

  gate.invalidate();
  assert.equal(gate.accept(second, "acc2"), false);
});


test("action responses are accepted only for the account that started them", () => {
  assert.equal(isCurrentCompetitorAccount("acc1", "acc1"), true);
  assert.equal(isCurrentCompetitorAccount("acc1", "acc2"), false);
  assert.equal(isCurrentCompetitorAccount("", ""), false);
});

test("persisted active account workflows are reattached after entering the page", () => {
  assert.deepEqual(
    activeCompetitorWorkflowIds([
      { id: "one", refreshStatus: "pending", activeWorkflowId: "wf_1" },
      { id: "two", refreshStatus: "running", activeWorkflowId: "wf_2" },
      { id: "three", refreshStatus: "succeeded", activeWorkflowId: "wf_old" },
      { id: "four", refreshStatus: "pending", activeWorkflowId: "wf_1" },
      { id: "five", refreshStatus: "running", activeWorkflowId: null },
    ]),
    ["wf_1", "wf_2"]
  );
});


test("refresh submission immediately marks only submitted targets pending", () => {
  assert.deepEqual(
    markCompetitorTargetsRefreshing(
      [{ id: "one", refreshStatus: "succeeded" }, { id: "two", refreshStatus: "failed" }],
      [{ id: "wf_1", inputPayload: { targetId: "one" } }]
    ),
    [
      { id: "one", refreshStatus: "pending", activeWorkflowId: "wf_1" },
      { id: "two", refreshStatus: "failed" },
    ]
  );
});


test("workflow polling stops at terminal state and reloads once", async () => {
  const scheduler = createFakeScheduler();
  const statuses = ["running", "completed"];
  const reloads = [];
  const polling = createCompetitorWorkflowPolling({
    api: {
      getCompetitorRefreshWorkflow: async () => ({ status: statuses.shift() }),
    },
    scheduler,
    onTerminal: (accountId) => reloads.push(accountId),
    onError: () => assert.fail("polling should not fail"),
    intervalMs: 1,
  });

  polling.track("acc1", ["wf_1"]);
  assert.equal(scheduler.size, 1);
  await scheduler.runNext();
  assert.equal(scheduler.size, 1);
  await scheduler.runNext();

  assert.deepEqual(reloads, ["acc1"]);
  assert.equal(scheduler.size, 0);
});


test("workflow polling publishes running updates before terminal reload", async () => {
  const scheduler = createFakeScheduler();
  const statuses = ["running", "completed"];
  const updates = [];
  const polling = createCompetitorWorkflowPolling({
    api: {
      getCompetitorRefreshWorkflow: async () => ({ status: statuses.shift() }),
    },
    scheduler,
    onUpdate: (accountId, workflows) => {
      updates.push([accountId, workflows[0].status]);
    },
    onTerminal: () => {},
    onError: () => assert.fail("polling should not fail"),
    intervalMs: 1,
  });

  polling.track("acc1", ["wf_1"]);
  await scheduler.runNext();
  await scheduler.runNext();

  assert.deepEqual(updates, [
    ["acc1", "running"],
    ["acc1", "completed"],
  ]);
});


test("workflow polling merges concurrent refresh operations for one account", async () => {
  const scheduler = createFakeScheduler();
  const calls = [];
  let secondStatus = "running";
  const reloads = [];
  const polling = createCompetitorWorkflowPolling({
    api: {
      getCompetitorRefreshWorkflow: async (_accountId, workflowId) => {
        calls.push(workflowId);
        if (workflowId === "wf_1") return { id: workflowId, status: "completed" };
        const status = secondStatus;
        secondStatus = "completed";
        return { id: workflowId, status };
      },
    },
    scheduler,
    onTerminal: (accountId, workflows) => reloads.push([accountId, workflows.map((item) => item.id)]),
    onError: () => assert.fail("polling should not fail"),
    intervalMs: 1,
  });

  polling.track("acc1", ["wf_1"]);
  polling.track("acc1", ["wf_2"]);
  assert.equal(scheduler.size, 1);
  await scheduler.runNext();
  assert.equal(scheduler.size, 1);
  await scheduler.runNext();

  assert.deepEqual(calls, ["wf_1", "wf_2", "wf_2"]);
  assert.deepEqual(reloads, [["acc1", ["wf_1", "wf_2"]]]);
  assert.equal(scheduler.size, 0);
});


test("reset cancels polling and stale workflow responses cannot reload", async () => {
  const scheduler = createFakeScheduler();
  let resolveWorkflow;
  const pending = new Promise((resolve) => {
    resolveWorkflow = resolve;
  });
  const reloads = [];
  const polling = createCompetitorWorkflowPolling({
    api: { getCompetitorRefreshWorkflow: async () => pending },
    scheduler,
    onTerminal: (accountId) => reloads.push(accountId),
    onError: () => {},
    intervalMs: 1,
  });

  polling.track("acc1", ["wf_1"]);
  const inFlight = scheduler.runNext();
  polling.reset();
  resolveWorkflow({ status: "completed" });
  await inFlight;

  assert.deepEqual(reloads, []);
  assert.equal(scheduler.size, 0);
});
