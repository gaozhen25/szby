import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const pageSource = readFileSync(new URL("./CompetitorMonitor.jsx", import.meta.url), "utf8");
const modalSource = readFileSync(
  new URL("../components/competitors/CompetitorAddModal.jsx", import.meta.url),
  "utf8"
);
const accountCardSource = readFileSync(
  new URL("../components/competitors/CompetitorAccountCard.jsx", import.meta.url),
  "utf8"
);
const videoCardSource = readFileSync(
  new URL("../components/competitors/CompetitorVideoCard.jsx", import.meta.url),
  "utf8"
);
const coverImageSource = readFileSync(
  new URL("../components/competitors/CompetitorCoverImage.jsx", import.meta.url),
  "utf8"
);
const metricSource = readFileSync(
  new URL("../components/competitors/CompetitorMetric.jsx", import.meta.url),
  "utf8"
);
const historySource = readFileSync(
  new URL("../components/competitors/CompetitorAccountHistory.jsx", import.meta.url),
  "utf8"
);
const recentWorksSource = readFileSync(
  new URL("../components/competitors/CompetitorRecentWorksModal.jsx", import.meta.url),
  "utf8"
);
const stylesUrl = new URL("../styles/competitor-monitor.css", import.meta.url);
const styles = existsSync(stylesUrl) ? readFileSync(stylesUrl, "utf8") : "";
const globalStyles = readFileSync(new URL("../styles/pages.css", import.meta.url), "utf8");
const allCompetitorSources = [pageSource, modalSource, accountCardSource, videoCardSource, metricSource, historySource, recentWorksSource, styles].join("\n");

test("competitor page uses persisted account monitoring data", () => {
  assert.match(pageSource, /useCompetitorMonitoring/);
  assert.match(pageSource, /monitoring\.accounts/);
  assert.match(pageSource, /monitoring\.addAccount/);
  assert.doesNotMatch(pageSource, /setMode\("video"\)|监控视频/);
  assert.doesNotMatch(pageSource, /美妆达人小A|本地美食家老张|const seed/);
});

test("competitor data hook resumes persisted active refresh workflows", () => {
  const hookSource = readFileSync(
    new URL("../hooks/useCompetitorMonitoring.js", import.meta.url),
    "utf8"
  );
  assert.match(hookSource, /activeCompetitorWorkflowIds\(accountItems\)/);
  assert.match(hookSource, /pollingRef\.current\?\.track\(requestedAccountId, activeWorkflowIds\)/);
});

test("competitor page exposes add and active batch refresh controls", () => {
  assert.match(pageSource, /刷新全部/);
  assert.match(pageSource, /CompetitorAddModal/);
  assert.match(pageSource, /monitoring\.refreshAccounts/);
  assert.doesNotMatch(pageSource, /monitoring\.refreshVideos/);
  assert.match(modalSource, /role="dialog"/);
  assert.match(modalSource, /aria-modal="true"/);
});

test("account monitoring targets support confirmed deletion", () => {
  assert.match(accountCardSource, /window\.confirm/);
  assert.match(accountCardSource, /onDelete\(item\.id\)/);
});

test("account cards open recent works in an accessible modal", () => {
  assert.match(accountCardSource, /item\.newVideos/);
  assert.match(accountCardSource, /recentWorks\.length \?/);
  assert.match(accountCardSource, /CompetitorRecentWorksModal/);
  assert.match(accountCardSource, /setShowRecentWorks\(true\)/);
  assert.match(recentWorksSource, /ModalOverlay/);
  assert.match(recentWorksSource, /competitor-recent-overlay/);
  assert.match(recentWorksSource, /role="dialog"/);
  assert.match(recentWorksSource, /aria-modal="true"/);
  assert.match(recentWorksSource, /event\.key === "Escape"/);
  assert.match(recentWorksSource, /\[1, 2, 7\]/);
  assert.match(recentWorksSource, /metrics\.likes/);
  assert.match(recentWorksSource, /metrics\.collects/);
  assert.match(recentWorksSource, /<CompetitorCoverImage url=\{work\.coverUrl\}/);
  assert.match(recentWorksSource, /target="_blank" rel="noreferrer"/);
  assert.match(styles, /\.competitor-page \.monitor-recent-trigger/);
  assert.match(styles, /\.competitor-recent-modal/);
});

test("competitor video covers convert HEIC and fall back after decode errors", () => {
  assert.match(videoCardSource, /<CompetitorCoverImage url=\{item\.coverUrl\}/);
  assert.match(coverImageSource, /browserCompatibleImageUrl/);
  assert.match(coverImageSource, /onError=\{\(\) => setFailed\(true\)\}/);
});

