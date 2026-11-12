import assert from "node:assert/strict";
import test from "node:test";

import {
  createCrawlActivityDisplay,
  createAccountReportViewModel,
  formatMetric,
  formatPlatformLabel,
  getCrawlPlatformStatusLabel,
  getReportStageLabel,
  hasExistingReport,
  isSafeHttpUrl,
  mergeAccountReportPreview,
  metricEntries,
  normalizeCrawlActivityFeed,
  normalizeCrawlProgress,
  normalizeReportProgress,
  resolvePlatformDisplay,
  shouldShowReportSkeleton,
} from "./accountReport.js";

test("platform codes render as readable Chinese labels with icons", () => {
  assert.deepEqual(resolvePlatformDisplay("xhs"), { label: "小红书", icon: "📕" });
  assert.deepEqual(resolvePlatformDisplay("douyin"), { label: "抖音", icon: "🎵" });
  assert.equal(formatPlatformLabel("xhs"), "📕 小红书");
  assert.equal(formatPlatformLabel(""), "📱 未知平台");
});

test("crawl activity display combines safe context and keeps only useful cumulative counts", () => {
  const display = createCrawlActivityDisplay({
    platformName: "小红书",
    message: "开始关键词采集",
    subject: "防晒",
    contentTitle: "夏季防晒指南",
    contentCount: 12,
    creatorCount: 0,
    commentCount: -1,
    cookie: "should-not-be-read",
  });

  assert.equal(display.summary, "小红书 · 开始关键词采集 · 防晒 · 夏季防晒指南");
  assert.deepEqual(display.counts, [{ key: "contentCount", label: "内容", value: 12 }]);
  assert.deepEqual(createCrawlActivityDisplay(null), {
    message: "采集状态更新",
    context: "",
    summary: "采集状态更新",
    counts: [],
  });
});

test("crawl activity counts call discovered creators accounts", () => {
  const display = createCrawlActivityDisplay({ creatorCount: 2 });
  assert.deepEqual(display.counts, [{ key: "creatorCount", label: "账号", value: 2 }]);
});

test("legacy creator crawl messages are normalized without calling the account a blogger", () => {
  const progress = normalizeCrawlProgress({
    resultPayload: {
      crawlProgress: {
        current: {
          action: "creator_started",
          message: "开始博主主页采集",
        },
        activities: [{
          action: "creator_discovered",
          message: "发现公开博主",
        }],
      },
    },
  });

  assert.equal(progress.current.message, "开始采集当前账号主页公开信息");
  assert.equal(progress.activities[0].message, "发现公开账号");
});

test("crawl platform statuses preserve skipped instead of falling back to pending", () => {
  assert.equal(getCrawlPlatformStatusLabel("skipped"), "已跳过");
  assert.equal(getCrawlPlatformStatusLabel("failed"), "采集失败");
  assert.equal(getCrawlPlatformStatusLabel("unknown"), "等待中");
});

test("crawl progress maps the backend failureSuggestion to the display suggestion", () => {
  const progress = normalizeCrawlProgress({
    resultPayload: {
      crawlProgress: {
        platformSummaries: [{
          platform: "dy",
          platformName: "抖音",
          status: "failed",
          failureCode: "credentials_expired",
          failureMessage: "登录凭证失效或未生效",
          failureSuggestion: "请更新平台登录凭证后重试",
          suggestion: "历史建议不应覆盖真实后端字段",
          rawFailure: "不应透传",
        }],
      },
    },
  });

  assert.deepEqual(progress.platformSummaries[0], {
    platform: "dy",
    platformName: "抖音",
    status: "failed",
    failureCode: "credentials_expired",
    failureMessage: "登录凭证失效或未生效",
    suggestion: "请更新平台登录凭证后重试",
  });
});

test("crawl progress preserves a nonblocking creator configuration notice", () => {
  const progress = normalizeCrawlProgress({
    resultPayload: {
      crawlProgress: {
        platformSummaries: [{
          platform: "dy",
          platformName: "抖音",
          status: "completed",
          contentCount: 12,
          noticeCode: "creator_url_invalid",
          noticeMessage: "当前账号主页链接无效，已跳过主页公开信息采集",
          noticeSuggestion: "请在账号档案中填写该平台真实、完整的当前账号主页链接",
          rawNotice: "https://example.test/profile?token=must-not-pass",
        }],
      },
    },
  });

  assert.deepEqual(progress.platformSummaries[0], {
    platform: "dy",
    platformName: "抖音",
    status: "completed",
    contentCount: 12,
    noticeCode: "creator_url_invalid",
    noticeMessage: "当前账号主页链接无效，已跳过主页公开信息采集",
    noticeSuggestion: "请在账号档案中填写该平台真实、完整的当前账号主页链接",
  });
  assert.doesNotMatch(JSON.stringify(progress), /must-not-pass/);
});

