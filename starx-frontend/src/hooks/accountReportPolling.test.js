import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  classifyLatestReportWorkflow,
  createAccountReportLifecycle,
  createAccountReportPolling,
  createAccountReportRefreshCoordinator,
  createConcurrentReportSectionPolling,
  isReportWorkflowNotFound,
  shouldAutoGenerateInitialTopics,
} from "./accountReportPolling.js";


function createFakeScheduler() {
  let nextId = 1;
  const timers = new Map();
  return {
    setTimeout(callback) {
      const id = nextId++;
      timers.set(id, callback);
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    get size() {
      return timers.size;
    },
    async runNext() {
      const entry = timers.entries().next().value;
      if (!entry) return;
      const [id, callback] = entry;
      timers.delete(id);
      await callback();
    },
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function createHarness({ getWorkflow, getReport, onComplete } = {}) {
  const scheduler = createFakeScheduler();
  const currentAccountIdRef = { current: "acc1" };
  const timerRef = { current: null };
  const runRef = { current: 0 };
  const state = {
    workflows: [],
    generating: [],
    reports: [],
    completions: [],
    failures: [],
  };
  const polling = createAccountReportPolling({
    api: {
      getReportWorkflow: getWorkflow || (async () => ({ id: "wf1", status: "completed" })),
      getReport: getReport || (async () => ({ accountId: "acc1", reportVersion: 2 })),
    },
    scheduler,
    timerRef,
    runRef,
    currentAccountIdRef,
    isMounted: () => true,
    setWorkflow: (value) => state.workflows.push(value),
    setGenerating: (value) => state.generating.push(value),
    setReport: (value) => state.reports.push(value),
    onComplete: onComplete || ((value) => state.completions.push(value)),
    onFailure: (message) => state.failures.push(message),
    intervalMs: 1,
  });
  return { polling, scheduler, currentAccountIdRef, timerRef, runRef, state };
}

test("pending report workflow polls to completion, reloads report, and leaves no timer", async () => {
  const harness = createHarness();

  harness.polling.start("acc1", { id: "wf1", status: "pending" });
  assert.equal(harness.scheduler.size, 1);
  await harness.scheduler.runNext();

  assert.equal(harness.scheduler.size, 0);
  assert.equal(harness.state.workflows.at(-1).status, "completed");
  assert.deepEqual(harness.state.reports, [{ accountId: "acc1", reportVersion: 2 }]);
  assert.equal(harness.state.completions.length, 1);
  assert.equal(harness.state.completions[0].accountId, "acc1");
  assert.equal(harness.state.generating.at(-1), false);
});

test("only the first completed report with no topics starts initial topic generation", () => {
  assert.equal(shouldAutoGenerateInitialTopics({ reportVersion: 1 }, []), true);
  assert.equal(shouldAutoGenerateInitialTopics({ reportVersion: 2 }, []), false);
  assert.equal(shouldAutoGenerateInitialTopics({ reportVersion: 1 }, [{ id: "t1" }]), false);
  assert.equal(shouldAutoGenerateInitialTopics({ reportVersion: 0 }, []), false);
});

test("different report sections poll concurrently without cancelling each other", async () => {
  const scheduler = createFakeScheduler();
  const currentAccountIdRef = { current: "acc1" };
  const state = { workflows: {}, reports: [] };
  const polling = createConcurrentReportSectionPolling({
    api: {
      getReportWorkflow: async (_accountId, workflowId) => ({ id: workflowId, status: "completed" }),
      getReport: async () => ({ reportVersion: state.reports.length + 1 }),
    },
    scheduler,
    currentAccountIdRef,
    isMounted: () => true,
    setWorkflows: (updater) => {
      state.workflows = typeof updater === "function" ? updater(state.workflows) : updater;
    },
    setReport: (report) => state.reports.push(report),
    intervalMs: 1,
  });

  await polling.start("acc1", "similarAccounts", { id: "wf-similar", status: "running" });
  await polling.start("acc1", "complianceRules", { id: "wf-rules", status: "pending" });

  assert.equal(scheduler.size, 2);
  assert.deepEqual(Object.keys(state.workflows).sort(), ["complianceRules", "similarAccounts"]);

  await scheduler.runNext();
  assert.equal(scheduler.size, 1);
  assert.deepEqual(Object.keys(state.workflows), ["complianceRules"]);

  await scheduler.runNext();
  assert.equal(scheduler.size, 0);
  assert.deepEqual(state.workflows, {});
  assert.equal(state.reports.length, 2);
});

test("failed report workflow stops and preserves the existing report", async () => {
  const harness = createHarness({
    getWorkflow: async () => ({ id: "wf1", status: "failed", error: "生成失败" }),
  });

  harness.polling.start("acc1", { id: "wf1", status: "running" });
  await harness.scheduler.runNext();

  assert.deepEqual(harness.state.reports, []);
  assert.deepEqual(harness.state.failures, ["生成失败"]);
  assert.equal(harness.state.generating.at(-1), false);
  assert.equal(harness.scheduler.size, 0);
});

test("transient poll errors keep loading and continue polling until completion", async () => {
  let requests = 0;
  const harness = createHarness({
    getWorkflow: async () => {
      requests += 1;
      if (requests === 1) throw new Error("network down");
      return { id: "wf1", status: "completed" };
    },
  });

  harness.polling.start("acc1", { id: "wf1", status: "running" });
  await harness.scheduler.runNext();

  assert.equal(harness.state.generating.at(-1), true);
  assert.equal(harness.scheduler.size, 1);
  assert.deepEqual(harness.state.failures, []);

  await harness.scheduler.runNext();

  assert.equal(harness.state.generating.at(-1), false);
  assert.deepEqual(harness.state.reports, [{ accountId: "acc1", reportVersion: 2 }]);
  assert.equal(harness.scheduler.size, 0);
});

test("account switch rejects a stale workflow response and does not schedule again", async () => {
  const response = deferred();
  const harness = createHarness({ getWorkflow: () => response.promise });

  harness.polling.start("acc1", { id: "wf1", status: "running" });
  const pendingPoll = harness.scheduler.runNext();
  harness.currentAccountIdRef.current = "acc2";
  response.resolve({ id: "wf1", status: "completed" });
  await pendingPoll;

  assert.deepEqual(harness.state.reports, []);
  assert.equal(harness.state.workflows.length, 1);
  assert.equal(harness.scheduler.size, 0);
});

test("stop clears the independent report timer and invalidates the current run", async () => {
  let requests = 0;
  const harness = createHarness({
    getWorkflow: async () => {
      requests += 1;
      return { id: "wf1", status: "running" };
    },
  });

  harness.polling.start("acc1", { id: "wf1", status: "pending" });
  const runBeforeStop = harness.runRef.current;
  harness.polling.stop();
  await harness.scheduler.runNext();

  assert.equal(requests, 0);
  assert.equal(harness.scheduler.size, 0);
  assert.equal(harness.timerRef.current, null);
  assert.ok(harness.runRef.current > runBeforeStop);
});

test("already completed workflow reloads once without creating a timer", async () => {
  const harness = createHarness();

  await harness.polling.start("acc1", { id: "wf1", status: "completed" });

  assert.equal(harness.scheduler.size, 0);
  assert.deepEqual(harness.state.reports, [{ accountId: "acc1", reportVersion: 2 }]);
  assert.equal(harness.state.generating.at(-1), false);
});

test("completed workflow report read failure preserves the existing report", async () => {
  const harness = createHarness({
    getReport: async () => {
      throw new Error("report unavailable");
    },
  });

  await harness.polling.start("acc1", { id: "wf1", status: "completed" });

  assert.deepEqual(harness.state.reports, []);
  assert.deepEqual(harness.state.failures, ["账号报告读取失败，已保留原报告"]);
  assert.equal(harness.state.generating.at(-1), false);
  assert.equal(harness.scheduler.size, 0);
});

test("latest workflow 404 is recognized by status even when detail has no number", () => {
  const error = new Error("account report workflow was not found");
  error.status = 404;

  assert.equal(isReportWorkflowNotFound(error), true);
  assert.equal(isReportWorkflowNotFound(new Error("account report workflow was not found")), false);
});

test("completed report read is ignored when account changes before the response", async () => {
  const reportResponse = deferred();
  const harness = createHarness({ getReport: () => reportResponse.promise });

  const completion = harness.polling.start("acc1", { id: "wf1", status: "completed" });
  harness.currentAccountIdRef.current = "acc2";
  harness.polling.stop();
  reportResponse.resolve({ accountId: "acc1", reportVersion: 2 });
  await completion;

  assert.deepEqual(harness.state.reports, []);
  assert.equal(harness.scheduler.size, 0);
});

test("lifecycle guards same-account bundle and refresh responses by latest run", () => {
  const currentAccountIdRef = { current: "acc1" };
  const lifecycle = createAccountReportLifecycle({
    accountBundleRunRef: { current: 0 },
    reportRefreshRequestRunRef: { current: 0 },
    currentAccountIdRef,
    stopPolling: () => {},
    clearReportState: () => {},
    isMounted: () => true,
  });

  const oldBundle = lifecycle.beginBundle("acc1");
  const newBundle = lifecycle.beginBundle("acc1");
  assert.equal(lifecycle.isCurrentBundle(oldBundle, "acc1"), false);
  assert.equal(lifecycle.isCurrentBundle(newBundle, "acc1"), true);

  const oldRefresh = lifecycle.beginRefresh("acc1");
  const newRefresh = lifecycle.beginRefresh("acc1");
  assert.equal(lifecycle.isCurrentRefresh(oldRefresh, "acc1"), false);
  assert.equal(lifecycle.isCurrentRefresh(newRefresh, "acc1"), true);
});

test("lifecycle invalidation clears switch/logout state and unmount avoids state updates", () => {
  const events = [];
  const bundleRef = { current: 3 };
  const refreshRef = { current: 7 };
  const lifecycle = createAccountReportLifecycle({
    accountBundleRunRef: bundleRef,
    reportRefreshRequestRunRef: refreshRef,
    currentAccountIdRef: { current: "acc1" },
    stopPolling: (options) => events.push(["stop", options]),
    clearReportState: () => events.push(["clear"]),
    isMounted: () => true,
  });

  lifecycle.invalidate({ clearState: true });
  lifecycle.invalidate({ clearState: false, updateState: false });

  assert.deepEqual(events, [
    ["stop", { updateState: true }],
    ["clear"],
    ["stop", { updateState: false }],
  ]);
  assert.equal(bundleRef.current, 5);
  assert.equal(refreshRef.current, 9);
});

test("same-account invalidation preserves report state while cross-account invalidation clears it", () => {
  const events = [];
  const lifecycle = createAccountReportLifecycle({
    accountBundleRunRef: { current: 0 },
    reportRefreshRequestRunRef: { current: 0 },
    currentAccountIdRef: { current: "acc1" },
    stopPolling: () => events.push("stop"),
    clearReportState: () => events.push("clear"),
    isMounted: () => true,
  });

  lifecycle.invalidate({ clearState: false });
  assert.deepEqual(events, ["stop"]);

  lifecycle.invalidate({ clearState: true });
  assert.deepEqual(events, ["stop", "stop", "clear"]);
});

test("latest workflow classification keeps 404 quiet and starts only valid workflow results", () => {
  const missing = new Error("not found");
  missing.status = 404;
  const unavailable = new Error("service unavailable");
  unavailable.status = 503;
  const workflow = { id: "wf1", status: "running" };

  assert.deepEqual(classifyLatestReportWorkflow({ error: missing }), { kind: "missing" });
  assert.deepEqual(classifyLatestReportWorkflow({ error: unavailable }), { kind: "error" });
  assert.deepEqual(classifyLatestReportWorkflow({ workflow }), { kind: "workflow", workflow });
});

test("refresh coordinator synchronously rejects a duplicate create request", async () => {
  const creation = deferred();
  const inFlightRef = { current: null };
  const generating = [];
  let creates = 0;
  let starts = 0;
  let requestRun = 0;
  const lifecycle = {
    beginRefresh: () => ++requestRun,
    isCurrentRefresh: (requestId) => requestId === requestRun,
  };
  const coordinator = createAccountReportRefreshCoordinator({
    inFlightRef,
    lifecycle,
    setGenerating: (value) => generating.push(value),
    createWorkflow: () => {
      creates += 1;
      return creation.promise;
    },
    startPolling: async () => {
      starts += 1;
    },
  });

  const first = coordinator.refresh("acc1");
  const second = await coordinator.refresh("acc1");
  assert.equal(second, null);
  assert.equal(creates, 1);
  assert.deepEqual(generating, [true]);

  creation.resolve({ id: "wf1", status: "running" });
  await first;
  assert.equal(starts, 1);
  assert.equal(inFlightRef.current, null);
});

test("refresh coordinator passes the comment choice and optional section to workflow creation", async () => {
  const createdWith = [];
  let requestRun = 0;
  const coordinator = createAccountReportRefreshCoordinator({
    inFlightRef: { current: null },
    lifecycle: {
      beginRefresh: () => ++requestRun,
      isCurrentRefresh: (requestId) => requestId === requestRun,
    },
    setGenerating: () => {},
    createWorkflow: async (accountId, referenceComments, sectionKey) => {
      createdWith.push({ accountId, referenceComments, sectionKey });
      return { id: "wf1", status: "running" };
    },
    startPolling: async () => {},
  });

  await coordinator.refresh("acc1", true, "hotContents");

  assert.deepEqual(createdWith, [{ accountId: "acc1", referenceComments: true, sectionKey: "hotContents" }]);
});

test("stale refresh cleanup cannot clear a newer request generating state", async () => {
  const firstCreation = deferred();
  const secondCreation = deferred();
  const inFlightRef = { current: null };
  const generating = [];
  let requestRun = 0;
  let call = 0;
  const lifecycle = {
    beginRefresh: () => ++requestRun,
    isCurrentRefresh: (requestId) => requestId === requestRun,
  };
  const coordinator = createAccountReportRefreshCoordinator({
    inFlightRef,
    lifecycle,
    setGenerating: (value) => generating.push(value),
    createWorkflow: () => (++call === 1 ? firstCreation.promise : secondCreation.promise),
    startPolling: async () => {},
  });

  const first = coordinator.refresh("acc1");
  coordinator.reset();
  requestRun += 1;
  const second = coordinator.refresh("acc1");
  firstCreation.resolve(null);
  await first;
  assert.deepEqual(generating, [true, true]);

  secondCreation.resolve({ id: "wf2", status: "running" });
  await second;
  assert.equal(inFlightRef.current, null);
});

test("useStarxApp wires the tested lifecycle guards into bundle, refresh, and invalidation paths", () => {
  const source = readFileSync(new URL("./useStarxApp.js", import.meta.url), "utf8");

  assert.match(source, /createAccountReportLifecycle\(\{/);
  assert.match(source, /reportLifecycleRef\.current\.beginBundle\(accountId\)/);
  assert.match(source, /reportLifecycleRef\.current\.isCurrentBundle\(bundleRunId, accountId\)/);
  assert.match(source, /createAccountReportRefreshCoordinator\(\{/);
  assert.match(source, /reportRefreshInFlightRef/);
  assert.match(source, /reportRefreshCoordinatorRef\.current\.refresh\(currentAccountId, referenceComments, sectionKey\)/);
  assert.match(source, /reportRefreshCoordinatorRef\.current\?\.reset\(\)/);
  assert.match(source, /onComplete:\s*\(\{ accountId, report: completedReport \}\)/);
  assert.match(source, /shouldAutoGenerateInitialTopics\(completedReport, topicsRef\.current\)/);
  assert.match(source, /initialTopicGenerationRef\.current\?\.\(accountId\)/);
  assert.match(source, /const isAccountChange = currentAccountIdRef\.current !== accountId;/);
  assert.match(source, /invalidateReportLifecycle\(\{ clearState: isAccountChange \}\)/);
  assert.match(source, /invalidateReportLifecycle\(\{ clearState: false, updateState: false \}\)/);
});
