const REPORT_STAGE_LABELS = {
  pending: "等待开始",
  context_loading: "读取账号档案",
  dashboard_refresh: "生成账号数据看板",
  keyword_planning: "规划行业关键词",
  creator_crawling: "采集当前账号主页公开信息",
  keyword_crawling: "采集行业公开内容",
  evidence_normalization: "整理公开内容证据",
  report_analysis: "生成行业分析",
  report_persistence: "保存账号报告",
  completed: "报告已完成",
  failed: "报告生成失败",
};

const LEGACY_REPORT_FIELDS = ["competitors", "prohibitedWords", "targetUsers", "hotContent"];
const STRUCTURED_REPORT_FIELDS = ["similarAccounts", "complianceRules", "hotContents"];
const VISIBLE_REPORT_SECTION_KEYS = [
  "similarAccounts",
  "complianceRules",
  "targetUserProfile",
  "hotContents",
];
const PUBLIC_METRIC_KEYS = new Set([
  "fansCount",
  "worksCount",
  "interactionCount",
  "hitContentCount",
  "likedCount",
  "collectedCount",
  "commentCount",
  "shareCount",
  "engagementScore",
]);
const CRAWL_ACTIVITY_TEXT_FIELDS = [
  "stage",
  "status",
  "platform",
  "platformName",
  "action",
  "message",
  "subject",
  "occurredAt",
];
const CRAWL_ACTIVITY_COUNT_FIELDS = ["sequence", "contentCount", "creatorCount", "commentCount"];
const PLATFORM_SUMMARY_TEXT_FIELDS = [
  "platform",
  "platformName",
  "status",
  "failureCode",
  "failureMessage",
  "noticeCode",
  "noticeMessage",
];
const PLATFORM_SUMMARY_COUNT_FIELDS = ["contentCount", "creatorCount", "commentCount"];
const CRAWL_COUNT_LABELS = [
  ["contentCount", "内容"],
  ["creatorCount", "账号"],
  ["commentCount", "评论"],
];
const CRAWL_PLATFORM_STATUS_LABELS = {
  pending: "等待中",
  running: "采集中",
  completed: "已完成",
  partial: "部分成功",
  failed: "采集失败",
  skipped: "已跳过",
};
const LEGACY_CRAWL_MESSAGES = {
  "开始博主主页采集": "开始采集当前账号主页公开信息",
  "发现公开博主": "发现公开账号",
};
const CREATOR_URL_NOTICE = {
  message: "当前账号主页链接无效，已跳过主页公开信息采集",
  suggestion: "请在账号档案中填写该平台真实、完整的当前账号主页链接",
};

const PLATFORM_DISPLAY_MAP = {
  xhs: { label: "小红书", icon: "📕" },
  xiaohongshu: { label: "小红书", icon: "📕" },
  "小红书": { label: "小红书", icon: "📕" },
  dy: { label: "抖音", icon: "🎵" },
  douyin: { label: "抖音", icon: "🎵" },
  "抖音": { label: "抖音", icon: "🎵" },
  ks: { label: "快手", icon: "⚡" },
  kuaishou: { label: "快手", icon: "⚡" },
  "快手": { label: "快手", icon: "⚡" },
  sph: { label: "视频号", icon: "💬" },
  channels: { label: "视频号", icon: "💬" },
  wechat_channels: { label: "视频号", icon: "💬" },
  "视频号": { label: "视频号", icon: "💬" },
  bilibili: { label: "B站", icon: "📺" },
  bili: { label: "B站", icon: "📺" },
  "b站": { label: "B站", icon: "📺" },
  "B站": { label: "B站", icon: "📺" },
  weibo: { label: "微博", icon: "📢" },
  "微博": { label: "微博", icon: "📢" },
};

