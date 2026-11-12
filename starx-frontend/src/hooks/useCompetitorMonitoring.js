import { useCallback, useEffect, useRef, useState } from "react";

import { starxApi } from "../api/starx.js";

const TERMINAL_WORKFLOW_STATUSES = new Set(["completed", "failed", "cancelled"]);

export function createCompetitorRequestGate() {
  let runId = 0;
  return {
    begin(accountId) {
      runId += 1;
      return { accountId, runId };
    },
    accept(token, accountId) {
      return Boolean(token) && token.runId === runId && token.accountId === accountId;
    },
    invalidate() {
      runId += 1;
    },
  };
}

export function isCurrentCompetitorAccount(requestedAccountId, currentAccountId) {
  return Boolean(requestedAccountId) && requestedAccountId === currentAccountId;
}

const browserScheduler = {
  setTimeout: (callback, delay) => window.setTimeout(callback, delay),
  clearTimeout: (timerId) => window.clearTimeout(timerId),
};

export function createCompetitorWorkflowPolling({
  api,
  scheduler = browserScheduler,
  onUpdate = () => {},
  onTerminal,
  onError,
  intervalMs = 2000,
}) {
  let timerId = null;
  let runId = 0;
  let trackedAccountId = "";
  let trackedWorkflowIds = new Set();
  let terminalWorkflows = [];
  let inFlight = false;

  const reset = () => {
    runId += 1;
    if (timerId !== null) scheduler.clearTimeout(timerId);
    timerId = null;
    trackedAccountId = "";
    trackedWorkflowIds = new Set();
    terminalWorkflows = [];
    inFlight = false;
  };

  const schedule = () => {
    if (timerId !== null || inFlight || !trackedAccountId || trackedWorkflowIds.size === 0) return;
    const currentRun = runId;
    timerId = scheduler.setTimeout(async () => {
      timerId = null;
      inFlight = true;
      const accountId = trackedAccountId;
      const ids = [...trackedWorkflowIds];
      try {
        const workflows = await Promise.all(
          ids.map((workflowId) => api.getCompetitorRefreshWorkflow(accountId, workflowId))
        );
        if (currentRun !== runId || accountId !== trackedAccountId) return;
        workflows.forEach((workflow, index) => {
          if (!TERMINAL_WORKFLOW_STATUSES.has(workflow?.status)) return;
          trackedWorkflowIds.delete(ids[index]);
          terminalWorkflows.push(workflow);
        });
        onUpdate(accountId, workflows);
        if (trackedWorkflowIds.size === 0) {
          const completed = terminalWorkflows;
          terminalWorkflows = [];
          onTerminal(accountId, completed);
        }
      } catch (error) {
        if (currentRun === runId && accountId === trackedAccountId) onError(error, accountId);
      } finally {
        if (currentRun === runId) {
          inFlight = false;
          schedule();
        }
      }
    }, intervalMs);
  };

  const track = (accountId, workflowIds) => {
    const uniqueIds = [...new Set((workflowIds || []).filter(Boolean))];
    if (!accountId || uniqueIds.length === 0) return;
    if (trackedAccountId && trackedAccountId !== accountId) reset();
    trackedAccountId = accountId;
    uniqueIds.forEach((workflowId) => trackedWorkflowIds.add(workflowId));
    schedule();
  };

  return { reset, track };
}

function replaceTarget(items, target) {
  if (!target?.id) return items;
  const exists = items.some((item) => item.id === target.id);
  return exists
    ? items.map((item) => (item.id === target.id ? target : item))
    : [target, ...items];
}

function mergeAccountTargets(items, targets) {
  const previousById = new Map((items || []).map((item) => [item.id, item]));
  return (targets || []).map((target) => {
    const previous = previousById.get(target.id);
    return previous?.metricHistory
      ? { ...target, metricHistory: previous.metricHistory }
      : target;
  });
}

function workflowIds(response) {
  if (response?.workflow?.id) return [response.workflow.id];
  if (response?.id) return [response.id];
  return (response?.workflows || []).map((workflow) => workflow.id).filter(Boolean);
}

export function activeCompetitorWorkflowIds(items) {
  return [...new Set(
    (items || [])
      .filter((item) => item?.refreshStatus === "pending" || item?.refreshStatus === "running")
      .map((item) => item?.activeWorkflowId)
      .filter(Boolean)
  )];
}

export function markCompetitorTargetsRefreshing(items, workflows) {
  const workflowByTarget = new Map(
    (workflows || [])
      .filter((workflow) => workflow?.inputPayload?.targetId)
      .map((workflow) => [workflow.inputPayload.targetId, workflow])
  );
  return items.map((item) => {
    const workflow = workflowByTarget.get(item.id);
    return workflow
      ? { ...item, refreshStatus: "pending", activeWorkflowId: workflow.id }
      : item;
  });
}

