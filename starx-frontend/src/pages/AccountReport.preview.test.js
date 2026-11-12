import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./AccountReport.jsx", import.meta.url), "utf8");
const sectionSource = readFileSync(new URL("./account-report/AccountReportSections.jsx", import.meta.url), "utf8");
const progressSource = readFileSync(
  new URL("./account-report/AccountReportLoadingOverlay.jsx", import.meta.url),
  "utf8",
);
const utilitySource = readFileSync(new URL("../utils/accountReport.js", import.meta.url), "utf8");
const exportUtilitySource = readFileSync(new URL("../utils/accountReportExport.js", import.meta.url), "utf8");
const reportSource = `${source}\n${sectionSource}\n${progressSource}\n${utilitySource}`;
const styles = [
  readFileSync(new URL("../styles/pages.css", import.meta.url), "utf8"),
  readFileSync(new URL("../styles/account-report.css", import.meta.url), "utf8"),
].join("\n");
const similarModalSource = readFileSync(
  new URL("./account-report/SimilarAccountModal.jsx", import.meta.url),
  "utf8",
);
const similarDeleteModalSource = readFileSync(
  new URL("./account-report/SimilarAccountDeleteModal.jsx", import.meta.url),
  "utf8",
);
const creatorAvatarSource = readFileSync(
  new URL("../components/CreatorAvatar.jsx", import.meta.url),
  "utf8",
);

test("account report renders structured backend fields without report mocks", () => {
  assert.doesNotMatch(source, /mockSimilarAccounts|const complianceRules\s*=|油皮夏日持妆实测|速效祛痘/);
  assert.match(source, /reportView\.similarAccounts/);
  assert.match(source, /report\?\.complianceRules/);
  assert.match(source, /report\?\.targetUserProfile/);
  assert.match(sectionSource, /profile\.categories/);
  assert.match(sectionSource, /priorityRanking/);
  assert.match(sectionSource, /positioningReminder/);
  assert.match(sectionSource, /非有效用户/);
  assert.match(sectionSource, /当前保存的是旧版目标用户画像/);
  assert.match(sectionSource, /重新生成/);
  assert.doesNotMatch(sectionSource, /<h4>内容偏好<\/h4>/);
  assert.doesNotMatch(sectionSource, /<h4>购买顾虑<\/h4>/);
  assert.doesNotMatch(sectionSource, /<h4>转化触点<\/h4>/);
  assert.match(utilitySource, /effectiveReport\?\.hotContents/);
  assert.doesNotMatch(source, /reportView\.topBloggerDetails/);
  assert.doesNotMatch(source, /report\?\.contentStrategy/);
  assert.match(utilitySource, /effectiveReport\?\.sourceMeta/);
  assert.match(source, /report\?\.competitors/);
  assert.match(source, /report\?\.prohibitedWords/);
  assert.match(source, /report\?\.targetUsers/);
  assert.match(source, /report\?\.hotContent/);
  assert.doesNotMatch(source, /report\?\.topBloggers/);
  assert.match(utilitySource, /workflow\?\.resultPayload\?\.reportPreview/);
});

test("similar accounts can be added directly to competitor monitoring", () => {
  assert.match(source, /app\.addCompetitorAccount\(profileUrl\)/);
  assert.match(source, /onAddToCompetitors=\{addSimilarAccountToCompetitors\}/);
  assert.match(sectionSource, /function AddToCompetitorsButton/);
  assert.match(sectionSource, /添加到竞品监控/);
  assert.match(sectionSource, /缺少公开主页链接/);
  assert.match(styles, /\.report-add-competitor/);
});

test("account report wires workflow loading, safe failure, and refresh", () => {
  assert.match(source, /app\.reportWorkflow/);
  assert.match(source, /app\.isGeneratingReport/);
  assert.match(source, /app\.refreshAccountReport\(referenceComments, null\)/);
  assert.match(source, /createAccountReportViewModel\(app\.report, workflow\)/);
  assert.match(source, /reportView\.state === "skeleton"/);
  assert.match(source, /const showLoading = Boolean\(app\.isGeneratingReport \|\| reportView\.isActive\)/);
  assert.match(source, /disabled=\{showLoading\}/);
});

