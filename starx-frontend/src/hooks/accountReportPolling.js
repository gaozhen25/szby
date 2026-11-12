import { logHotContentsBackendData } from "../utils/accountReport.js";

const ACTIVE_REPORT_STATUSES = new Set(["pending", "running"]);

const browserScheduler = {
  setTimeout: (callback, delay) => window.setTimeout(callback, delay),
  clearTimeout: (timerId) => window.clearTimeout(timerId),
};
export function isReportWorkflowNotFound(error) {
  return error?.status === 404 || /(?:request failed:\s*404|\b404\b)/i.test(String(error?.message || ""));
}

export function classifyLatestReportWorkflow({ workflow, error } = {}) {
  if (workflow?.id) return { kind: "workflow", workflow };
  if (isReportWorkflowNotFound(error)) return { kind: "missing" };
  return error ? { kind: "error" } : { kind: "missing" };
}

export function shouldAutoGenerateInitialTopics(report, topics) {
  return Number(report?.reportVersion || 0) === 1
    && Array.isArray(topics)
    && topics.length === 0;
}

export function createAccountReportRefreshCoordinator({
  inFlightRef,
  lifecycle,
  setGenerating,
  createWorkflow,
  startPolling,
  onFailure = () => {},
}) {
  const reset = () => {
    inFlightRef.current = null;
  };

  const refresh = async (accountId, referenceComments = false, sectionKey = null) => {
    if (!accountId || inFlightRef.current !== null) return null;
    const requestId = lifecycle.beginRefresh(accountId);
    inFlightRef.current = { requestId, accountId };
    setGenerating(true);
    let handedOffToPolling = false;
    try {
      const workflow = await createWorkflow(accountId, referenceComments, sectionKey);
      if (!lifecycle.isCurrentRefresh(requestId, accountId)) return null;
      if (!workflow?.id) throw new Error("report workflow id is missing");
      await startPolling(accountId, workflow);
      handedOffToPolling = true;
      return workflow;
    } catch {
      if (lifecycle.isCurrentRefresh(requestId, accountId)) {
        onFailure(sectionKey ? "该报告板块重新生成启动失败，已保留原内容" : "账号报告刷新启动失败，已保留现有报告");
      }
      return null;
    } finally {
      if (inFlightRef.current?.requestId === requestId) {
        inFlightRef.current = null;
        if (!handedOffToPolling && lifecycle.isCurrentRefresh(requestId, accountId)) {
          setGenerating(false);
        }
      }
    }
  };

  return { refresh, reset };
}

export function createAccountReportLifecycle({
  accountBundleRunRef,
  reportRefreshRequestRunRef,
  currentAccountIdRef,
  stopPolling,
  clearReportState,
  isMounted = () => true,
}) {
  const beginBundle = () => {
    accountBundleRunRef.current += 1;
    return accountBundleRunRef.current;
  };
  const beginRefresh = () => {
    reportRefreshRequestRunRef.current += 1;
    return reportRefreshRequestRunRef.current;
  };
  const isCurrentBundle = (runId, accountId) =>
    isMounted() && accountBundleRunRef.current === runId && currentAccountIdRef.current === accountId;
  const isCurrentRefresh = (runId, accountId) =>
    isMounted() && reportRefreshRequestRunRef.current === runId && currentAccountIdRef.current === accountId;
  const invalidate = ({ clearState = false, updateState = true } = {}) => {
    accountBundleRunRef.current += 1;
    reportRefreshRequestRunRef.current += 1;
    stopPolling({ updateState });
    if (clearState && updateState && isMounted()) clearReportState();
  };
  return { beginBundle, beginRefresh, isCurrentBundle, isCurrentRefresh, invalidate };
}

/**
 * A small account-report polling state machine independent from React.
 * Mutable refs are injected so the hook can own a timer and run generation
 * that never overlap with topic refresh polling.
 */