test("legacy creator link notices are normalized by stable notice code", () => {
  const progress = normalizeCrawlProgress({
    resultPayload: {
      crawlProgress: {
        platformSummaries: [{
          noticeCode: "creator_url_invalid",
          noticeMessage: "配置的博主主页链接无效，已跳过主页采集",
          noticeSuggestion: "请在账号档案中填写该平台真实、完整的博主主页链接",
        }],
      },
    },
  });

  assert.equal(
    progress.platformSummaries[0].noticeMessage,
    "当前账号主页链接无效，已跳过主页公开信息采集",
  );
  assert.equal(
    progress.platformSummaries[0].noticeSuggestion,
    "请在账号档案中填写该平台真实、完整的当前账号主页链接",
  );
});

test("crawl progress normalization is bounded and backward compatible", () => {
  assert.deepEqual(normalizeCrawlProgress({ resultPayload: {} }), {
    current: null,
    activities: [],
    platformSummaries: [],
  });

  const workflow = {
    resultPayload: {
      crawlProgress: {
        current: { message: "正在搜索", platformName: "小红书" },
        activities: Array.from({ length: 8 }, (_, index) => ({
          sequence: index + 1,
          message: `活动 ${index + 1}`,
          contentTitle: "x".repeat(80),
        })),
        platformSummaries: [{
          platform: "dy",
          platformName: "抖音",
          status: "failed",
          failureCode: "credentials_expired",
          failureMessage: "登录凭证失效或未生效",
          suggestion: "更新抖音 Cookie 并重启服务",
        }],
      },
    },
  };

  const result = normalizeCrawlProgress(workflow);
  assert.equal(result.activities.length, 5);
  assert.equal(result.activities[0].message, "活动 8");
  assert.equal(result.activities[0].contentTitle.length, 60);
  assert.equal(result.platformSummaries[0].failureCode, "credentials_expired");
});