test("account cards render persisted creator metric history", () => {
  assert.match(accountCardSource, /CompetitorAccountHistory/);
  assert.match(accountCardSource, /item\.metricHistory/);
  assert.match(historySource, /博主数据趋势/);
  assert.match(historySource, /followers/);
  assert.match(historySource, /following/);
  assert.match(historySource, /works/);
  assert.match(historySource, /liked/);
  assert.match(historySource, /polyline/);
});

test("account history renders a horizontal baseline before two snapshots exist", () => {
  assert.match(historySource, /if \(!values\.length\) return `0,/);
  assert.match(historySource, /if \(values\.length === 1\)/);
  assert.match(historySource, /className=\{values\.length \? undefined : "is-baseline"\}/);
  assert.doesNotMatch(historySource, /monitor-history-no-data">暂无数据/);
});

test("account cards render persisted avatars", () => {
  assert.match(accountCardSource, /item\.avatarUrl/);
  assert.match(accountCardSource, /browserCompatibleImageUrl/);
  assert.match(accountCardSource, /onError=\{\(\) => setAvatarFailed\(true\)\}/);
});

test("unknown metrics render as a dash instead of fabricated values", () => {
  assert.match(metricSource, /value === null \|\| value === undefined/);
  assert.match(metricSource, /—/);
});

test("metric changes use contextual trend badges instead of ambiguous plus signs", () => {
  assert.match(metricSource, /较上次更新/);
  assert.match(metricSource, /isUp \? "↗" : "↘"/);
  assert.doesNotMatch(metricSource, /<span>较上次/);
  assert.doesNotMatch(metricSource, /delta > 0 \? "\+"/);
  assert.match(styles, /\.competitor-page \.monitor-metric-trend\.is-up/);
  assert.match(styles, /\.competitor-page \.monitor-metric\s*\{[\s\S]{0,160}height:\s*44px/);
  assert.match(styles, /\.competitor-page \.monitor-metric-trend\s*\{[\s\S]{0,220}padding:\s*0/);
  assert.doesNotMatch(styles, /\.monitor-metric-trend\.is-up\s*\{[^}]*background/);
});

test("account details stay grouped while only the card footer absorbs spare height", () => {
  assert.doesNotMatch(styles, /\.competitor-page \.monitor-metrics\s*\{[^}]*margin-top:\s*auto/);
  assert.match(styles, /\.competitor-page \.monitor-updated\s*\{[^}]*margin-top:\s*auto/);
});

test("cards render the backend succeeded refresh status as updated", () => {
  assert.match(accountCardSource, /succeeded: "已更新"/);
});

test("page shows real refresh status counts and disables an all-active batch", () => {
  assert.match(pageSource, /refreshSummary/);
  assert.match(pageSource, /刷新中/);
  assert.match(pageSource, /失败/);
  assert.match(pageSource, /items\.every/);
});

test("competitor page keeps Kim header controls together and imports isolated styles", () => {
  assert.match(pageSource, /import "\.\.\/styles\/competitor-monitor\.css"/);
  assert.match(pageSource, /<header className="section-header competitor-monitor-header">/);
  assert.match(pageSource, /className="competitor-monitor-actions"/);
  assert.doesNotMatch(pageSource, /className="view-toggle-group"/);
  assert.match(pageSource, /刷新全部/);
  assert.match(pageSource, /＋ 添加监控/);
  assert.doesNotMatch(pageSource, /competitor-toolbar/);
});

test("competitor account cards use Kim monitor structure with real fields and clear action hierarchy", () => {
  assert.match(accountCardSource, /className="glass-card monitor-card/);
  assert.match(accountCardSource, /className="monitor-card-top"/);
  assert.match(accountCardSource, /className="monitor-thumb/);
  assert.match(accountCardSource, /<CompetitorMetric/);
  assert.match(accountCardSource, /className="monitor-card-actions"/);
  assert.match(accountCardSource, /className="btn btn-sm btn-primary"/);
  assert.match(accountCardSource, /className="btn btn-sm"/);
  assert.match(accountCardSource, /className="btn btn-sm btn-danger"/);
  assert.match(accountCardSource, /target="_blank" rel="noreferrer"/);
  assert.match(pageSource, /className="monitor-grid"/);
  assert.doesNotMatch(pageSource, /className={`competitor-grid/);
});