export function resolvePlatformDisplay(platform) {
  const raw = String(platform || "").trim();
  if (!raw) return { label: "未知平台", icon: "📱" };
  const mapped = PLATFORM_DISPLAY_MAP[raw] || PLATFORM_DISPLAY_MAP[raw.toLowerCase()];
  if (mapped) return mapped;
  return { label: raw, icon: "📱" };
}

export function formatPlatformLabel(platform) {
  const { icon, label } = resolvePlatformDisplay(platform);
  return `${icon} ${label}`;
}

const SEEDED_LEGACY_PLACEHOLDERS = {
  competitors: /^基于定位“[\s\S]*”，系统会结合目标平台生成竞对分析。$/,
  prohibitedWords: /^系统会按创作目标平台切换违禁词规则。$/,
  targetUsers: /^目标用户聚焦于对“[\s\S]*”感兴趣的人群。$/,
  hotContent: /^系统将在首轮创作后补全爆款内容解析。$/,
};

export function asArray(value) {
  return Array.isArray(value) ? value : [];
}

export function formatMetric(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "0";
  const rounded = Math.round(number);
  if (rounded >= 100000000) return `${trimDecimal(rounded / 100000000)}亿`;
  if (rounded >= 10000) return `${trimDecimal(rounded / 10000)}万`;
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(rounded);
}

function trimDecimal(value) {
  return value.toFixed(1).replace(/\.0$/, "");
}

export function getReportStageLabel(stage) {
  return REPORT_STAGE_LABELS[String(stage || "")] || "生成账号报告";
}

export function hasExistingReport(report) {
  if (!report || typeof report !== "object") return false;
  if (Number(report.reportVersion || 0) > 0) return true;
  const isUnpersistedSeed = !report.generatedAt;
  if (LEGACY_REPORT_FIELDS.some((field) => {
    const value = String(report[field] || "").trim();
    if (!value) return false;
    return !(isUnpersistedSeed && SEEDED_LEGACY_PLACEHOLDERS[field]?.test(value));
  })) return true;
  if (STRUCTURED_REPORT_FIELDS.some((field) => asArray(report[field]).length > 0)) return true;
  return Boolean(
    report.targetUserProfile?.summary
    || asArray(report.targetUserProfile?.categories).length
  );
}

export function mergeAccountReportPreview(report, workflow) {
  const base = report && typeof report === "object" && !Array.isArray(report) ? report : {};
  const isActive = ["pending", "running"].includes(workflow?.status);
  const isCompletedWithoutPublishedReport = workflow?.status === "completed"
    && !hasExistingReport(base);
  if (!isActive && !isCompletedWithoutPublishedReport) return base;
  const preview = workflow?.resultPayload?.reportPreview;
  if (!preview || typeof preview !== "object" || Array.isArray(preview)) return base;
  return { ...base, ...preview };
}

export function shouldShowReportSkeleton(report, workflow) {
  const hasPreviewSection = asArray(workflow?.resultPayload?.reportSectionsCompleted).length > 0;
  return ["pending", "running"].includes(workflow?.status)
    && !hasExistingReport(mergeAccountReportPreview(report, workflow))
    && !hasPreviewSection;
}

export function normalizeReportProgress(value) {
  const progress = Number(value);
  if (!Number.isFinite(progress)) return 0;
  return Math.min(100, Math.max(0, progress));
}

function normalizeCrawlRecord(value, textFields, countFields) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const normalized = {};
  textFields.forEach((field) => {
    if (typeof value[field] === "string") normalized[field] = value[field];
  });
  countFields.forEach((field) => {
    const number = Number(value[field]);
    if (Number.isFinite(number)) normalized[field] = number;
  });
  return normalized;
}

function normalizeCrawlActivity(value) {
  const activity = normalizeCrawlRecord(
    value,
    CRAWL_ACTIVITY_TEXT_FIELDS,
    CRAWL_ACTIVITY_COUNT_FIELDS,
  );
  if (!activity) return null;
  if (LEGACY_CRAWL_MESSAGES[activity.message]) {
    activity.message = LEGACY_CRAWL_MESSAGES[activity.message];
  }
  if (typeof value.contentTitle === "string") activity.contentTitle = value.contentTitle.slice(0, 60);
  return activity;
}