test("each visible account report block can regenerate independently", () => {
  assert.match(source, /重新生成全部/);
  for (const sectionKey of ["similarAccounts", "complianceRules", "targetUserProfile", "hotContents"]) {
    assert.match(source, new RegExp(`refreshSection\\("${sectionKey}"\\)`));
    assert.match(source, new RegExp(`isSectionGenerating\\("${sectionKey}"\\)`));
  }
  assert.match(source, /app\.reportSectionWorkflows/);
  assert.match(source, /hasGeneratingSection/);
  assert.match(source, /workflow\?\.inputPayload\?\.sectionKey/);
  assert.match(source, /const showFullLoading = showLoading && !activeSectionKey/);
  assert.match(sectionSource, /function SectionRegenerateButton/);
  assert.equal((sectionSource.match(/headerAction=\{<SectionRegenerateButton/g) || []).length, 4);
  assert.match(styles, /\.report-section-regenerate/);
});

test("account report reveals each visible AI section as soon as that section completes", () => {
  assert.match(source, /reportView\.visibleCompletedSections\.length > 0/);
  assert.match(source, /const showReportContent = hasReport &&/);
  assert.match(source, /completedSections\.has\(sectionKey\)/);
  assert.match(source, /isSectionReady\("similarAccounts"\)/);
  assert.match(source, /isSectionReady\("complianceRules"\)/);
  assert.match(source, /isSectionReady\("targetUserProfile"\)/);
  assert.match(source, /isSectionReady\("hotContents"\)/);
  assert.equal((source.match(/<ReportSectionLoading/g) || []).length, 4);
  assert.match(sectionSource, /完成后会自动展示，无需等待其他板块/);
  assert.match(progressSource, /report-progress-banner/);
  assert.match(progressSource, /const progressVerb = reportView\.hasPublishedReport \? "已更新" : "已展示"/);
  assert.match(progressSource, /\{progressVerb\} \{reportView\.visibleCompletedSections\.length\}\/\{reportView\.visibleSectionsTotal\} 个板块/);
  assert.doesNotMatch(source, /!showLoading && !skeleton && hasReport/);
});

test("account report keeps an accessible opt-in comment switch for the current account session", () => {
  assert.match(source, /const \[referenceComments, setReferenceComments\] = useState\(false\)/);
  assert.match(source, /useEffect\(\(\) => \{[\s\S]*setReferenceComments\(false\)/);
  assert.match(source, /\[app\.currentAccount\?\.id\]/);
  assert.match(source, /role="switch"/);
  assert.match(source, /aria-checked=\{referenceComments\}/);
  assert.match(source, /参考内容评论/);
  assert.match(source, /onClick=\{refresh\}/);
  assert.match(styles, /\.report-comment-switch\[aria-checked="true"\]/);
  assert.match(styles, /\.report-comment-switch:focus-visible/);
});

test("account report renders source notices and safe external links", () => {
  assert.match(source, /sourceMeta\.failedPlatforms/);
  assert.match(source, /sourceMeta\.unsupportedPlatforms/);
  assert.match(source, /sourceMeta\.keywords/);
  assert.match(reportSource, /sourceMeta\.sampleCount/);
  assert.match(source, /report\?\.generatedAt/);
  assert.match(reportSource, /content\.safeUrl/);
  assert.match(reportSource, /target="_blank"/);
  assert.match(reportSource, /rel="noopener noreferrer"/);
  assert.doesNotMatch(reportSource, /dangerouslySetInnerHTML/);
});

test("account report target profile text blocks clamp to two lines with trailing toggles", () => {
  assert.match(sectionSource, /function ExpandableText/);
  assert.match(sectionSource, /function ExpandableBlock/);
  assert.match(sectionSource, /label="分析假设："/);
  assert.match(sectionSource, /男性画像/);
  assert.match(sectionSource, /女性画像/);
  assert.match(sectionSource, /target-profile-conclusion-body/);
  assert.match(sectionSource, /优先用户排序/);
  assert.match(sectionSource, /定位提醒/);
  assert.match(styles, /\.expandable-text-body\.is-clamped/);
  assert.match(styles, /\.expandable-block-body\.is-clamped/);
  assert.match(styles, /max-height:\s*calc\(1\.7em \* var\(--expandable-lines,\s*2\)(?:\s*\+\s*4px)?\)/);
});

test("account report shows up to eight hot references with trusted covers and compact metrics", () => {
  assert.match(sectionSource, /contents\.slice\(0, 8\)/);
  assert.match(sectionSource, /content\.contentType === "video" \? "🎬" : "📄"/);
  assert.match(sectionSource, /content\.safeCoverUrl/);
  assert.match(sectionSource, /referrerPolicy="no-referrer"/);
  assert.match(styles, /\.trending-note-content[\s\S]*flex-direction:\s*column/);
  assert.match(styles, /\.trending-note \.report-metrics/);
});

test("account report links similar accounts through normalized profile urls", () => {
  assert.match(source, /reportView\.similarAccounts/);
  assert.match(sectionSource, /function CreatorProfileName/);
  assert.match(sectionSource, /creator\?\.safeProfileUrl/);
  assert.equal((sectionSource.match(/<CreatorProfileName/g) || []).length, 2);
  assert.match(sectionSource, /creator-profile-link/);
  assert.match(styles, /\.creator-profile-link:focus-visible/);
});

test("similar account lists render persisted avatars with a safe fallback", () => {
  assert.match(sectionSource, /import CreatorAvatar/);
  assert.equal((sectionSource.match(/<CreatorAvatar/g) || []).length, 2);
  assert.match(creatorAvatarSource, /creator\?\.avatarUrl/);
  assert.match(creatorAvatarSource, /referrerPolicy="no-referrer"/);
  assert.match(creatorAvatarSource, /onError=\{\(\) => setFailed\(true\)\}/);
  assert.match(creatorAvatarSource, /creator-avatar-fallback/);
  assert.match(styles, /\.creator-avatar > img/);
});

test("account report lets users persistently add and delete similar accounts", () => {
  assert.match(source, /app\.resolveReportSimilarAccount/);
  assert.match(source, /app\.addReportSimilarAccount/);
  assert.match(source, /app\.deleteReportSimilarAccount/);
  assert.match(sectionSource, /添加相似账号/);
  assert.match(sectionSource, /configurationSource === "manual"/);
  assert.match(source, /account\.configurationKey \|\| account\.creatorHash/);
  assert.match(sectionSource, /account\.configurationKey \|\| account\.creatorHash/);
  assert.match(source, /缺少删除标识/);
  assert.doesNotMatch(source, /window\.confirm/);
  assert.match(source, /pendingDeleteSimilarAccount/);
  assert.match(similarDeleteModalSource, /role="alertdialog"/);
  assert.match(similarDeleteModalSource, /确认删除相似账号/);
  assert.match(sectionSource, /report-similar-delete/);
  assert.match(similarModalSource, /系统会自动识别平台并获取博主信息/);
  assert.doesNotMatch(similarModalSource, /账号名称/);
  assert.doesNotMatch(similarModalSource, /<select/);
  assert.match(similarModalSource, /type="url"/);
  assert.match(similarModalSource, /正在解析/);
  assert.match(similarModalSource, /是他/);
  assert.match(similarModalSource, /resolvedAccount\.followers/);
  assert.match(styles, /\.report-manual-tag/);
});

test("account report platform tags use readable Chinese labels instead of raw codes", () => {
  assert.match(sectionSource, /function PlatformTag/);
  assert.match(sectionSource, /resolvePlatformDisplay\(platform\)/);
  assert.match(sectionSource, /<PlatformTag platform=\{account\.platform\}/);
  assert.match(utilitySource, /xhs:\s*\{\s*label:\s*"小红书"/);
  assert.match(styles, /\.platform-readable-tag/);
  assert.doesNotMatch(sectionSource, /className="mini-tag">\{account\.platform/);
});

test("account report card actions use the shared website button style", () => {
  assert.match(sectionSource, /className="btn btn-sm report-card-action"[^>]*>查看完整名单/);
  assert.match(sectionSource, /className="btn btn-sm report-card-action"[^>]*>查看规则/);
  assert.equal((sectionSource.match(/type="button" className="btn btn-sm report-card-action"/g) || []).length, 2);
  assert.doesNotMatch(sectionSource, /className="view-link"/);
  assert.match(styles, /\.report-card-action\s*\{[\s\S]*margin-top:/);
});

test("account report uses editorial masthead layout with top pair and full-bleed rows", () => {
  assert.match(source, /account-report-ux-shell/);
  assert.match(source, /report-masthead/);
  assert.match(source, /report-grid-editorial/);
  assert.match(source, /report-grid-top/);
  assert.match(source, /report-grid-wide/);
  assert.match(source, /import "\.\.\/styles\/account-report\.css"/);
  assert.match(styles, /\.report-grid-editorial/);
  assert.match(styles, /\.report-masthead/);
});

test("account report keeps responsive main and detail layouts", () => {
  assert.match(source, /setView\("similar"\)/);
  assert.match(source, /setView\("rules"\)/);
  assert.match(source, /AccountReportLoadingOverlay/);
  assert.match(source, /report-loading-slot/);
  assert.match(styles, /\.report-source-notices/);
  assert.match(styles, /@media \(max-width: 700px\)[\s\S]*\.report-hero/);
});

test("account report exports a professional report as PDF and Markdown", () => {
  assert.match(source, /createAccountReportExport/);
  assert.match(source, /downloadAccountReportMarkdown/);
  assert.match(source, /printAccountReportPdf/);
  assert.match(source, /导出 PDF/);
  assert.match(source, /导出 MD/);
  assert.match(styles, /\.report-export-actions/);
  assert.match(exportUtilitySource, /text\/markdown;charset=utf-8/);
  assert.match(exportUtilitySource, /@page \{ size: A4; margin: 16mm 15mm; \}/);
  assert.match(exportUtilitySource, /核心概览/);
  assert.match(exportUtilitySource, /关键发现/);
  assert.match(exportUtilitySource, /ACCOUNT INTELLIGENCE REPORT/);
  assert.match(exportUtilitySource, /01 相似账号洞察/);
  assert.match(exportUtilitySource, /02 行业合规提醒/);
  assert.match(exportUtilitySource, /03 目标用户画像/);
  assert.match(exportUtilitySource, /04 爆款内容参考/);
  assert.match(exportUtilitySource, /window\.print\(\)/);
});

test("account report uses the shared full-screen animation for live backend status", () => {
  assert.match(source, /AccountReportLoadingOverlay/);
  assert.match(progressSource, /import LoadingOverlay/);
  assert.match(progressSource, /normalizeCrawlActivityFeed\(workflow\)/);
  assert.match(progressSource, /createCrawlActivityDisplay\(currentActivity\)\.summary/);
  assert.match(progressSource, /statusMessage="预计十分钟左右完成"/);
  assert.match(progressSource, /subMessage=\{backendStatus \|\| undefined\}/);
  assert.match(progressSource, /showProgress=\{false\}/);
  assert.match(progressSource, /embedded/);
  assert.doesNotMatch(progressSource, /\bcontained\b/);
  assert.doesNotMatch(progressSource, /platformSummaries/);
  assert.doesNotMatch(sectionSource, /头部博主参考/);
  assert.doesNotMatch(sectionSource, /title="内容策略"/);
  assert.doesNotMatch(progressSource, /dangerouslySetInnerHTML/);
});

test("account report queues batched backend messages for two seconds each", () => {
  assert.match(progressSource, /const STATUS_DISPLAY_MS = 2000/);
  assert.match(progressSource, /queueRef\.current\.push\(activity\)/);
  assert.match(progressSource, /queueRef\.current\.shift\(\)/);
  assert.match(progressSource, /window\.setTimeout/);
});

test("account report removes the inline progress, activity, and platform summary UI", () => {
  assert.doesNotMatch(source, /ReportSkeleton/);
  assert.doesNotMatch(progressSource, /report-workflow-status/);
  assert.doesNotMatch(progressSource, /report-crawl-activities/);
  assert.doesNotMatch(progressSource, /report-platform-summaries/);
});