export function createAccountReportPolling({
  api,
  timerRef,
  runRef,
  currentAccountIdRef,
  setWorkflow,
  setGenerating,
  setReport,
  onComplete = () => {},
  onFailure = () => {},
  isMounted = () => true,
  scheduler = browserScheduler,
  intervalMs = 1500,
}) {
  const clearTimer = () => {
    if (timerRef.current !== null) {
      scheduler.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const stop = ({ updateState = true } = {}) => {
    clearTimer();
    runRef.current += 1;
    if (updateState && isMounted()) setGenerating(false);
  };

  const isCurrent = (runId, accountId) =>
    isMounted() && runRef.current === runId && currentAccountIdRef.current === accountId;

  const settle = (runId) => {
    clearTimer();
    setGenerating(false);
    if (runRef.current === runId) runRef.current += 1;
  };

  const complete = async (runId, accountId, workflow) => {
    setWorkflow(workflow);
    try {
      const nextReport = await api.getReport(accountId);
      if (!isCurrent(runId, accountId)) return;
      logHotContentsBackendData("getReport/workflowComplete", nextReport, {
        accountId,
        workflowId: workflow?.id,
        reportPreview: workflow?.resultPayload?.reportPreview ?? null,
      });
      setReport(nextReport);
      try {
        await onComplete({ accountId, workflow, report: nextReport });
      } catch {
        // The report is already complete; a follow-up action must not turn it into a report failure.
      }
      if (!isCurrent(runId, accountId)) return;
      settle(runId);
    } catch {
      if (!isCurrent(runId, accountId)) return;
      settle(runId);
      onFailure("账号报告读取失败，已保留原报告");
    }
  };

  const fail = (runId, workflow, fallbackMessage) => {
    setWorkflow(workflow);
    settle(runId);
    onFailure(workflow?.error || fallbackMessage);
  };

  const schedule = (runId, accountId, workflowId) => {
    if (!isCurrent(runId, accountId)) return;
    timerRef.current = scheduler.setTimeout(
      () => poll(runId, accountId, workflowId),
      intervalMs
    );
  };

  const poll = async (runId, accountId, workflowId) => {
    timerRef.current = null;
    if (!isCurrent(runId, accountId)) return;
    try {
      const workflow = await api.getReportWorkflow(accountId, workflowId);
      if (!isCurrent(runId, accountId)) return;
      if (workflow.status === "completed") {
        await complete(runId, accountId, workflow);
        return;
      }
      if (workflow.status === "failed") {
        fail(runId, workflow, "账号报告生成失败，已保留原报告");
        return;
      }
      setWorkflow(workflow);
      const preview = workflow?.resultPayload?.reportPreview;
      if (Array.isArray(preview?.hotContents)) {
        logHotContentsBackendData("workflowPoll/reportPreview", preview, {
          accountId,
          workflowId,
          status: workflow?.status,
          completedSections: workflow?.resultPayload?.reportSectionsCompleted ?? [],
        });
      }
      schedule(runId, accountId, workflowId);
    } catch {
      if (!isCurrent(runId, accountId)) return;
      // Keep the loading overlay until the workflow reaches a terminal status.
      schedule(runId, accountId, workflowId);
    }
  };

  const start = async (accountId, workflow) => {
    stop();
    const runId = runRef.current;
    if (!workflow?.id || !isCurrent(runId, accountId)) return;
    setWorkflow(workflow);

    if (workflow.status === "completed") {
      setGenerating(true);
      await complete(runId, accountId, workflow);
      return;
    }
    if (workflow.status === "failed") {
      fail(runId, workflow, "账号报告生成失败，已保留原报告");
      return;
    }
    if (!ACTIVE_REPORT_STATUSES.has(workflow.status)) {
      settle(runId);
      return;
    }

    setGenerating(true);
    schedule(runId, accountId, workflow.id);
  };

  return { start, stop };
}

/** 独立轮询多个报告板块；不同板块互不取消，同一板块新任务替换旧跟踪。 */
export function createConcurrentReportSectionPolling({
  api,
  currentAccountIdRef,
  setWorkflows,
  setReport,
  onFailure = () => {},
  isMounted = () => true,
  scheduler = browserScheduler,
  intervalMs = 1500,
}) {
  const entries = new Map();
  let sequence = 0;

  const publish = (sectionKey, workflow) => {
    if (!isMounted()) return;
    setWorkflows((current) => {
      const next = { ...current };
      if (workflow) next[sectionKey] = workflow;
      else delete next[sectionKey];
      return next;
    });
  };

  const clear = (sectionKey, token, updateState = true) => {
    const entry = entries.get(sectionKey);
    if (!entry || entry.token !== token) return;
    if (entry.timer !== null) scheduler.clearTimeout(entry.timer);
    entries.delete(sectionKey);
    if (updateState) publish(sectionKey, null);
  };

  const isCurrent = (sectionKey, token, accountId) => {
    const entry = entries.get(sectionKey);
    return Boolean(
      entry
      && entry.token === token
      && isMounted()
      && currentAccountIdRef.current === accountId
    );
  };

  const complete = async (sectionKey, token, accountId, workflow) => {
    publish(sectionKey, workflow);
    try {
      const nextReport = await api.getReport(accountId);
      if (!isCurrent(sectionKey, token, accountId)) return;
      setReport(nextReport);
      clear(sectionKey, token);
    } catch {
      if (!isCurrent(sectionKey, token, accountId)) return;
      clear(sectionKey, token);
      onFailure(`${sectionKey}:账号报告读取失败，已保留原报告`);
    }
  };

  const poll = async (sectionKey, token, accountId, workflowId) => {
    const entry = entries.get(sectionKey);
    if (entry?.token === token) entry.timer = null;
    if (!isCurrent(sectionKey, token, accountId)) return;
    try {
      const workflow = await api.getReportWorkflow(accountId, workflowId);
      if (!isCurrent(sectionKey, token, accountId)) return;
      publish(sectionKey, workflow);
      if (workflow.status === "completed") {
        await complete(sectionKey, token, accountId, workflow);
        return;
      }
      if (workflow.status === "failed") {
        clear(sectionKey, token);
        onFailure(workflow.error || "账号报告板块生成失败，已保留原内容");
        return;
      }
      schedule(sectionKey, token, accountId, workflowId);
    } catch {
      if (isCurrent(sectionKey, token, accountId)) {
        schedule(sectionKey, token, accountId, workflowId);
      }
    }
  };

  const schedule = (sectionKey, token, accountId, workflowId) => {
    if (!isCurrent(sectionKey, token, accountId)) return;
    const entry = entries.get(sectionKey);
    entry.timer = scheduler.setTimeout(
      () => poll(sectionKey, token, accountId, workflowId),
      intervalMs,
    );
  };

  const start = async (accountId, sectionKey, workflow) => {
    const previous = entries.get(sectionKey);
    if (previous?.timer !== null && previous?.timer !== undefined) {
      scheduler.clearTimeout(previous.timer);
    }
    const token = ++sequence;
    entries.set(sectionKey, { token, accountId, timer: null });
    if (!workflow?.id || !isCurrent(sectionKey, token, accountId)) {
      clear(sectionKey, token);
      return;
    }
    publish(sectionKey, workflow);
    if (workflow.status === "completed") {
      await complete(sectionKey, token, accountId, workflow);
    } else if (workflow.status === "failed") {
      clear(sectionKey, token);
      onFailure(workflow.error || "账号报告板块生成失败，已保留原内容");
    } else if (ACTIVE_REPORT_STATUSES.has(workflow.status)) {
      schedule(sectionKey, token, accountId, workflow.id);
    } else {
      clear(sectionKey, token);
    }
  };

  const stop = ({ updateState = true } = {}) => {
    entries.forEach((entry) => {
      if (entry.timer !== null) scheduler.clearTimeout(entry.timer);
    });
    entries.clear();
    sequence += 1;
    if (updateState && isMounted()) setWorkflows({});
  };

  return { start, stop };
}
