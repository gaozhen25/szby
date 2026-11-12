import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(
  new URL("./DataDashboard.jsx", import.meta.url),
  "utf8",
);

test("TOP content covers avoid referrer leakage and fall back after CDN errors", () => {
  assert.match(source, /function TopContentCover/);
  assert.match(source, /referrerPolicy="no-referrer"/);
  assert.match(source, /onError=\{\(\) => setFailed\(true\)\}/);
  assert.match(source, /<TopContentCover content=\{content\} \/>/);
});

test("content table shows interaction values and hourly changes without play metrics", () => {
  assert.match(source, />点赞</);
  assert.match(source, />评论</);
  assert.match(source, />收藏</);
  assert.match(source, />分享</);
  assert.match(source, />1h变化</);
  assert.match(source, />24h变化</);
  assert.match(source, /formatMetric\(content\.likes\)/);
  assert.doesNotMatch(source, />播放量</);
  assert.doesNotMatch(source, />阅读量</);
});

test("dashboard requests only a platform configured on the current account", () => {
  assert.match(source, /const configuredPlatforms = \["抖音", "小红书"\]\.filter/);
  assert.match(source, /app\.currentAccount\?\.platformAccounts\?\.\[item\]/);
  assert.match(source, /configuredPlatforms\.length/);
  assert.match(source, /const effectivePlatform = availablePlatforms\.includes\(platform\)/);
  assert.match(source, /platform: effectivePlatform, days/);
  assert.match(source, /!app\.currentAccountId \|\| !effectivePlatform/);
});

test("dashboard renders an accessible animated page while initial data is loading", () => {
  assert.match(source, /function DashboardLoadingPage/);
  assert.match(source, /role="status"/);
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /正在加载作品互动数据/);
  assert.match(source, /if \(!dashboard\) return <DashboardLoadingPage \/>/);
});

test("dashboard submits and polls an asynchronous manual refresh", () => {
  assert.match(source, /const refreshDashboard = async \(\) =>/);
  assert.match(source, /startDashboardRefresh/);
  assert.match(source, /getDashboardRefresh/);
  assert.match(source, /window\.setTimeout\(poll, 1500\)/);
  assert.match(source, /主动刷新/);
  assert.match(source, /disabled=\{loading \|\| refreshing \|\| !effectivePlatform\}/);
});

test("dashboard renders unavailable changes as accumulating instead of zero", () => {
  assert.match(source, /function formatDelta/);
  assert.match(source, /return "待积累"/);
});

test("dashboard empty works state does not ask to fill account", () => {
  assert.match(source, /该账号暂无作品/);
  assert.match(source, /social\?\.status === "empty"/);
  assert.match(source, /isUnconfigured \? \(/);
});

test("dashboard fetches and renders a selected work's hourly interaction trend", () => {
  assert.match(source, /function ContentTrend/);
  assert.match(source, /getDashboardContentTrend/);
  assert.match(source, /TREND_METRICS/);
  assert.match(source, /className="chart-svg own-content-trend"/);
  assert.match(source, /setSelectedContentId\(content\.contentId\)/);
  assert.match(source, /相邻点的差值代表对应小时的新增或回落/);
});

test("dashboard header does not expose retrieval provider label", () => {
  assert.doesNotMatch(source, /数据源 \$\{social\.provider\}/);
  assert.doesNotMatch(source, /providerLabel/);
});