function workflowForTarget(response, targetId) {
  return { ...response, inputPayload: { ...(response?.inputPayload || {}), targetId } };
}

export function useCompetitorMonitoring({ accountId, api = starxApi, addToast = () => {} }) {
  const [accounts, setAccounts] = useState([]);
  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const accountIdRef = useRef(accountId || "");
  const requestGateRef = useRef(createCompetitorRequestGate());
  const pollingRef = useRef(null);
  const partialReloadInFlightRef = useRef(false);
  const mountedRef = useRef(false);

  const load = useCallback(async (requestedAccountId = accountIdRef.current) => {
    if (!requestedAccountId) {
      setAccounts([]);
      setVideos([]);
      setLoading(false);
      return;
    }
    const token = requestGateRef.current.begin(requestedAccountId);
    setLoading(true);
    setError("");
    try {
      const [nextAccounts, nextVideos] = await Promise.all([
        api.getCompetitorAccounts(requestedAccountId),
        api.getCompetitorVideos(requestedAccountId),
      ]);
      const accountItems = Array.isArray(nextAccounts) ? nextAccounts : [];
      if (!mountedRef.current || !requestGateRef.current.accept(token, accountIdRef.current)) return;

      // 账号和刷新状态先展示；历史曲线属于补充信息，不应阻塞主列表刷新。
      setAccounts(accountItems);
      setVideos(Array.isArray(nextVideos) ? nextVideos : []);
      setLoading(false);

      const activeWorkflowIds = activeCompetitorWorkflowIds(accountItems);
      if (activeWorkflowIds.length > 0) {
        pollingRef.current?.track(requestedAccountId, activeWorkflowIds);
      }

      const accountsWithHistory = await Promise.all(
        accountItems.map(async (item) => {
          if (typeof api.getCompetitorAccountMetricTrends !== "function") return item;
          try {
            const history = await api.getCompetitorAccountMetricTrends(
              requestedAccountId,
              item.id,
              30
            );
            return { ...item, metricHistory: Array.isArray(history) ? history : [] };
          } catch (_historyError) {
            return { ...item, metricHistory: [] };
          }
        })
      );
      if (!mountedRef.current || !requestGateRef.current.accept(token, accountIdRef.current)) return;
      const historyByTarget = new Map(
        accountsWithHistory.map((item) => [item.id, item.metricHistory || []])
      );
      setAccounts((items) => items.map((item) => (
        historyByTarget.has(item.id)
          ? { ...item, metricHistory: historyByTarget.get(item.id) }
          : item
      )));
    } catch (loadError) {
      if (!mountedRef.current || !requestGateRef.current.accept(token, accountIdRef.current)) return;
      setError(loadError?.message || "竞品监控数据加载失败");
    } finally {
      if (mountedRef.current && requestGateRef.current.accept(token, accountIdRef.current)) {
        setLoading(false);
      }
    }
  }, [api]);

  const reloadAccountsWhileRefreshing = useCallback(async (requestedAccountId) => {
    if (
      partialReloadInFlightRef.current
      || !isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)
    ) return;
    partialReloadInFlightRef.current = true;
    try {
      const nextAccounts = await api.getCompetitorAccounts(requestedAccountId);
      if (
        mountedRef.current
        && isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)
        && Array.isArray(nextAccounts)
      ) {
        setAccounts((items) => mergeAccountTargets(items, nextAccounts));
      }
    } catch (_error) {
      // 工作流轮询仍会继续；瞬时列表读取失败不覆盖页面已有数据。
    } finally {
      partialReloadInFlightRef.current = false;
    }
  }, [api]);

  useEffect(() => {
    mountedRef.current = true;
    pollingRef.current = createCompetitorWorkflowPolling({
      api,
      onUpdate: (pollingAccountId, workflows) => {
        if (workflows.some((workflow) => !TERMINAL_WORKFLOW_STATUSES.has(workflow?.status))) {
          reloadAccountsWhileRefreshing(pollingAccountId);
        }
      },
      onTerminal: (terminalAccountId, workflows) => {
        if (terminalAccountId !== accountIdRef.current) return;
        load(terminalAccountId);
        const failed = workflows.some((workflow) => workflow.status === "failed");
        addToast(failed ? "部分竞品数据刷新失败，已保留上次数据" : "竞品监控数据已更新", failed ? "warning" : "success");
      },
      onError: () => addToast("刷新状态获取失败，将自动重试", "warning"),
    });
    return () => {
      mountedRef.current = false;
      requestGateRef.current.invalidate();
      pollingRef.current?.reset();
    };
  }, [addToast, api, load, reloadAccountsWhileRefreshing]);

  useEffect(() => {
    accountIdRef.current = accountId || "";
    requestGateRef.current.invalidate();
    pollingRef.current?.reset();
    setAccounts([]);
    setVideos([]);
    setError("");
    load(accountId || "");
  }, [accountId, load]);

  const track = useCallback((response, requestedAccountId = accountIdRef.current) => {
    if (!isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)) return;
    const ids = workflowIds(response);
    if (ids.length > 0) pollingRef.current?.track(requestedAccountId, ids);
  }, []);

  const runAction = useCallback(async (action, successMessage, requestedAccountId) => {
    setError("");
    try {
      const response = await action();
      if (successMessage && isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)) {
        addToast(successMessage, "success");
      }
      return response;
    } catch (actionError) {
      const message = actionError?.message || "操作失败，请稍后重试";
      if (isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)) {
        setError(message);
        addToast(message, "warning");
      }
      throw actionError;
    }
  }, [addToast]);

  const addAccount = useCallback(async (reference) => {
    const requestedAccountId = accountIdRef.current;
    const response = await runAction(
      () => api.addCompetitorAccount(requestedAccountId, reference),
      "已添加监控账号，正在抓取数据",
      requestedAccountId
    );
    if (!isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)) return response;
    setAccounts((items) => replaceTarget(items, response.target));
    track(response, requestedAccountId);
    return response;
  }, [api, runAction, track]);

  const addVideo = useCallback(async (url) => {
    const requestedAccountId = accountIdRef.current;
    const response = await runAction(
      () => api.addCompetitorVideo(requestedAccountId, url),
      "已添加监控视频，正在抓取数据",
      requestedAccountId
    );
    if (!isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)) return response;
    setVideos((items) => replaceTarget(items, response.target));
    track(response, requestedAccountId);
    return response;
  }, [api, runAction, track]);

  const deleteAccount = useCallback(async (targetId) => {
    const requestedAccountId = accountIdRef.current;
    await runAction(() => api.deleteCompetitorAccount(requestedAccountId, targetId), "已删除监控账号", requestedAccountId);
    if (!isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)) return;
    setAccounts((items) => items.filter((item) => item.id !== targetId));
  }, [api, runAction]);

  const deleteVideo = useCallback(async (targetId) => {
    const requestedAccountId = accountIdRef.current;
    await runAction(() => api.deleteCompetitorVideo(requestedAccountId, targetId), "已删除监控视频", requestedAccountId);
    if (!isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)) return;
    setVideos((items) => items.filter((item) => item.id !== targetId));
  }, [api, runAction]);

  const refreshAccount = useCallback(async (targetId) => {
    const requestedAccountId = accountIdRef.current;
    const response = await runAction(
      () => api.refreshCompetitorAccount(requestedAccountId, targetId),
      "账号刷新任务已提交",
      requestedAccountId
    );
    if (isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)) {
      setAccounts((items) => markCompetitorTargetsRefreshing(items, [workflowForTarget(response, targetId)]));
    }
    track(response, requestedAccountId);
  }, [api, runAction, track]);

  const refreshVideo = useCallback(async (targetId) => {
    const requestedAccountId = accountIdRef.current;
    const response = await runAction(
      () => api.refreshCompetitorVideo(requestedAccountId, targetId),
      "视频刷新任务已提交",
      requestedAccountId
    );
    if (isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)) {
      setVideos((items) => markCompetitorTargetsRefreshing(items, [workflowForTarget(response, targetId)]));
    }
    track(response, requestedAccountId);
  }, [api, runAction, track]);

  const refreshAccounts = useCallback(async () => {
    const requestedAccountId = accountIdRef.current;
    const response = await runAction(
      () => api.refreshCompetitorAccounts(requestedAccountId),
      "账号批量刷新任务已提交",
      requestedAccountId
    );
    if (isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)) {
      setAccounts((items) => markCompetitorTargetsRefreshing(items, response.workflows));
    }
    track(response, requestedAccountId);
  }, [api, runAction, track]);

  const refreshVideos = useCallback(async () => {
    const requestedAccountId = accountIdRef.current;
    const response = await runAction(
      () => api.refreshCompetitorVideos(requestedAccountId),
      "视频批量刷新任务已提交",
      requestedAccountId
    );
    if (isCurrentCompetitorAccount(requestedAccountId, accountIdRef.current)) {
      setVideos((items) => markCompetitorTargetsRefreshing(items, response.workflows));
    }
    track(response, requestedAccountId);
  }, [api, runAction, track]);

  return {
    accounts,
    videos,
    loading,
    error,
    reload: load,
    addAccount,
    addVideo,
    deleteAccount,
    deleteVideo,
    refreshAccount,
    refreshVideo,
    refreshAccounts,
    refreshVideos,
  };
}