test("crawl activity feed preserves a backend batch in playback order", () => {
  const activities = normalizeCrawlActivityFeed({
    resultPayload: {
      crawlProgress: {
        activities: Array.from({ length: 10 }, (_, index) => ({
          sequence: 10 - index,
          message: `内容 ${10 - index}`,
        })),
      },
    },
  });

  assert.equal(activities.length, 10);
  assert.deepEqual(activities.map((item) => item.sequence), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
});

test("formatMetric safely handles invalid, small, and large public metrics", () => {
  assert.equal(formatMetric(undefined), "0");
  assert.equal(formatMetric("not-a-number"), "0");
  assert.equal(formatMetric(-3), "0");
  assert.equal(formatMetric(988), "988");
  assert.equal(formatMetric("12345"), "1.2万");
  assert.equal(formatMetric(100000000), "1亿");
});

test("workflow stages use stable Chinese labels with a safe fallback", () => {
  assert.equal(getReportStageLabel("context_loading"), "读取账号档案");
  assert.equal(getReportStageLabel("dashboard_refresh"), "生成账号数据看板");
  assert.equal(getReportStageLabel("creator_crawling"), "采集当前账号主页公开信息");
  assert.equal(getReportStageLabel("keyword_crawling"), "采集行业公开内容");
  assert.equal(getReportStageLabel("report_persistence"), "保存账号报告");
  assert.equal(getReportStageLabel("unknown_stage"), "生成账号报告");
});

test("first active generation uses a skeleton while an old report remains visible", () => {
  const active = { status: "running" };
  assert.equal(hasExistingReport({ reportVersion: 0 }), false);
  assert.equal(shouldShowReportSkeleton({ reportVersion: 0 }, active), true);
  assert.equal(shouldShowReportSkeleton({ reportVersion: 1 }, active), false);
  assert.equal(shouldShowReportSkeleton({ reportVersion: 0, competitors: "旧竞对摘要" }, active), false);
  assert.equal(shouldShowReportSkeleton(null, { status: "failed" }), false);
});

test("a completed workflow report section becomes visible while the workflow is still running", () => {
  const workflow = {
    status: "running",
    progress: 78,
    resultPayload: {
      reportPreview: {
        similarAccounts: [{ name: "增量账号", profileUrl: "https://example.test/creator" }],
        sourceMeta: { sampleCount: 3, keywords: ["通勤妆"] },
      },
      reportSectionsCompleted: ["contentStrategy", "similarAccounts"],
    },
  };

  const preview = mergeAccountReportPreview(null, workflow);
  const view = createAccountReportViewModel(null, workflow);

  assert.equal(preview.similarAccounts[0].name, "增量账号");
  assert.equal(view.state, "content");
  assert.equal(view.isActive, true);
  assert.equal(view.hasPublishedReport, false);
  assert.deepEqual(view.completedSections, ["contentStrategy", "similarAccounts"]);
  assert.deepEqual(view.visibleCompletedSections, ["similarAccounts"]);
  assert.equal(view.visibleSectionsTotal, 4);
  assert.equal(view.similarAccounts[0].safeProfileUrl, "https://example.test/creator");
  assert.deepEqual(view.report.contentStrategy, undefined);
});

test("a published report remains available while independently generated sections refresh", () => {
  const view = createAccountReportViewModel(
    { reportVersion: 2, competitors: "旧版相似账号" },
    {
      status: "running",
      resultPayload: {
        reportPreview: { complianceRules: [{ expression: "最新规则" }] },
        reportSectionsCompleted: ["complianceRules"],
      },
    },
  );

  assert.equal(view.hasPublishedReport, true);
  assert.deepEqual(view.visibleCompletedSections, ["complianceRules"]);
  assert.equal(view.report.complianceRules[0].expression, "最新规则");
  assert.equal(view.report.competitors, "旧版相似账号");
});

test("a completed workflow preview cannot restore a similar account deleted from the published report", () => {
  const deletedAccount = { creatorHash: "creator-deleted", name: "已删除账号" };
  const view = createAccountReportViewModel(
    {
      reportVersion: 3,
      generatedAt: "2026-07-21T12:00:00Z",
      similarAccounts: [{ creatorHash: "creator-kept", name: "保留账号" }],
    },
    {
      status: "completed",
      resultPayload: {
        reportPreview: { similarAccounts: [deletedAccount] },
        reportSectionsCompleted: ["similarAccounts"],
      },
    },
  );

  assert.deepEqual(view.similarAccounts.map((account) => account.creatorHash), ["creator-kept"]);
});

test("a failed workflow drops its incomplete preview and preserves the formal report", () => {
  const formalReport = { reportVersion: 2, competitors: "已发布报告" };
  const workflow = {
    status: "failed",
    resultPayload: {
      reportPreview: { competitors: "未完成预览" },
      reportSectionsCompleted: ["similarAccounts"],
    },
  };

  const view = createAccountReportViewModel(formalReport, workflow);

  assert.equal(view.report.competitors, "已发布报告");
  assert.equal(view.state, "content");
  assert.equal(view.isFailed, true);
});

test("new account seeded report placeholders are not treated as an existing report", () => {
  const newAccountReport = {
    reportVersion: 0,
    generatedAt: null,
    competitors: "基于定位“敏感肌护肤”，系统会结合目标平台生成竞对分析。",
    prohibitedWords: "系统会按创作目标平台切换违禁词规则。",
    targetUsers: "目标用户聚焦于对“敏感肌护肤”感兴趣的人群。",
    hotContent: "系统将在首轮创作后补全爆款内容解析。",
    topBloggers: "系统将在首轮平台分析后生成头部博主解析。",
  };

  assert.equal(hasExistingReport(newAccountReport), false);
  assert.equal(hasExistingReport({ ...newAccountReport, competitors: "真实旧版竞对分析" }), true);
});

test("legacy seeded placeholders allow multiline account descriptions", () => {
  const multilineSeed = {
    reportVersion: 0,
    generatedAt: null,
    competitors: "基于定位“咖啡”\n探店”，系统会结合目标平台生成竞对分析。",
    prohibitedWords: "系统会按创作目标平台切换违禁词规则。",
    targetUsers: "目标用户聚焦于对“咖啡”\n探店”感兴趣的人群。",
    hotContent: "系统将在首轮创作后补全爆款内容解析。",
    topBloggers: "系统将在首轮平台分析后生成头部博主解析。",
  };

  assert.equal(hasExistingReport(multilineSeed), false);
});

test("external report urls allow only absolute http and https links", () => {
  assert.equal(isSafeHttpUrl("https://example.test/note?id=1"), true);
  assert.equal(isSafeHttpUrl("http://example.test/note"), true);
  assert.equal(isSafeHttpUrl("javascript:alert(1)"), false);
  assert.equal(isSafeHttpUrl("//example.test/note"), false);
  assert.equal(isSafeHttpUrl("not a url"), false);
});

test("report metrics render only known public metric keys", () => {
  assert.deepEqual(metricEntries({ likedCount: 12, engagementScore: 82.5, promptInjectionScore: 999, commentCount: "8", shareCount: true }), [
    ["likedCount", 12],
    ["engagementScore", 82.5],
    ["commentCount", 8],
  ]);
  assert.deepEqual(metricEntries({ unknownMetric: 1, fansCount: "invalid" }), []);
  assert.deepEqual(metricEntries({ likedCount: "1622000", collectedCount: "86000", commentCount: "38000", shareCount: "884000", viewCount: 0 }), [
    ["likedCount", 1622000],
    ["collectedCount", 86000],
    ["commentCount", 38000],
    ["shareCount", 884000],
  ]);
});

test("account report view model drives real empty, content, workflow, source, and link states", () => {
  const seeded = {
    reportVersion: 0,
    generatedAt: null,
    competitors: "基于定位“咖啡”，系统会结合目标平台生成竞对分析。",
    prohibitedWords: "系统会按创作目标平台切换违禁词规则。",
    targetUsers: "目标用户聚焦于对“咖啡”感兴趣的人群。",
    hotContent: "系统将在首轮创作后补全爆款内容解析。",
    topBloggers: "系统将在首轮平台分析后生成头部博主解析。",
  };
  assert.equal(createAccountReportViewModel(seeded, null).state, "empty");
  assert.equal(createAccountReportViewModel(seeded, { status: "failed" }).state, "failed");
  assert.equal(createAccountReportViewModel(seeded, { status: "pending", progress: 20 }).state, "skeleton");

  const legacy = createAccountReportViewModel({ reportVersion: 0, competitors: "真实旧报告" }, { status: "pending", progress: 35 });
  assert.equal(legacy.state, "content");
  assert.equal(legacy.isActive, true);
  assert.equal(legacy.progress, 35);

  const structured = createAccountReportViewModel({
    reportVersion: 1,
    similarAccounts: [
      { name: "可跳转账号", profileUrl: "https://www.douyin.com/user/peer" },
      { name: "危险账号", profileUrl: "javascript:alert(1)" },
      { name: "历史账号" },
    ],
    hotContents: [
      { title: "安全", publicUrl: "https://example.test/note", coverUrl: "https://example.test/cover.webp" },
      { title: "危险", publicUrl: "javascript:alert(1)", coverUrl: "data:image/svg+xml,bad" },
    ],
    sourceMeta: {
      sampleCount: 12,
      keywords: ["咖啡"],
      failedPlatforms: ["抖音"],
      unsupportedPlatforms: ["微博"],
    },
  }, { status: "completed", progress: 100 });
  assert.equal(structured.state, "content");
  assert.deepEqual(structured.sourceMeta.keywords, ["咖啡"]);
  assert.equal(structured.hotContents[0].safeUrl, "https://example.test/note");
  assert.equal(structured.hotContents[1].safeUrl, "");
  assert.equal(structured.hotContents[0].safeCoverUrl, "https://example.test/cover.webp");
  assert.equal(structured.hotContents[1].safeCoverUrl, "");
  assert.equal(structured.similarAccounts[0].safeProfileUrl, "https://www.douyin.com/user/peer");
  assert.equal(structured.similarAccounts[1].safeProfileUrl, "");
  assert.equal(structured.similarAccounts[2].safeProfileUrl, "");
});

test("workflow progress clamps finite values and resets invalid values", () => {
  assert.equal(normalizeReportProgress(undefined), 0);
  assert.equal(normalizeReportProgress("invalid"), 0);
  assert.equal(normalizeReportProgress(38), 38);
  assert.equal(normalizeReportProgress(120), 100);
  assert.equal(normalizeReportProgress(-2), 0);
});