test("competitor monitor CSS follows Kim three-two-one responsive grid and 56px thumbnail", () => {
  assert.match(styles, /\.competitor-page \.monitor-grid\s*\{[\s\S]{0,180}grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(styles, /\.competitor-page \.monitor-card\s*\{/);
  assert.match(styles, /\.competitor-page \.monitor-card-top\s*\{/);
  assert.match(styles, /\.competitor-page \.monitor-thumb\s*\{[\s\S]{0,180}width:\s*56px;[\s\S]{0,80}height:\s*56px/);
  assert.match(styles, /\.competitor-page \.monitor-metric\s*\{/);
  assert.match(styles, /@media\s*\(max-width:\s*1100px\)[\s\S]*\.competitor-page \.monitor-grid\s*\{[\s\S]{0,120}repeat\(2/);
  assert.match(styles, /@media\s*\(max-width:\s*700px\)[\s\S]*\.competitor-page \.monitor-grid\s*\{[\s\S]{0,120}grid-template-columns:\s*1fr/);
});

test("add modal is account-only and retains input after failed locked submission", () => {
  assert.match(modalSource, /className="modal monitor-add-modal"/);
  assert.doesNotMatch(modalSource, /monitor-add-type|监控视频|onModeChange/);
  assert.match(modalSource, /抖音号/);
  assert.match(modalSource, /小红书号/);
  assert.match(modalSource, /await onSubmit\(\{ platform, reference: normalizedValue \}\)/);
  assert.doesNotMatch(modalSource, /主页链接",\s*fieldLabel/);
  assert.match(modalSource, /const submittingRef = useRef\(false\)/);
  assert.match(modalSource, /if \(submittingRef\.current\) return/);
  assert.match(modalSource, /submittingRef\.current = true/);
  assert.match(modalSource, /submittingRef\.current = false/);
  assert.match(modalSource, /catch \(_error\)[\s\S]{0,180}finally/);
  assert.doesNotMatch(modalSource, /catch \(_error\)[\s\S]{0,180}setUrl\(""\)/);
  assert.match(styles, /\.monitor-add-overlay \.monitor-add-modal\s*\{/);
});

test("add modal offers two platforms and pins close control to the top-right corner", () => {
  assert.match(modalSource, /const PLATFORMS = \[/);
  assert.match(modalSource, /抖音号或者抖音主页链接/);
  assert.match(modalSource, /小红书号或者小红书主页链接/);
  assert.match(modalSource, /className="btn btn-xs monitor-add-close"/);
  assert.match(modalSource, /后台会自动判断输入的是\{platform\}号还是公开主页链接/);
  assert.match(styles, /\.monitor-add-overlay \.monitor-add-platform\s*\{[\s\S]{0,180}repeat\(2/);
  assert.match(styles, /\.monitor-add-overlay \.monitor-add-close\s*\{[\s\S]{0,180}position:\s*absolute;[\s\S]{0,120}top:[\s\S]{0,120}right:/);
  assert.doesNotMatch(styles, /\.competitor-page \.monitor-add-close/);
});

test("add modal always submits account monitoring targets", () => {
  assert.doesNotMatch(pageSource, /addMode|onModeChange/);
  assert.match(pageSource, /monitoring\.addAccount\(reference\)/);
  assert.doesNotMatch(pageSource, /monitoring\.addVideo/);
});

test("add modal traps keyboard focus and restores it to the opener", () => {
  assert.match(modalSource, /const dialogRef = useRef\(null\)/);
  assert.match(modalSource, /event\.key !== "Tab"/);
  assert.match(modalSource, /querySelectorAll/);
  assert.match(modalSource, /previouslyFocused/);
  assert.match(modalSource, /previouslyFocused\.focus\(\)/);
  assert.match(modalSource, /ref=\{dialogRef\}/);
});

test("medium layouts stack the expanded develop controls without retaining obsolete competitor CSS", () => {
  assert.match(
    styles,
    /@media\s*\(max-width:\s*1100px\)[\s\S]*\.competitor-page \.competitor-monitor-header\s*\{[\s\S]{0,160}flex-direction:\s*column/
  );
  assert.match(styles, /\.competitor-page \.competitor-empty\s*\{/);
  assert.doesNotMatch(globalStyles, /\.competitor-toolbar|\.competitor-grid|\.competitor-card\s*\{/);
});

test("competitor UX never imports Kim demo data or fake detail flows", () => {
  for (const forbidden of [
    "trendPoints",
    "chartPath",
    "example.com",
    "benchmarkAccounts",
    "monitorVideos",
    "platformFromUrl",
  ]) {
    assert.doesNotMatch(allCompetitorSources, new RegExp(forbidden.replace(".", "\\.")));
  }
  assert.doesNotMatch(allCompetitorSources, /Array\.from\(\{\s*length/);
});