function normalizePlatformSummary(value) {
  const summary = normalizeCrawlRecord(
    value,
    PLATFORM_SUMMARY_TEXT_FIELDS,
    PLATFORM_SUMMARY_COUNT_FIELDS,
  );
  if (!summary) return null;
  const backendSuggestion = typeof value.failureSuggestion === "string"
    ? value.failureSuggestion.trim()
    : "";
  const legacySuggestion = typeof value.suggestion === "string"
    ? value.suggestion.trim()
    : "";
  const suggestion = backendSuggestion || legacySuggestion;
  if (suggestion) summary.suggestion = suggestion;
  const noticeSuggestion = typeof value.noticeSuggestion === "string"
    ? value.noticeSuggestion.trim()
    : "";
  if (noticeSuggestion) summary.noticeSuggestion = noticeSuggestion;
  if (summary.noticeCode === "creator_url_invalid") {
    summary.noticeMessage = CREATOR_URL_NOTICE.message;
    summary.noticeSuggestion = CREATOR_URL_NOTICE.suggestion;
  }
  return summary;
}

export function normalizeCrawlProgress(workflow) {
  const raw = workflow?.resultPayload?.crawlProgress;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { current: null, activities: [], platformSummaries: [] };
  }

  const current = normalizeCrawlActivity(raw.current);
  const activities = asArray(raw.activities)
    .map(normalizeCrawlActivity)
    .filter(Boolean)
    .sort((left, right) => Number(right.sequence || 0) - Number(left.sequence || 0))
    .slice(0, 5);
  const platformSummaries = asArray(raw.platformSummaries)
    .map(normalizePlatformSummary)
    .filter(Boolean);

  return { current, activities, platformSummaries };
}

export function normalizeCrawlActivityFeed(workflow) {
  const raw = workflow?.resultPayload?.crawlProgress;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
  return asArray(raw.activities)
    .map(normalizeCrawlActivity)
    .filter(Boolean)
    .sort((left, right) => Number(left.sequence || 0) - Number(right.sequence || 0))
    .slice(-30);
}

export function createCrawlActivityDisplay(activity) {
  const value = activity && typeof activity === "object" && !Array.isArray(activity) ? activity : {};
  const message = typeof value.message === "string" && value.message ? value.message : "采集状态更新";
  const contextParts = [value.platformName, value.subject, value.contentTitle]
    .filter((item) => typeof item === "string" && item);
  const summaryParts = [value.platformName, message, value.subject, value.contentTitle]
    .filter((item) => typeof item === "string" && item);
  const counts = CRAWL_COUNT_LABELS.flatMap(([key, label]) => (
    Number.isSafeInteger(value[key]) && value[key] > 0
      ? [{ key, label, value: value[key] }]
      : []
  ));
  return {
    message,
    context: contextParts.join(" · "),
    summary: summaryParts.join(" · "),
    counts,
  };
}

export function getCrawlPlatformStatusLabel(status) {
  return CRAWL_PLATFORM_STATUS_LABELS[String(status || "")] || CRAWL_PLATFORM_STATUS_LABELS.pending;
}

