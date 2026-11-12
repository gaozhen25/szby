import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { starxApi } from "../api/starx";
import { AUTH_SESSION_EXPIRED_EVENT, setAccessToken } from "../api/client";
import { addUniqueJobId } from "../utils/generationCanvas";
import { createWorkflowPublishRequestGate } from "../utils/workflowPublish";
import {
  classifyLatestReportWorkflow,
  createAccountReportLifecycle,
  createAccountReportPolling,
  createAccountReportRefreshCoordinator,
  createConcurrentReportSectionPolling,
  shouldAutoGenerateInitialTopics,
} from "./accountReportPolling";
import { applyAutostartVideoScriptJobResult } from "../utils/videoScriptPackage";
import { stripHashtagsFromTitle } from "../utils/videoAnalysis";
import { normalizeImagePreferences } from "../utils/creationPreferences";
import { logHotContentsBackendData } from "../utils/accountReport";

const defaultCreationState = { version: 1 };

const defaultCreation = {
  creationId: "",
  topicId: "",
  topicTitle: "",
  type: "image",
  targetPlatform: "小红书",
  content: {
    scriptOriginal: [],
    scriptRewritten: [],
    title: "",
    body: "",
    hashtags: [],
    cover: { fileId: "", url: "" },
    bgmSuggestion: "",
    sensitiveCheck: { status: "passed", issues: [] },
    imagePrompt: "",
    assets: [],
  },
  creationState: defaultCreationState,
};

const defaultQuota = {
  aiImage: 0,
  changeBatch: 0,
  changeSingle: 0,
};

const SESSION_EXPIRED_MESSAGE = "登录已过期，请重新登录";

function getAccountAvatar(account = {}) {
  if (account.avatar) return account.avatar;
  const baseName = account.name || account.platforms?.[0] || account.platform || "账";
  return String(baseName).trim().slice(0, 1) || "账";
}

function normalizeAccountRecord(account = {}) {
  const platforms = Array.isArray(account.platforms) && account.platforms.length > 0
    ? account.platforms
    : account.platform
      ? [account.platform]
      : [];

  return {
    ...account,
    platforms,
    accountLinks: account.accountLinks || {},
    platformAccounts: account.platformAccounts || {},
    platformAccountIdentities: account.platformAccountIdentities || {},
    publishSettings: account.publishSettings || {},
    industry: account.industry || "",
    productService: account.productService || "",
    targetCity: account.targetCity || "",
    targetAudience: account.targetAudience || "",
    conversionGoal: account.conversionGoal || "",
    knowledgeBaseId: account.knowledgeBaseId || account.knowledgeBaseSummary?.id || "",
    knowledgeBaseSummary: account.knowledgeBaseSummary || null,
    avatar: getAccountAvatar(account),
    quota: {
      ...defaultQuota,
      ...(account.quota || {}),
    },
  };
}

function normalizeKnowledgeBaseRecord(knowledgeBase = {}) {
  return {
    ...knowledgeBase,
    industry: knowledgeBase.industry || "",
    imageMaterials: Array.isArray(knowledgeBase.imageMaterials) ? knowledgeBase.imageMaterials : [],
    enabledFields: knowledgeBase.enabledFields || {},
  };
}

function normalizeKnowledgeBaseListResponse(response, fallback = {}) {
  const isLegacyArray = Array.isArray(response);
  const rawItems = Array.isArray(response) ? response : Array.isArray(response?.items) ? response.items : [];
  const page = Number(response?.page || fallback.page || 1);
  const pageSize = Number(response?.pageSize || fallback.pageSize || rawItems.length || 20);
  const pageItems = isLegacyArray ? rawItems.slice((page - 1) * pageSize, page * pageSize) : rawItems;
  return {
    items: pageItems.map(normalizeKnowledgeBaseRecord),
    total: Number(isLegacyArray ? rawItems.length : response?.total ?? rawItems.length),
    page,
    pageSize,
    keyword: fallback.keyword || "",
  };
}

function normalizeAccountListResponse(response, fallback = {}) {
  const isLegacyArray = Array.isArray(response);
  const rawItems = Array.isArray(response) ? response : Array.isArray(response?.items) ? response.items : [];
  const page = Number(response?.page || fallback.page || 1);
  const pageSize = Number(response?.pageSize || fallback.pageSize || rawItems.length || 4);
  const pageItems = isLegacyArray ? rawItems.slice((page - 1) * pageSize, page * pageSize) : rawItems;
  return {
    items: pageItems.map(normalizeAccountRecord),
    total: Number(isLegacyArray ? rawItems.length : response?.total ?? rawItems.length),
    page,
    pageSize,
    keyword: fallback.keyword || "",
    platform: fallback.platform || "",
  };
}

function normalizeCreationRecord(creation = defaultCreation) {
  return {
    ...defaultCreation,
    ...creation,
    content: {
      ...defaultCreation.content,
      ...(creation.content || {}),
      scriptOriginal: Array.isArray(creation.content?.scriptOriginal) ? creation.content.scriptOriginal : [],
      scriptRewritten: Array.isArray(creation.content?.scriptRewritten) ? creation.content.scriptRewritten : [],
      hashtags: Array.isArray(creation.content?.hashtags) ? creation.content.hashtags : [],
      cover: creation.content?.cover || defaultCreation.content.cover,
      sensitiveCheck: creation.content?.sensitiveCheck || defaultCreation.content.sensitiveCheck,
      assets: Array.isArray(creation.content?.assets) ? creation.content.assets : [],
    },
    creationState: {
      ...defaultCreationState,
      ...(creation.creationState || {}),
    },
  };
}

function createManualCreation(account) {
  const targetPlatform = account?.platform || account?.platforms?.[0] || "小红书";
  return normalizeCreationRecord({
    ...defaultCreation,
    creationId: `manual_${Date.now()}`,
    topicTitle: "手动新建素材",
    targetPlatform,
    content: {
      ...defaultCreation.content,
      title: "",
      body: "",
    },
    creationState: {
      ...defaultCreationState,
      entryModeSelectionRequired: true,
      creationWizardStep: 0,
      completedCreationWizardSteps: [],
      creationWizardProgressByType: {
        image: { currentStep: 0, completedSteps: [] },
        video: { currentStep: 0, completedSteps: [] },
      },
    },
  });
}