export function createAccountReportViewModel(report, workflow) {
  const effectiveReport = mergeAccountReportPreview(report, workflow);
  const completedPreviewSections = asArray(workflow?.resultPayload?.reportSectionsCompleted);
  const visibleCompletedSections = VISIBLE_REPORT_SECTION_KEYS.filter((key) => (
    completedPreviewSections.includes(key)
  ));
  const hasPublishedReport = hasExistingReport(report);
  const hasPreviewSection = ["pending", "running", "completed"].includes(workflow?.status)
    && completedPreviewSections.length > 0;
  const hasReport = hasExistingReport(effectiveReport) || hasPreviewSection;
  const isActive = ["pending", "running"].includes(workflow?.status);
  const isFailed = workflow?.status === "failed";
  const showSkeleton = isActive && !hasReport;
  const rawSourceMeta = effectiveReport?.sourceMeta && typeof effectiveReport.sourceMeta === "object" ? effectiveReport.sourceMeta : {};
  const sampleCount = Number(rawSourceMeta.sampleCount);
  const withSafeProfileUrl = (creator) => ({
    ...creator,
    safeProfileUrl: isSafeHttpUrl(creator?.profileUrl) ? creator.profileUrl : "",
  });
  return {
    report: effectiveReport,
    state: showSkeleton ? "skeleton" : hasReport ? "content" : isFailed ? "failed" : "empty",
    hasReport,
    hasPublishedReport,
    isActive,
    isFailed,
    completedSections: completedPreviewSections,
    visibleCompletedSections,
    visibleSectionsTotal: VISIBLE_REPORT_SECTION_KEYS.length,
    progress: normalizeReportProgress(workflow?.progress),
    stageLabel: getReportStageLabel(workflow?.currentStage),
    crawlProgress: normalizeCrawlProgress(workflow),
    sourceMeta: {
      ...rawSourceMeta,
      sampleCount: Number.isFinite(sampleCount) && sampleCount >= 0 ? sampleCount : 0,
      keywords: asArray(rawSourceMeta.keywords),
      failedPlatforms: asArray(rawSourceMeta.failedPlatforms),
      unsupportedPlatforms: asArray(rawSourceMeta.unsupportedPlatforms),
    },
    hotContents: asArray(effectiveReport?.hotContents).map((content) => ({
      ...content,
      safeUrl: isSafeHttpUrl(content?.publicUrl) ? content.publicUrl : "",
      safeCoverUrl: isSafeHttpUrl(content?.coverUrl) ? content.coverUrl : "",
    })),
    similarAccounts: asArray(effectiveReport?.similarAccounts).map(withSafeProfileUrl),
  };
}

export function isSafeHttpUrl(value) {
  try {
    const parsed = new URL(String(value || ""));
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export function formatReportDate(value) {
  if (!value) return "尚未生成";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** Debug helper: print backend hotContents payload for 爆款笔记参考. */
export function logHotContentsBackendData(source, reportLike, extra = {}) {
  const hotContents = asArray(reportLike?.hotContents);
  console.log("[爆款笔记参考] 后端数据", {
    source,
    count: hotContents.length,
    hotContent: reportLike?.hotContent ?? null,
    hotContents,
    ...extra,
  });
}

function toMetricNumber(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : NaN;
  if (typeof value === "string" && value.trim() !== "") {
    const number = Number(value);
    return Number.isFinite(number) ? number : NaN;
  }
  return NaN;
}

export function metricEntries(metrics) {
  if (!metrics || typeof metrics !== "object" || Array.isArray(metrics)) return [];
  return Object.entries(metrics)
    .map(([key, value]) => [key, toMetricNumber(value)])
    .filter(([key, value]) => PUBLIC_METRIC_KEYS.has(key) && Number.isFinite(value))
    .slice(0, 6);
}

export function metricLabel(key) {
  return {
    fansCount: "粉丝",
    worksCount: "作品",
    interactionCount: "互动",
    hitContentCount: "爆款",
    likedCount: "点赞",
    collectedCount: "收藏",
    commentCount: "评论",
    shareCount: "分享",
    engagementScore: "互动评分",
  }[key] || String(key || "指标");
}

export function metricIcon(key) {
  return {
    likedCount: "♥",
    collectedCount: "★",
    commentCount: "💬",
    shareCount: "↗",
    fansCount: "👤",
    worksCount: "▣",
    interactionCount: "⚡",
    hitContentCount: "🔥",
    engagementScore: "✦",
  }[key] || null;
}