export function useStarxApp() {
  const [currentUser, setCurrentUser] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [accountPage, setAccountPage] = useState({ page: 1, pageSize: 4, total: 0, keyword: "", platform: "" });
  const [accountLoading, setAccountLoading] = useState(false);
  const [currentAccountRecord, setCurrentAccountRecord] = useState(null);
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [knowledgeBaseList, setKnowledgeBaseList] = useState([]);
  const [knowledgeBasePage, setKnowledgeBasePage] = useState({ page: 1, pageSize: 12, total: 0, keyword: "" });
  const [knowledgeBaseLoading, setKnowledgeBaseLoading] = useState(false);
  const [currentAccountId, setCurrentAccountId] = useState("");
  const [topics, setTopics] = useState([]);
  const [favoriteTopics, setFavoriteTopics] = useState([]);
  const [topicRefreshWorkflow, setTopicRefreshWorkflow] = useState(null);
  const [isRefreshingTopics, setIsRefreshingTopics] = useState(false);
  const [tasks, setTasks] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [digitalHumanProfiles, setDigitalHumanProfiles] = useState([]);
  const [generationJobs, setGenerationJobs] = useState([]);
  const [videoAnalysisJobs, setVideoAnalysisJobs] = useState([]);
  const [extractHistories, setExtractHistories] = useState([]);
  const [promptTagCategories, setPromptTagCategories] = useState([]);
  const [promptTemplates, setPromptTemplates] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [summary, setSummary] = useState([]);
  const [report, setReport] = useState(null);
  const [reportWorkflow, setReportWorkflow] = useState(null);
  const [reportSectionWorkflows, setReportSectionWorkflows] = useState({});
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [creation, setCreation] = useState(defaultCreation);
  const [publishStates, setPublishStates] = useState({});
  const [canvasJobIds, setCanvasJobIds] = useState([]);
  const [activeCanvasJobId, setActiveCanvasJobId] = useState("");
  const [activePage, setActivePage] = useState("account");
  const [toasts, setToasts] = useState([]);
  const [showAddAccountModal, setShowAddAccountModal] = useState(false);
  const [editingAccount, setEditingAccount] = useState(null);
  const [showKnowledgeBaseModal, setShowKnowledgeBaseModal] = useState(false);
  const [editingKnowledgeBase, setEditingKnowledgeBase] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const currentAccountIdRef = useRef("");
  const knowledgeBaseCreatedCallbackRef = useRef(null);
  const workflowPublishRequestGateRef = useRef(createWorkflowPublishRequestGate());
  const topicRefreshTimerRef = useRef(null);
  const topicRefreshRunRef = useRef(0);
  const reportWorkflowTimerRef = useRef(null);
  const reportWorkflowRunRef = useRef(0);
  const accountBundleRunRef = useRef(0);
  const reportRefreshRequestRunRef = useRef(0);
  const reportRefreshInFlightRef = useRef(null);
  const reportSectionRefreshInFlightRef = useRef(new Set());
  const reportSectionWorkflowsRef = useRef({});
  const reportSectionPollingRef = useRef(null);
  const reportPollingControllerRef = useRef(null);
  const reportLifecycleRef = useRef(null);
  const reportRefreshCoordinatorRef = useRef(null);
  const isMountedRef = useRef(false);
  const topicsRef = useRef([]);
  const initialTopicGenerationRef = useRef(null);

  const currentAccount = useMemo(
    () => accounts.find((account) => account.id === currentAccountId) || currentAccountRecord,
    [accounts, currentAccountId, currentAccountRecord]
  );

  useEffect(() => {
    currentAccountIdRef.current = currentAccountId;
  }, [currentAccountId]);

  const addToast = useCallback((message, type = "") => {
    if (!isMountedRef.current) return;
    const id = `${Date.now()}_${Math.random()}`;
    setToasts((prev) => [...prev, { id, message, type }]);
    window.setTimeout(() => {
      if (isMountedRef.current) {
        setToasts((prev) => prev.filter((toast) => toast.id !== id));
      }
    }, 2500);
  }, []);

  if (reportPollingControllerRef.current === null) {
    reportPollingControllerRef.current = createAccountReportPolling({
      api: starxApi,
      timerRef: reportWorkflowTimerRef,
      runRef: reportWorkflowRunRef,
      currentAccountIdRef,
      isMounted: () => isMountedRef.current,
      setWorkflow: setReportWorkflow,
      setGenerating: setIsGeneratingReport,
      setReport,
      onComplete: ({ accountId, report: completedReport }) => {
        if (!shouldAutoGenerateInitialTopics(completedReport, topicsRef.current)) return null;
        return initialTopicGenerationRef.current?.(accountId) || null;
      },
      onFailure: (message) => addToast(message, "warning"),
    });
  }

  const updateReportSectionWorkflows = (updater) => {
    setReportSectionWorkflows((current) => {
      const next = typeof updater === "function" ? updater(current) : updater;
      reportSectionWorkflowsRef.current = next;
      return next;
    });
  };

  if (reportSectionPollingRef.current === null) {
    reportSectionPollingRef.current = createConcurrentReportSectionPolling({
      api: starxApi,
      currentAccountIdRef,
      isMounted: () => isMountedRef.current,
      setWorkflows: updateReportSectionWorkflows,
      setReport: (nextReport) => setReport((current) => {
        const currentVersion = Number(current?.reportVersion || 0);
        const nextVersion = Number(nextReport?.reportVersion || 0);
        return nextVersion >= currentVersion ? nextReport : current;
      }),
      onFailure: (message) => addToast(message, "warning"),
    });
  }

  if (reportLifecycleRef.current === null) {
    reportLifecycleRef.current = createAccountReportLifecycle({
      accountBundleRunRef,
      reportRefreshRequestRunRef,
      currentAccountIdRef,
      isMounted: () => isMountedRef.current,
      stopPolling: (options) => {
        reportPollingControllerRef.current?.stop(options);
        reportSectionPollingRef.current?.stop(options);
        reportSectionRefreshInFlightRef.current.clear();
      },
      clearReportState: () => {
        setReport(null);
        setReportWorkflow(null);
        updateReportSectionWorkflows({});
        setIsGeneratingReport(false);
      },
    });
  }

  if (reportRefreshCoordinatorRef.current === null) {
    reportRefreshCoordinatorRef.current = createAccountReportRefreshCoordinator({
      inFlightRef: reportRefreshInFlightRef,
      lifecycle: reportLifecycleRef.current,
      setGenerating: setIsGeneratingReport,
      createWorkflow: (accountId, referenceComments, sectionKey) => {
        const sectionWorkflowCreators = {
          similarAccounts: starxApi.createSimilarAccountsReportWorkflow,
          complianceRules: starxApi.createComplianceRulesReportWorkflow,
          targetUserProfile: starxApi.createTargetUserProfileReportWorkflow,
          hotContents: starxApi.createHotContentsReportWorkflow,
        };
        const createWorkflow = sectionWorkflowCreators[sectionKey] || starxApi.createReportWorkflow;
        return createWorkflow(accountId, referenceComments);
      },
      startPolling: (accountId, workflow) => reportPollingControllerRef.current.start(accountId, workflow),
      onFailure: (message) => addToast(message, "warning"),
    });
  }

  const stopAccountReportPolling = useCallback(() => {
    reportPollingControllerRef.current?.stop();
    reportSectionPollingRef.current?.stop();
    reportSectionRefreshInFlightRef.current.clear();
  }, []);

  const invalidateReportLifecycle = useCallback((options) => {
    reportRefreshCoordinatorRef.current?.reset();
    reportLifecycleRef.current.invalidate(options);
  }, []);

  const stopTopicRefreshPolling = useCallback(() => {
    if (topicRefreshTimerRef.current) {
      window.clearTimeout(topicRefreshTimerRef.current);
      topicRefreshTimerRef.current = null;
    }
    topicRefreshRunRef.current += 1;
  }, []);

  const isCurrentTopicRefreshRun = useCallback(
    (runId, accountId) =>
      isMountedRef.current &&
      topicRefreshRunRef.current === runId &&
      currentAccountIdRef.current === accountId,
    []
  );

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      workflowPublishRequestGateRef.current.reset();
      stopTopicRefreshPolling();
      invalidateReportLifecycle({ clearState: false, updateState: false });
    };
  }, [invalidateReportLifecycle, stopTopicRefreshPolling]);

  const refreshKnowledgeBaseOptions = useCallback(async () => {
    const response = await starxApi.getKnowledgeBases({ page: 1, pageSize: 100 });
    const normalized = normalizeKnowledgeBaseListResponse(response, { page: 1, pageSize: 100 });
    setKnowledgeBases(normalized.items);
    return normalized.items;
  }, []);

  const loadKnowledgeBasesPage = useCallback(async ({ page = 1, pageSize = 12, keyword = "" } = {}) => {
    setKnowledgeBaseLoading(true);
    try {
      const response = await starxApi.getKnowledgeBases({ page, pageSize, keyword });
      const normalized = normalizeKnowledgeBaseListResponse(response, { page, pageSize, keyword });
      setKnowledgeBaseList(normalized.items);
      setKnowledgeBasePage({
        page: normalized.page,
        pageSize: normalized.pageSize,
        total: normalized.total,
        keyword: normalized.keyword,
      });
      return normalized;
    } finally {
      setKnowledgeBaseLoading(false);
    }
  }, []);

  const loadAccountsPage = useCallback(async ({ page = 1, pageSize = 4, keyword = "", platform = "" } = {}) => {
    setAccountLoading(true);
    try {
      const response = await starxApi.getAccounts({ page, pageSize, keyword, platform });
      const normalized = normalizeAccountListResponse(response, { page, pageSize, keyword, platform });
      setAccounts(normalized.items);
      setAccountPage({
        page: normalized.page,
        pageSize: normalized.pageSize,
        total: normalized.total,
        keyword: normalized.keyword,
        platform: normalized.platform,
      });
      const visibleCurrent = normalized.items.find((account) => account.id === currentAccountIdRef.current);
      if (visibleCurrent) {
        setCurrentAccountRecord(visibleCurrent);
      }
      return normalized;
    } finally {
      setAccountLoading(false);
    }
  }, []);

  const loadAccountBundle = useCallback(
    async (accountId) => {
      stopAccountReportPolling();
      currentAccountIdRef.current = accountId;
      const bundleRunId = reportLifecycleRef.current.beginBundle(accountId);
      const [
        topicsData,
        favoriteTopicsData,
        tasksData,
        materialsData,
        digitalHumanProfilesData,
        dashboardData,
        reportData,
        summaryData,
        videoAnalysisJobsData,
        extractHistoriesData,
        promptTagsData,
        promptTemplatesData,
        generationJobsData,
        latestReportWorkflowResult,
        activeReportWorkflows,
      ] = await Promise.all([
        starxApi.getTopics(accountId),
        starxApi.getFavoriteTopics(accountId),
        starxApi.getTasks(accountId),
        starxApi.getMaterials(accountId),
        starxApi.getDigitalHumanProfiles(accountId).catch(() => []),
        starxApi.getDashboard(accountId),
        starxApi.getReport(accountId),
        starxApi.getSummary(),
        starxApi.getVideoAnalysisJobs({ accountId }),
        starxApi.getExtractLinkHistory(),
        starxApi.getPromptTags(accountId).catch(() => []),
        starxApi.getPromptTemplates(accountId).catch(() => []),
        starxApi.getGenerationJobs(accountId, { page: 1, limit: 10 }).catch(() => []),
        starxApi.getLatestReportWorkflow(accountId)
          .then((workflow) => classifyLatestReportWorkflow({ workflow }))
          .catch((error) => classifyLatestReportWorkflow({ error })),
        starxApi.getActiveReportWorkflows(accountId).catch(() => []),
      ]);
      if (!reportLifecycleRef.current.isCurrentBundle(bundleRunId, accountId)) return;
      topicsRef.current = topicsData;
      setTopics(topicsData);
      setFavoriteTopics(favoriteTopicsData);
      setTopicRefreshWorkflow(null);
      setIsRefreshingTopics(false);
      stopTopicRefreshPolling();
      setTasks(tasksData);
      setMaterials(materialsData);
      setDigitalHumanProfiles(digitalHumanProfilesData);
      setDashboard(dashboardData);
      setReport(reportData);
      logHotContentsBackendData("getReport/loadAccountBundle", reportData, { accountId });
      setReportWorkflow(null);
      updateReportSectionWorkflows({});
      setIsGeneratingReport(false);
      const activeFullWorkflow = activeReportWorkflows.find((item) => item.type === "account_report");
      const activeSectionWorkflows = activeReportWorkflows.filter((item) => item.inputPayload?.sectionKey);
      if (activeFullWorkflow) {
        void reportPollingControllerRef.current.start(accountId, activeFullWorkflow);
      } else if (latestReportWorkflowResult.kind === "workflow" && !activeSectionWorkflows.length) {
        void reportPollingControllerRef.current.start(accountId, latestReportWorkflowResult.workflow);
      } else if (latestReportWorkflowResult.kind === "error") {
        addToast("账号报告状态读取失败，已保留现有报告", "warning");
      }
      activeSectionWorkflows.forEach((workflow) => {
        void reportSectionPollingRef.current.start(
          accountId,
          workflow.inputPayload.sectionKey,
          workflow,
        );
      });
      setSummary(summaryData);
      setGenerationJobs(generationJobsData || []);
      setVideoAnalysisJobs(videoAnalysisJobsData);
      setExtractHistories(extractHistoriesData);
      setPromptTagCategories(promptTagsData);
      setPromptTemplates(promptTemplatesData);
    },
    [addToast, stopAccountReportPolling, stopTopicRefreshPolling]
  );

  const bootstrapWorkspace = useCallback(
    async (user) => {
      setCurrentUser(user);
      const [accountsData, knowledgeBaseOptionsData, knowledgeBasePageData] = await Promise.all([
        starxApi.getAccounts({ page: 1, pageSize: 4 }),
        starxApi.getKnowledgeBases({ page: 1, pageSize: 100 }),
        starxApi.getKnowledgeBases({ page: 1, pageSize: 12 }),
      ]);
      const normalizedAccountPage = normalizeAccountListResponse(accountsData, { page: 1, pageSize: 4 });
      const normalizedKnowledgeBaseOptions = normalizeKnowledgeBaseListResponse(knowledgeBaseOptionsData, { page: 1, pageSize: 100 });
      const normalizedKnowledgeBasePage = normalizeKnowledgeBaseListResponse(knowledgeBasePageData, { page: 1, pageSize: 12 });
      setKnowledgeBases(normalizedKnowledgeBaseOptions.items);
      setKnowledgeBaseList(normalizedKnowledgeBasePage.items);
      setKnowledgeBasePage({
        page: normalizedKnowledgeBasePage.page,
        pageSize: normalizedKnowledgeBasePage.pageSize,
        total: normalizedKnowledgeBasePage.total,
        keyword: "",
      });
      setAccounts(normalizedAccountPage.items);
      setAccountPage({
        page: normalizedAccountPage.page,
        pageSize: normalizedAccountPage.pageSize,
        total: normalizedAccountPage.total,
        keyword: "",
        platform: "",
      });
      if (normalizedAccountPage.items.length > 0) {
        setCurrentAccountRecord(normalizedAccountPage.items[0]);
        setCurrentAccountId(normalizedAccountPage.items[0].id);
        setCanvasJobIds([]);
        setActiveCanvasJobId("");
        await loadAccountBundle(normalizedAccountPage.items[0].id);
      } else {
        currentAccountIdRef.current = "";
        setCurrentAccountRecord(null);
        setCurrentAccountId("");
        setTopics([]);
        setFavoriteTopics([]);
        setTopicRefreshWorkflow(null);
        setIsRefreshingTopics(false);
        stopTopicRefreshPolling();
        invalidateReportLifecycle({ clearState: true });
        setTasks([]);
        setMaterials([]);
        setDigitalHumanProfiles([]);
        setGenerationJobs([]);
        setVideoAnalysisJobs([]);
        setExtractHistories([]);
        setCanvasJobIds([]);
        setActiveCanvasJobId("");
        setDashboard(null);
        setReport(null);
        setSummary([]);
      }
    },
    [invalidateReportLifecycle, loadAccountBundle, stopTopicRefreshPolling]
  );

  useEffect(() => {
    async function bootstrap() {
      const token =
        typeof window !== "undefined" ? window.localStorage.getItem("starx_token") || "" : "";
      if (!token) {
        setCurrentUser(null);
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        const user = await starxApi.me();
        await bootstrapWorkspace(user);
      } catch (err) {
        setAccessToken("");
        setCurrentUser(null);
        if (err?.status === 401 || err?.isAuthExpired) {
          setError(SESSION_EXPIRED_MESSAGE);
        }
      } finally {
        setLoading(false);
      }
    }

    bootstrap();
  }, [bootstrapWorkspace]);

  const switchAccount = useCallback(
    async (accountId) => {
      const isAccountChange = currentAccountIdRef.current !== accountId;
      invalidateReportLifecycle({ clearState: isAccountChange });
      stopTopicRefreshPolling();
      currentAccountIdRef.current = accountId;
      setTopicRefreshWorkflow(null);
      if (isAccountChange) {
        // Drop previous account topics immediately so Topic Center never flashes stale cards.
        setTopics([]);
        setFavoriteTopics([]);
        setIsRefreshingTopics(true);
        setCanvasJobIds([]);
        setActiveCanvasJobId("");
        setDigitalHumanProfiles([]);
        workflowPublishRequestGateRef.current.reset();
        setPublishStates({});
      } else {
        setIsRefreshingTopics(false);
      }
      const nextCurrentAccount = accounts.find((account) => account.id === accountId);
      if (nextCurrentAccount) {
        setCurrentAccountRecord(nextCurrentAccount);
      }
      setCurrentAccountId(accountId);
      try {
        await loadAccountBundle(accountId);
      } catch (error) {
        if (currentAccountIdRef.current === accountId) {
          setIsRefreshingTopics(false);
        }
        throw error;
      }
    },
    [accounts, invalidateReportLifecycle, loadAccountBundle, stopTopicRefreshPolling]
  );

  const refreshAccountReport = useCallback(async (referenceComments = false, sectionKey = null) => {
    if (!currentAccountId) return null;
    if (sectionKey) {
      const active = reportSectionWorkflowsRef.current[sectionKey];
      if (active || reportSectionRefreshInFlightRef.current.has(sectionKey)) return active || null;
      const creators = {
        similarAccounts: starxApi.createSimilarAccountsReportWorkflow,
        complianceRules: starxApi.createComplianceRulesReportWorkflow,
        targetUserProfile: starxApi.createTargetUserProfileReportWorkflow,
        hotContents: starxApi.createHotContentsReportWorkflow,
      };
      const createWorkflow = creators[sectionKey];
      if (!createWorkflow) return null;
      reportSectionRefreshInFlightRef.current.add(sectionKey);
      try {
        const workflow = await createWorkflow(currentAccountId, referenceComments);
        await reportSectionPollingRef.current.start(currentAccountId, sectionKey, workflow);
        return workflow;
      } catch (error) {
        addToast("该报告板块重新生成启动失败，已保留原内容", "warning");
        return null;
      } finally {
        reportSectionRefreshInFlightRef.current.delete(sectionKey);
      }
    }
    return reportRefreshCoordinatorRef.current.refresh(currentAccountId, referenceComments, sectionKey);
  }, [addToast, currentAccountId]);

  const addReportSimilarAccount = useCallback(async (payload) => {
    if (!currentAccountId) return null;
    const requestAccountId = currentAccountId;
    try {
      const nextReport = await starxApi.addReportSimilarAccount(requestAccountId, payload);
      if (currentAccountIdRef.current === requestAccountId) setReport(nextReport);
      addToast("相似账号已添加", "success");
      return nextReport;
    } catch (err) {
      addToast(err.message || "添加相似账号失败", "warning");
      throw err;
    }
  }, [addToast, currentAccountId]);

  const resolveReportSimilarAccount = useCallback(async (profileUrl) => {
    if (!currentAccountId || !profileUrl) return null;
    try {
      return await starxApi.resolveReportSimilarAccount(currentAccountId, profileUrl);
    } catch (err) {
      addToast(err.message || "账号链接解析失败", "warning");
      throw err;
    }
  }, [addToast, currentAccountId]);

  const deleteReportSimilarAccount = useCallback(async (configurationKey) => {
    if (!currentAccountId || !configurationKey) return null;
    const requestAccountId = currentAccountId;
    try {
      const nextReport = await starxApi.deleteReportSimilarAccount(
        requestAccountId,
        configurationKey
      );
      if (currentAccountIdRef.current === requestAccountId) setReport(nextReport);
      addToast("相似账号已删除", "success");
      return nextReport;
    } catch (err) {
      addToast(err.message || "删除相似账号失败", "warning");
      throw err;
    }
  }, [addToast, currentAccountId]);

  const addCompetitorAccount = useCallback(async (profileUrl) => {
    if (!currentAccountId || !profileUrl) return null;
    return starxApi.addCompetitorAccount(currentAccountId, profileUrl);
  }, [currentAccountId]);

  const refreshTopics = useCallback(async () => {
    if (!currentAccountId || isRefreshingTopics) return;
    const requestAccountId = currentAccountId;
    stopTopicRefreshPolling();
    const runId = topicRefreshRunRef.current;

    const scheduleNextPoll = (workflowId) => {
      if (!isCurrentTopicRefreshRun(runId, requestAccountId)) return;
      topicRefreshTimerRef.current = window.setTimeout(() => {
        pollTopicRefreshWorkflow(workflowId);
      }, 1500);
    };

    const pollTopicRefreshWorkflow = async (workflowId) => {
      topicRefreshTimerRef.current = null;
      if (!isCurrentTopicRefreshRun(runId, requestAccountId)) return;

      try {
        const latest = await starxApi.getTopicRefreshWorkflow(requestAccountId, workflowId);
        if (!isCurrentTopicRefreshRun(runId, requestAccountId)) return;

        setTopicRefreshWorkflow(latest);

        if (latest.status === "completed") {
          const nextTopics = await starxApi.getTopics(requestAccountId);
          if (!isCurrentTopicRefreshRun(runId, requestAccountId)) return;

          stopTopicRefreshPolling();
          topicsRef.current = nextTopics;
          setTopics(nextTopics);
          setIsRefreshingTopics(false);
          addToast("AI 已生成新一批选题", "success");
          return;
        }

        if (latest.status === "failed") {
          stopTopicRefreshPolling();
          setIsRefreshingTopics(false);
          addToast(latest.error || "AI 选题生成失败，已保留原选题", "warning");
          return;
        }

        scheduleNextPoll(workflowId);
      } catch (err) {
        if (!isCurrentTopicRefreshRun(runId, requestAccountId)) return;
        stopTopicRefreshPolling();
        setIsRefreshingTopics(false);
        addToast("选题刷新状态获取失败，已保留原选题", "warning");
      }
    };

    setIsRefreshingTopics(true);
    try {
      const workflow = await starxApi.refreshTopics(requestAccountId);
      if (!isCurrentTopicRefreshRun(runId, requestAccountId)) return;
      setTopicRefreshWorkflow(workflow);
      scheduleNextPoll(workflow.id);
    } catch (err) {
      if (isCurrentTopicRefreshRun(runId, requestAccountId)) {
        stopTopicRefreshPolling();
        setIsRefreshingTopics(false);
        addToast("选题刷新启动失败", "warning");
      }
    }
  }, [addToast, currentAccountId, isCurrentTopicRefreshRun, isRefreshingTopics, stopTopicRefreshPolling]);

  initialTopicGenerationRef.current = (accountId) => {
    if (currentAccountIdRef.current !== accountId || topicsRef.current.length > 0) return null;
    return refreshTopics();
  };

  const replaceSingleTopic = useCallback(
    (topicId) => {
      if (!currentAccount?.quota?.changeSingle) {
        addToast("单题换一个次数已用完", "warning");
        return;
      }
      setTopics((prev) =>
        prev.map((topic) =>
          topic.id === topicId
            ? { ...topic, id: `${topic.id}_${Date.now()}`, title: `🆕 精选新选题 #${Math.floor(Math.random() * 100)}` }
            : topic
        )
      );
      addToast("已替换单个选题");
    },
    [addToast, currentAccount]
  );

  const favoriteTopic = useCallback(async (topicId) => {
    if (!currentAccountId) return null;
    const favorite = await starxApi.favoriteTopic(currentAccountId, topicId);
    setFavoriteTopics((prev) => {
      const withoutDuplicate = prev.filter((item) => item.id !== favorite.id);
      return [favorite, ...withoutDuplicate];
    });
    addToast("已收藏，可在「我的收藏」中随时查看", "success");
    return favorite;
  }, [addToast, currentAccountId]);

  const deleteFavoriteTopic = useCallback(async (favoriteId) => {
    if (!currentAccountId) return;
    await starxApi.deleteFavoriteTopic(currentAccountId, favoriteId);
    setFavoriteTopics((prev) => prev.filter((item) => item.id !== favoriteId));
    addToast("已从收藏中删除", "success");
  }, [addToast, currentAccountId]);

  const upsertGenerationJob = useCallback((job) => {
    setGenerationJobs((prev) => {
      const exists = prev.some((item) => item.id === job.id);
      if (exists) {
        return prev.map((item) => (item.id === job.id ? job : item));
      }
      return [job, ...prev];
    });
  }, []);

  const upsertVideoAnalysisJob = useCallback((job) => {
    setVideoAnalysisJobs((prev) => {
      const exists = prev.some((item) => item.id === job.id);
      if (exists) {
        return prev.map((item) => (item.id === job.id ? job : item));
      }
      return [job, ...prev];
    });
  }, []);

  const refreshGenerationJob = useCallback(
    async (jobId) => {
      if (!currentAccountId || !jobId) return null;
      const requestAccountId = currentAccountId;
      const job = await starxApi.getGenerationJob(requestAccountId, jobId);
      if (currentAccountIdRef.current === requestAccountId) {
        upsertGenerationJob(job);
      }
      return job;
    },
    [currentAccountId, upsertGenerationJob]
  );

  const createPromptJob = useCallback(
    async (payload) => {
      if (!currentAccountId) return null;
      const job = await starxApi.createPromptJob(currentAccountId, payload);
      upsertGenerationJob(job);
      addToast("已开始生成生图提示词");
      return job;
    },
    [addToast, currentAccountId, upsertGenerationJob]
  );

  const createTopicPromptJob = useCallback(
    async (payload) => {
      if (!currentAccountId) return null;
      const job = await starxApi.createTopicPromptJob(currentAccountId, payload);
      upsertGenerationJob(job);
      addToast("已开始根据选题生成生图提示词");
      return job;
    },
    [addToast, currentAccountId, upsertGenerationJob]
  );

  const createImageJob = useCallback(
    async (payload) => {
      if (!currentAccountId) return null;
      const job = await starxApi.createImageJob(currentAccountId, payload);
      upsertGenerationJob(job);
      addToast("已开始生成图片");
      return job;
    },
    [addToast, currentAccountId, upsertGenerationJob]
  );

  const refreshDigitalHumanProfiles = useCallback(async () => {
    if (!currentAccountId) return [];
    const requestAccountId = currentAccountId;
    const profiles = await starxApi.getDigitalHumanProfiles(requestAccountId);
    if (currentAccountIdRef.current === requestAccountId) setDigitalHumanProfiles(profiles);
    return profiles;
  }, [currentAccountId]);

  const createDigitalHumanProfile = useCallback(async (payload) => {
    if (!currentAccountId) return null;
    const response = await starxApi.createDigitalHumanProfile(currentAccountId, payload);
    setDigitalHumanProfiles((current) => [
      response.profile,
      ...current.filter((item) => item.id !== response.profile.id),
    ]);
    upsertGenerationJob(response.workflow);
    addToast("数字人素材已上传，正在检测并克隆声音", "success");
    return response;
  }, [addToast, currentAccountId, upsertGenerationJob]);

  const disableDigitalHumanProfile = useCallback(async (profileId) => {
    if (!currentAccountId || !profileId) return null;
    const profile = await starxApi.disableDigitalHumanProfile(currentAccountId, profileId);
    setDigitalHumanProfiles((current) => current.filter((item) => item.id !== profile.id));
    addToast("数字人已停用", "success");
    return profile;
  }, [addToast, currentAccountId]);

  const createDigitalHumanVideo = useCallback(async (payload) => {
    if (!currentAccountId) return null;
    const job = await starxApi.createDigitalHumanVideo(currentAccountId, payload);
    upsertGenerationJob(job);
    addToast("数字人口播视频已开始生成", "success");
    return job;
  }, [addToast, currentAccountId, upsertGenerationJob]);

  const createScriptRewriteJob = useCallback(
    async (payload) => {
      if (!currentAccountId) return null;
      const job = await starxApi.createScriptRewriteJob(currentAccountId, payload);
      upsertGenerationJob(job);
      addToast("已开始 AI 改写脚本");
      return job;
    },
    [addToast, currentAccountId, upsertGenerationJob]
  );

  const createVideoScriptJob = useCallback(
    async (payload) => {
      if (!currentAccountId) return null;
      const job = await starxApi.createVideoScriptJob(currentAccountId, payload);
      upsertGenerationJob(job);
      addToast("已开始生成视频脚本");
      return job;
    },
    [addToast, currentAccountId, upsertGenerationJob]
  );

  const generateCreation = useCallback(
    async (topicId, targetPlatform, preferences) => {
      if (!currentAccountId) return;
      const nextCreation = normalizeCreationRecord(
        await starxApi.generateCreation(currentAccountId, topicId, targetPlatform)
      );
      if (nextCreation.type === "video") {
        const creationState = {
          ...(nextCreation.creationState || {}),
          videoScriptTargetPlatform: preferences.targetPlatform,
          videoScriptDurationSeconds: preferences.durationSeconds,
          videoScriptContentGoal: preferences.contentGoal,
          videoScriptFormat: preferences.videoFormat,
          videoScriptToneStyle: preferences.toneStyle,
          videoScriptCustomRequirements: preferences.customRequirements,
        };
        setCreation(normalizeCreationRecord({ ...nextCreation, creationState }));
        setActivePage("creation");
        addToast("已进入创作流程 · 视频模式");
        try {
          const job = await starxApi.createVideoScriptJob(currentAccountId, {
            topicId,
            targetPlatform: nextCreation.targetPlatform || targetPlatform,
            durationSeconds: preferences.durationSeconds,
            contentGoal: preferences.contentGoal,
            videoFormat: preferences.videoFormat,
            toneStyle: preferences.toneStyle,
            customRequirements: preferences.customRequirements,
          });
          upsertGenerationJob(job);
          setCreation((currentCreation) => {
            const nextOwnedCreation = applyAutostartVideoScriptJobResult(currentCreation, {
              creationId: nextCreation.creationId,
              jobId: job.id,
              preferences,
            });
            return nextOwnedCreation === currentCreation
              ? currentCreation
              : normalizeCreationRecord(nextOwnedCreation);
          });
          addToast("已开始生成视频脚本");
        } catch (err) {
          const failureMessage = err.message || "自动生成视频脚本失败";
          addToast(`${failureMessage}，可在创作页面重试`, "warning");
        }
        return;
      }

      const referenceNote = nextCreation.creationState?.referenceNote || {};
      const hasImageReference = referenceNote.contentType === "image" && Boolean(referenceNote.publicUrl);
      if (!hasImageReference) {
        const imagePreferences = normalizeImagePreferences(
          preferences,
          { platforms: [nextCreation.targetPlatform || targetPlatform].filter(Boolean) },
          currentAccount || { platforms: [nextCreation.targetPlatform || targetPlatform].filter(Boolean) }
        );
        const creationState = {
          ...(nextCreation.creationState || {}),
          referenceNote: {},
          linkReference: null,
          linkText: "",
          useOriginalAsReference: false,
          imageCreationPreferences: imagePreferences,
          ratio: imagePreferences.ratio,
          creationWizardStep: 1,
          completedCreationWizardSteps: [0],
          creationWizardProgressByType: {
            ...(nextCreation.creationState?.creationWizardProgressByType || {}),
            image: { currentStep: 1, completedSteps: [0] },
          },
        };
        setCreation(normalizeCreationRecord({ ...nextCreation, creationState }));
        setActivePage("creation");
        addToast("已进入图文创作，AI 正在生成生图提示词");
        try {
          const job = await starxApi.createTopicPromptJob(currentAccountId, {
            topicId,
            ...imagePreferences,
          });
          const jobId = String(job?.id || "").trim();
          if (!jobId) throw new Error("图片 Prompt 计划任务创建失败：未返回任务 ID");
          upsertGenerationJob(job);
          setCreation((currentCreation) => {
            if (currentCreation.creationId !== nextCreation.creationId) return currentCreation;
            return normalizeCreationRecord({
              ...currentCreation,
              creationState: {
                ...(currentCreation.creationState || {}),
                imagePromptJobId: jobId,
                promptJobId: jobId,
                imagePromptPlanStartError: "",
                imageCreationPreferences: imagePreferences,
              },
            });
          });
        } catch (err) {
          const failureMessage = err.message || "自动生成生图提示词失败";
          setCreation((currentCreation) => {
            if (currentCreation.creationId !== nextCreation.creationId) return currentCreation;
            return normalizeCreationRecord({
              ...currentCreation,
              creationState: {
                ...(currentCreation.creationState || {}),
                imagePromptPlanStartError: failureMessage,
                imageCreationPreferences: imagePreferences,
              },
            });
          });
          addToast(`${failureMessage}，可在创作页面重试`, "warning");
        }
        return;
      }
      const extractedLinkReference = await starxApi.extractLinkReference(referenceNote.publicUrl, {
        accountId: currentAccountId,
        creationId: nextCreation.creationId,
      });
      const cleanReferenceTitle = stripHashtagsFromTitle(extractedLinkReference.title);
      const linkReference = { ...extractedLinkReference, title: cleanReferenceTitle };
      const images = (linkReference.images || [])
        .map((image) => ({ ...image, url: image?.url || image?.sourceUrl || "" }))
        .filter((image) => image.url)
        .slice(0, 8);
      if (!images.length) {
        throw new Error("参考爆款笔记未解析出原图，请检查笔记链接后重试");
      }
      const creationState = {
        ...(nextCreation.creationState || {}),
        referenceNote,
        linkReference: { ...linkReference, images },
        linkText: referenceNote.publicUrl,
        useOriginalAsReference: true,
        imageLinkPromptRows: [],
        showImageParseResult: true,
        ratio: "9:16",
        creationWizardStep: 0,
        completedCreationWizardSteps: [],
        creationWizardProgressByType: {
          ...(nextCreation.creationState?.creationWizardProgressByType || {}),
          image: { currentStep: 0, completedSteps: [] },
        },
      };
      setCreation(normalizeCreationRecord({
        ...nextCreation,
        content: {
          ...(nextCreation.content || {}),
          title: stripHashtagsFromTitle(nextCreation.content?.title || nextCreation.topicTitle || cleanReferenceTitle),
          body: nextCreation.content?.body || linkReference.description || "",
          hashtags: linkReference.hashtags || nextCreation.content?.hashtags || [],
        },
        creationState,
      }));
      setActivePage("creation");
      addToast("参考爆款解析完成，可确认素材后继续创作", "success");
    },
    [addToast, currentAccount, currentAccountId, upsertGenerationJob]
  );

  const reversePrompt = useCallback(
    async (imageSource, options = {}) => {
      if (!currentAccountId) return null;
      const { silent = false, ...context } = options;
      const source = typeof imageSource === "string"
        ? { imageUrl: imageSource, ...context }
        : imageSource;
      const result = await starxApi.reversePrompt(currentAccountId, source);
      if (!silent) addToast("提示词和发布文案反推完成", "success");
      return result;
    },
    [addToast, currentAccountId]
  );

  const savePromptTemplate = useCallback(
    async (payload) => {
      if (!currentAccountId) return null;
      const template = await starxApi.createPromptTemplate(currentAccountId, payload);
      setPromptTemplates((prev) => [template, ...prev]);
      addToast(`模板「${template.name}」已保存`, "success");
      return template;
    },
    [addToast, currentAccountId]
  );

  const deletePromptTemplate = useCallback(
    async (templateId) => {
      if (!currentAccountId) return;
      await starxApi.deletePromptTemplate(currentAccountId, templateId);
      setPromptTemplates((prev) => prev.filter((t) => t.id !== templateId));
      addToast("模板已删除", "success");
    },
    [addToast, currentAccountId]
  );

  const createCustomTag = useCallback(
    async (categoryId, payload) => {
      if (!currentAccountId) return null;
      const tag = await starxApi.createPromptTag(currentAccountId, categoryId, payload);
      addToast(`自定义标签「${tag.label}」已创建`, "success");
      return tag;
    },
    [addToast, currentAccountId]
  );

  const deleteCustomTag = useCallback(
    async (tagId) => {
      if (!currentAccountId) return;
      await starxApi.deletePromptTag(currentAccountId, tagId);
      addToast("自定义标签已删除", "success");
    },
    [addToast, currentAccountId]
  );

  const createCustomTagCategory = useCallback(
    async (label) => {
      if (!currentAccountId) return null;
      const category = await starxApi.createPromptTagCategory(currentAccountId, { label, sortOrder: 0 });
      addToast(`标签分类「${category.label}」已创建`, "success");
      return category;
    },
    [addToast, currentAccountId]
  );

  const deleteCustomTagCategory = useCallback(
    async (categoryId) => {
      if (!currentAccountId) return;
      await starxApi.deletePromptTagCategory(currentAccountId, categoryId);
      addToast("标签分类已删除", "success");
    },
    [addToast, currentAccountId]
  );

  const refreshPromptTags = useCallback(async () => {
    if (!currentAccountId) return;
    const tags = await starxApi.getPromptTags(currentAccountId).catch(() => []);
    setPromptTagCategories(tags);
  }, [currentAccountId]);

  const refreshVideoAnalysisJob = useCallback(
    async (jobId) => {
      if (!jobId) return null;
      const job = await starxApi.getVideoAnalysisJob(jobId);
      upsertVideoAnalysisJob(job);
      return job;
    },
    [upsertVideoAnalysisJob]
  );

  const createVideoAnalysisJob = useCallback(
    async (payload) => {
      const job = await starxApi.createVideoAnalysisJob({
        accountId: currentAccountId,
        creationId: creation.creationId || "",
        ...payload,
      });
      upsertVideoAnalysisJob(job);
      addToast("已开始 AI 解析视频");
      return job;
    },
    [addToast, creation.creationId, currentAccountId, upsertVideoAnalysisJob]
  );

  const extractLinkReference = useCallback(
    async (text, context = {}) => {
      const result = await starxApi.extractLinkReference(text, {
        accountId: currentAccountId,
        creationId: creation.creationId || "",
        ...context,
      });
      setExtractHistories(await starxApi.getExtractLinkHistory());
      addToast("链接内容已解析为参考输入", "success");
      return result;
    },
    [addToast, creation.creationId, currentAccountId]
  );

  // Jobs refresh on-demand when user clicks them — no polling needed.

  const addCanvasJob = useCallback((jobId) => {
    if (!jobId) return;
    setCanvasJobIds((prev) => addUniqueJobId(prev, jobId));
    setActiveCanvasJobId(jobId);
  }, []);

  const openGenerationCanvas = useCallback(
    (jobId) => {
      if (!jobId) {
        addToast("未找到可打开的图片任务", "warning");
        return;
      }
      setCanvasJobIds((prev) => addUniqueJobId(prev, jobId));
      setActiveCanvasJobId(jobId);
      setActivePage("canvas");
    },
    [addToast],
  );

  const closeGenerationCanvas = useCallback(() => {
    setActivePage("creation");
  }, []);

  const startBlankCreation = useCallback(() => {
    setCreation(createManualCreation(currentAccount));
    setActivePage("creation");
  }, [currentAccount]);

  const updateCreation = useCallback((patch) => {
    setCreation((prev) => normalizeCreationRecord({ ...prev, ...patch }));
  }, []);

  const saveCreationState = useCallback(
    async (creationState) => {
      if (!currentAccountId) return;
      const creationId = creation.creationId || "";
      if (!creationId) return;
      try {
        // Re-submit the creation with updated creationState so it persists to backend
        const current = creation;
        await starxApi.submitCreationTask(currentAccountId, creationId, {
          topicId: current.topicId || "",
          targetPlatform: current.targetPlatform || "小红书",
          type: current.type || "image",
          content: {
            ...current.content,
            imagePrompt: creationState.imagePrompt || current.content?.imagePrompt || "",
          },
          creationState: {
            ...(current.creationState || {}),
            ...creationState,
          },
          persistExtractAssets: false,
        });
      } catch { /* silent — don't block user on auto-save */ }
    },
    [currentAccountId, creation]
  );

  const createTask = useCallback(
    async (payload) => {
      if (!currentAccountId) return;
      const task = await starxApi.createTask(currentAccountId, payload);
      setTasks((prev) => [task, ...prev]);
      addToast("任务已创建，可在流程管理中查看", "success");
    },
    [addToast, currentAccountId]
  );

  const submitCreationToWorkflow = useCallback(
    async (payload) => {
      if (!currentAccountId) return null;
      const creationId = creation.creationId || `manual_${Date.now()}`;
      const response = await starxApi.submitCreationTask(currentAccountId, creationId, payload);
      const { material, assetPersistence, ...task } = response;
      if (material) setMaterials((prev) => [material, ...prev.filter((item) => item.id !== material.id)]);
      setCreation((prev) => normalizeCreationRecord({
        ...prev,
        creationId,
        topicId: payload.topicId || prev.topicId || "",
        topicTitle: prev.topicTitle || payload.content.title || "手动新建素材",
        type: payload.type,
        targetPlatform: payload.targetPlatform,
        content: payload.content,
        creationState: {
          ...defaultCreationState,
          ...(payload.creationState || {}),
          assetPersistence: assetPersistence || payload.creationState?.assetPersistence || null,
        },
      }));
      setTasks((prev) => {
        const exists = prev.some((item) => item.id === task.id);
        return exists ? prev.map((item) => (item.id === task.id ? task : item)) : [task, ...prev];
      });
      const historyIds = [assetPersistence?.historyId || payload.extractHistoryId].filter(Boolean);
      if (historyIds.length) {
        await starxApi.bindExtractHistories({ creationId, taskId: task.id, historyIds });
        setExtractHistories(await starxApi.getExtractLinkHistory());
      }
      addToast(
        assetPersistence ? "内容已保存，资源正在后台转存" : material ? "脚本素材和流程已保存" : "内容已保存进流程管理",
        "success"
      );
      return task;
    },
    [addToast, creation.creationId, currentAccountId]
  );

  const publishCreation = useCallback(
    async (creationId, payload) => {
      if (!currentAccountId || !creationId) return null;
      const requestAccountId = currentAccountId;
      const requestToken = workflowPublishRequestGateRef.current.begin(`publish:${creationId}`, requestAccountId);
      const result = await starxApi.publishCreation(requestAccountId, creationId, payload);
      const recorded = { ...result, recordedAt: new Date().toISOString() };
      if (!workflowPublishRequestGateRef.current.isCurrent(requestToken, currentAccountIdRef.current)) return result;
      setPublishStates((prev) => ({ ...prev, [creationId]: recorded }));
      setCreation((prev) => prev.creationId === creationId ? normalizeCreationRecord({
        ...prev,
        creationState: {
          ...(prev.creationState || {}),
          publish: recorded,
          publishHistory: [...(prev.creationState?.publishHistory || []), recorded].slice(-50),
        },
      }) : prev);
      addToast(`发布任务已提交 · ${result.status || "queued"}`, "success");
      return result;
    },
    [addToast, currentAccountId]
  );

  const uploadPublishVideo = useCallback(
    async (creationId, taskId, file) => {
      if (!currentAccountId || !creationId || !taskId || !file) return null;
      return starxApi.uploadPublishVideo(currentAccountId, creationId, taskId, file);
    },
    [currentAccountId]
  );

  const uploadPublishImages = useCallback(
    async (creationId, taskId, files) => {
      if (!currentAccountId || !creationId || !taskId || !files?.length) return [];
      return starxApi.uploadPublishImages(currentAccountId, creationId, taskId, files);
    },
    [currentAccountId]
  );

  const refreshPublishStatus = useCallback(
    async (creationId, options = {}) => {
      if (!currentAccountId || !creationId) return null;
      const requestAccountId = currentAccountId;
      const requestToken = workflowPublishRequestGateRef.current.begin(`publish:${creationId}`, requestAccountId);
      const result = await starxApi.getPublishStatus(requestAccountId, creationId);
      const recorded = { ...result, recordedAt: new Date().toISOString() };
      if (!workflowPublishRequestGateRef.current.isCurrent(requestToken, currentAccountIdRef.current)) return result;
      setPublishStates((prev) => ({ ...prev, [creationId]: recorded }));
      setCreation((prev) => prev.creationId === creationId ? normalizeCreationRecord({
        ...prev,
        creationState: {
          ...(prev.creationState || {}),
          publish: recorded,
          publishHistory: [...(prev.creationState?.publishHistory || []), recorded].slice(-50),
        },
      }) : prev);
      if (!options.silent) addToast(`发布状态：${result.status || "unknown"}`, "success");
      return result;
    },
    [addToast, currentAccountId]
  );

  const loadTaskCreation = useCallback(
    async (task) => {
      if (!currentAccountId || !task?.creationId) {
        throw new Error("这个流程没有关联创作内容");
      }
      const requestAccountId = currentAccountId;
      const requestToken = workflowPublishRequestGateRef.current.begin("load-task-creation", requestAccountId);
      const savedCreation = await starxApi.getCreation(requestAccountId, task.creationId);
      if (!workflowPublishRequestGateRef.current.isCurrent(requestToken, currentAccountIdRef.current)) return null;
      const persistedPublishState = savedCreation.creationState?.publish;
      setPublishStates((prev) => {
        if (persistedPublishState) {
          return { ...prev, [task.creationId]: persistedPublishState };
        }
        if (!Object.prototype.hasOwnProperty.call(prev, task.creationId)) return prev;
        const next = { ...prev };
        delete next[task.creationId];
        return next;
      });
      return savedCreation;
    },
    [currentAccountId]
  );

  const openTaskCreation = useCallback(
    async (task) => {
      if (!currentAccountId || !task?.creationId) {
        addToast("这个流程没有关联创作内容", "warning");
        return;
      }
      const [savedCreation, boundHistories] = await Promise.all([
        starxApi.getCreation(currentAccountId, task.creationId),
        starxApi.getExtractLinkHistory({ taskId: task.id }),
      ]);
      const state = savedCreation.creationState || {};
      const generationJobIds = [
        state.promptJobId,
        state.activeImageJobId,
        state.scriptRewriteJobId,
        state.activeVideoScriptJobId,
        state.activeDigitalHumanWorkflowId,
        ...(state.digitalHumanWorkflowIds || []),
        ...(state.imageJobIds || []),
      ].filter(Boolean);
      const loadedJobs = await Promise.all(
        [...new Set(generationJobIds)].map((jobId) =>
          starxApi.getGenerationJob(currentAccountId, jobId).catch(() => null)
        )
      );
      loadedJobs.filter(Boolean).forEach(upsertGenerationJob);
      if (state.videoAnalysisJobId) {
        const videoJob = await starxApi.getVideoAnalysisJob(state.videoAnalysisJobId).catch(() => null);
        if (videoJob) upsertVideoAnalysisJob(videoJob);
      }
      setExtractHistories((prev) => {
        const boundIds = new Set(boundHistories.map((item) => item.id));
        return [...boundHistories, ...prev.filter((item) => !boundIds.has(item.id))];
      });
      setCreation(normalizeCreationRecord({ ...savedCreation, sourceTaskId: task.id }));
      setActivePage("creation");
      addToast("已打开关联创作内容");
    },
    [addToast, currentAccountId, upsertGenerationJob, upsertVideoAnalysisJob]
  );

  const moveTask = useCallback(
    async (taskId, status) => {
      if (!currentAccountId) return;
      const updated = await starxApi.updateTaskStatus(currentAccountId, taskId, status);
      setTasks((prev) => prev.map((task) => (task.id === taskId ? updated : task)));
      addToast("任务状态已更新");
    },
    [addToast, currentAccountId]
  );

  const duplicateTask = useCallback(
    async (taskId) => {
      if (!currentAccountId || !taskId) return null;
      const duplicate = await starxApi.duplicateTask(currentAccountId, taskId);
      setTasks((prev) => [duplicate, ...prev.filter((task) => task.id !== duplicate.id)]);
      addToast("流程已复制", "success");
      return duplicate;
    },
    [addToast, currentAccountId]
  );

  const saveMaterial = useCallback(
    async (payload) => {
      if (!currentAccountId) return;
      const material = await starxApi.createMaterial(currentAccountId, payload);
      setMaterials((prev) => [material, ...prev]);
      addToast("所有内容已保存至个人素材库", "success");
    },
    [addToast, currentAccountId]
  );

  const deleteMaterial = useCallback(
    (materialId) => {
      setMaterials((prev) => prev.filter((material) => material.id !== materialId));
      addToast("素材已删除");
    },
    [addToast]
  );

  const deleteTask = useCallback(
    (taskId) => {
      setTasks((prev) => prev.filter((task) => task.id !== taskId));
      addToast("任务已删除");
    },
    [addToast]
  );

  const createAccount = useCallback(
    async (payload) => {
      const account = normalizeAccountRecord(await starxApi.createAccount(payload));
      setAccounts((prev) => [account, ...prev].slice(0, accountPage.pageSize));
      setAccountPage((prev) => ({ ...prev, page: 1, total: prev.total + 1, keyword: "", platform: "" }));
      setCurrentAccountRecord(account);
      await switchAccount(account.id);
      setShowAddAccountModal(false);
      addToast(`新账号「${account.name}」已创建，正在生成报告…`);
      setActivePage("report");
      void reportRefreshCoordinatorRef.current.refresh(account.id, false);
      return account;
    },
    [accountPage.pageSize, addToast, switchAccount]
  );

  const openAccountModal = useCallback((account = null) => {
    setEditingAccount(account);
    setShowAddAccountModal(true);
  }, []);

  const closeAccountModal = useCallback(() => {
    setEditingAccount(null);
    setShowAddAccountModal(false);
  }, []);

  const updateAccount = useCallback(
    async (accountId, payload) => {
      const account = normalizeAccountRecord(await starxApi.updateAccount(accountId, payload));
      setAccounts((prev) => prev.map((item) => (item.id === account.id ? account : item)));
      if (account.id === currentAccountId) {
        setCurrentAccountRecord(account);
        setCurrentAccountId(account.id);
        setDashboard(null);
        void starxApi.getDashboard(account.id)
          .then((dashboardData) => {
            if (currentAccountIdRef.current === account.id) {
              setDashboard(dashboardData);
            }
          })
          .catch((error) => {
            if (currentAccountIdRef.current === account.id) {
              addToast(error?.message || "账号已保存，但数据看板状态刷新失败", "warning");
            }
          });
      }
      closeAccountModal();
      addToast(`账号「${account.name}」已更新`, "success");
      return account;
    },
    [addToast, closeAccountModal, currentAccountId]
  );

  const deleteAccount = useCallback(
    async (accountId) => {
      const target = accounts.find((account) => account.id === accountId);
      await starxApi.deleteAccount(accountId);
      const nextTotal = Math.max(0, accountPage.total - 1);
      const nextPage = Math.min(accountPage.page, Math.max(1, Math.ceil(nextTotal / accountPage.pageSize)));
      const normalizedPage = await loadAccountsPage({
        page: nextPage,
        pageSize: accountPage.pageSize,
        keyword: accountPage.keyword,
        platform: accountPage.platform,
      });
      const nextAccounts = normalizedPage.items;

      if (accountId === currentAccountId) {
        workflowPublishRequestGateRef.current.reset();
        setPublishStates({});
        const nextCurrent = nextAccounts[0] || null;
        if (nextCurrent) {
          invalidateReportLifecycle({ clearState: true });
          stopTopicRefreshPolling();
          currentAccountIdRef.current = nextCurrent.id;
          setTopicRefreshWorkflow(null);
          setIsRefreshingTopics(false);
          setCurrentAccountId(nextCurrent.id);
          setCurrentAccountRecord(nextCurrent);
          setCanvasJobIds([]);
          setActiveCanvasJobId("");
          await loadAccountBundle(nextCurrent.id);
        } else {
          invalidateReportLifecycle({ clearState: true });
          currentAccountIdRef.current = "";
          setCurrentAccountRecord(null);
          setCurrentAccountId("");
          setTopics([]);
          setFavoriteTopics([]);
          setTopicRefreshWorkflow(null);
          setIsRefreshingTopics(false);
          stopTopicRefreshPolling();
          setTasks([]);
          setMaterials([]);
          setDigitalHumanProfiles([]);
          setGenerationJobs([]);
          setVideoAnalysisJobs([]);
          setExtractHistories([]);
          setCanvasJobIds([]);
          setActiveCanvasJobId("");
          setDashboard(null);
          setReport(null);
          setSummary([]);
          setCreation(defaultCreation);
          setActivePage("account");
        }
      } else {
        setSummary(await starxApi.getSummary());
      }

      addToast(`账号「${target?.name || "已选账号"}」已删除`, "success");
    },
    [
      accountPage,
      accounts,
      addToast,
      currentAccountId,
      loadAccountBundle,
      loadAccountsPage,
      invalidateReportLifecycle,
      stopTopicRefreshPolling,
    ]
  );

  const login = useCallback(
    async (payload) => {
      setLoading(true);
      setError("");
      try {
        const result = await starxApi.login(payload);
        setAccessToken(result.accessToken);
        await bootstrapWorkspace(result.user);
      } catch (err) {
        setError(err.message || "登录失败");
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [bootstrapWorkspace]
  );

  const logout = useCallback(() => {
    setAccessToken("");
    stopTopicRefreshPolling();
    invalidateReportLifecycle({ clearState: true });
    currentAccountIdRef.current = "";
    setCurrentUser(null);
    setAccounts([]);
    setAccountPage({ page: 1, pageSize: 4, total: 0, keyword: "", platform: "" });
    setCurrentAccountRecord(null);
    setKnowledgeBases([]);
    setKnowledgeBaseList([]);
    setKnowledgeBasePage({ page: 1, pageSize: 12, total: 0, keyword: "" });
    setCurrentAccountId("");
    setTopics([]);
    setFavoriteTopics([]);
    setTopicRefreshWorkflow(null);
    setIsRefreshingTopics(false);
    setTasks([]);
    setMaterials([]);
    setDigitalHumanProfiles([]);
    setGenerationJobs([]);
    setVideoAnalysisJobs([]);
    setExtractHistories([]);
    setCanvasJobIds([]);
    setActiveCanvasJobId("");
    setDashboard(null);
    setSummary([]);
    setReport(null);
    setReportWorkflow(null);
    setIsGeneratingReport(false);
    setCreation(defaultCreation);
    workflowPublishRequestGateRef.current.reset();
    setPublishStates({});
    setActivePage("account");
    setEditingAccount(null);
    setShowAddAccountModal(false);
    setEditingKnowledgeBase(null);
    setShowKnowledgeBaseModal(false);
    knowledgeBaseCreatedCallbackRef.current = null;
    setError("");
  }, [invalidateReportLifecycle, stopTopicRefreshPolling]);

  useEffect(() => {
    const handleSessionExpired = () => {
      logout();
      setError(SESSION_EXPIRED_MESSAGE);
    };

    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, handleSessionExpired);
    return () => window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, handleSessionExpired);
  }, [logout]);

  const saveReportSection = useCallback(
    async (sectionKey, content) => {
      if (!currentAccountId) return;
      const nextReport = await starxApi.updateReportSection(currentAccountId, sectionKey, content);
      setReport(nextReport);
      addToast("内容已保存", "success");
    },
    [addToast, currentAccountId]
  );

  const openKnowledgeBaseModal = useCallback((knowledgeBase = null, options = {}) => {
    if (typeof options.onCreated === "function") {
      knowledgeBaseCreatedCallbackRef.current = options.onCreated;
    }
    setEditingKnowledgeBase(knowledgeBase);
    setShowKnowledgeBaseModal(true);
  }, []);

  const closeKnowledgeBaseModal = useCallback(() => {
    setEditingKnowledgeBase(null);
    setShowKnowledgeBaseModal(false);
    knowledgeBaseCreatedCallbackRef.current = null;
  }, []);

  const createKnowledgeBase = useCallback(
    async (payload) => {
      const knowledgeBase = normalizeKnowledgeBaseRecord(await starxApi.createKnowledgeBase(payload));
      setKnowledgeBases((prev) => [knowledgeBase, ...prev]);
      setKnowledgeBaseList((prev) => [knowledgeBase, ...prev].slice(0, knowledgeBasePage.pageSize));
      setKnowledgeBasePage((prev) => ({ ...prev, page: 1, total: prev.total + 1 }));
      const onCreated = knowledgeBaseCreatedCallbackRef.current;
      closeKnowledgeBaseModal();
      onCreated?.(knowledgeBase);
      addToast(`知识库「${knowledgeBase.name}」已创建`, "success");
      return knowledgeBase;
    },
    [addToast, closeKnowledgeBaseModal, knowledgeBasePage.pageSize]
  );

  const uploadKnowledgeBaseImages = useCallback(
    (files) => starxApi.uploadKnowledgeBaseImages(files),
    []
  );

  const updateKnowledgeBase = useCallback(
    async (knowledgeBaseId, payload) => {
      const knowledgeBase = normalizeKnowledgeBaseRecord(
        await starxApi.updateKnowledgeBase(knowledgeBaseId, payload)
      );
      setKnowledgeBases((prev) =>
        prev.map((item) => (item.id === knowledgeBase.id ? knowledgeBase : item))
      );
      setKnowledgeBaseList((prev) =>
        prev.map((item) => (item.id === knowledgeBase.id ? knowledgeBase : item))
      );
      setAccounts((prev) =>
        prev.map((account) =>
          account.knowledgeBaseSummary?.id === knowledgeBase.id
            ? {
                ...account,
                knowledgeBaseSummary: {
                  ...(account.knowledgeBaseSummary || {}),
                  id: knowledgeBase.id,
                  name: knowledgeBase.name,
                  productName: knowledgeBase.productName,
                },
              }
            : account
        )
      );
      closeKnowledgeBaseModal();
      addToast(`知识库「${knowledgeBase.name}」已更新`, "success");
      return knowledgeBase;
    },
    [addToast, closeKnowledgeBaseModal]
  );

  const deleteKnowledgeBase = useCallback(
    async (knowledgeBase) => {
      if (!knowledgeBase?.id) return;
      try {
        await starxApi.deleteKnowledgeBase(knowledgeBase.id);
        setKnowledgeBases((prev) => prev.filter((item) => item.id !== knowledgeBase.id));
        setKnowledgeBaseList((prev) => prev.filter((item) => item.id !== knowledgeBase.id));
        setKnowledgeBasePage((prev) => ({ ...prev, total: Math.max(0, prev.total - 1) }));
        addToast(`知识库「${knowledgeBase.name || "未命名知识库"}」已删除`, "success");
      } catch (err) {
        addToast("删除失败，请先解绑正在使用该知识库的账号", "warning");
      }
    },
    [addToast]
  );

  return {
    currentUser,
    accounts,
    accountPage,
    accountLoading,
    knowledgeBases,
    knowledgeBaseList,
    knowledgeBasePage,
    knowledgeBaseLoading,
    currentAccount,
    currentAccountId,
    topics,
    favoriteTopics,
    topicRefreshWorkflow,
    isRefreshingTopics,
    tasks,
    materials,
    digitalHumanProfiles,
    generationJobs,
    videoAnalysisJobs,
    extractHistories,
    promptTagCategories,
    promptTemplates,
    dashboard,
    summary,
    report,
    reportWorkflow,
    reportSectionWorkflows,
    isGeneratingReport,
    creation,
    publishStates,
    canvasJobIds,
    activeCanvasJobId,
    activePage,
    loading,
    error,
    toasts,
    showAddAccountModal,
    editingAccount,
    showKnowledgeBaseModal,
    editingKnowledgeBase,
    setActivePage,
    setShowAddAccountModal,
    setShowKnowledgeBaseModal,
    addToast,
    login,
    logout,
    switchAccount,
    refreshTopics,
    refreshAccountReport,
    addReportSimilarAccount,
    resolveReportSimilarAccount,
    deleteReportSimilarAccount,
    addCompetitorAccount,
    replaceSingleTopic,
    favoriteTopic,
    deleteFavoriteTopic,
    generateCreation,
    createPromptJob,
    createTopicPromptJob,
    createImageJob,
    createScriptRewriteJob,
    createVideoScriptJob,
    refreshDigitalHumanProfiles,
    createDigitalHumanProfile,
    disableDigitalHumanProfile,
    createDigitalHumanVideo,
    createVideoAnalysisJob,
    refreshVideoAnalysisJob,
    extractLinkReference,
    refreshGenerationJob,
    addCanvasJob,
    openGenerationCanvas,
    closeGenerationCanvas,
    startBlankCreation,
    updateCreation,
    saveCreationState,
    createTask,
    submitCreationToWorkflow,
    uploadPublishImages,
    uploadPublishVideo,
    publishCreation,
    refreshPublishStatus,
    loadTaskCreation,
    openTaskCreation,
    moveTask,
    duplicateTask,
    saveMaterial,
    deleteMaterial,
    deleteTask,
    createAccount,
    updateAccount,
    openAccountModal,
    closeAccountModal,
    deleteAccount,
    openKnowledgeBaseModal,
    closeKnowledgeBaseModal,
    refreshKnowledgeBaseOptions,
    loadKnowledgeBasesPage,
    loadAccountsPage,
    createKnowledgeBase,
    uploadKnowledgeBaseImages,
    updateKnowledgeBase,
    deleteKnowledgeBase,
    saveReportSection,
    reversePrompt,
    savePromptTemplate,
    deletePromptTemplate,
    createCustomTag,
    deleteCustomTag,
    createCustomTagCategory,
    deleteCustomTagCategory,
    refreshPromptTags,
  };
}
