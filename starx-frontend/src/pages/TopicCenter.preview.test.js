import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const styles = readFileSync(new URL("../styles/pages.css", import.meta.url), "utf8");
const componentStyles = readFileSync(new URL("../styles/components.css", import.meta.url), "utf8");
const topicStyles = readFileSync(new URL("../styles/topic-center.css", import.meta.url), "utf8");
const topicCenterSource = readFileSync(new URL("./TopicCenter.jsx", import.meta.url), "utf8");
const preferenceModalSource = readFileSync(new URL("../components/CreationPreferenceModal.jsx", import.meta.url), "utf8");
const imagePreferenceFieldsSource = readFileSync(new URL("../components/ImagePreferenceFields.jsx", import.meta.url), "utf8");
const appHookSource = readFileSync(new URL("../hooks/useStarxApp.js", import.meta.url), "utf8");
const generateCreationSource = appHookSource.slice(
  appHookSource.indexOf("const generateCreation = useCallback"),
  appHookSource.indexOf("const reversePrompt = useCallback")
);

test("topic center shows refresh workflow loading state", () => {
  assert.match(topicCenterSource, /app\.isRefreshingTopics/);
  assert.match(topicCenterSource, /isCreating \|\| app\.isRefreshingTopics/);
  assert.match(topicCenterSource, /正在生成新一批选题/);
  assert.match(topicCenterSource, /结合账号报告、用户画像和参考笔记分析/);
  assert.match(topicCenterSource, /<LoadingOverlay\s+contained/);
  assert.match(componentStyles, /\.loading-overlay\.loading-overlay-contained\s*\{[\s\S]*left:/);
  assert.match(topicCenterSource, /AI 分析中/);
  assert.match(topicCenterSource, /disabled=\{app\.isRefreshingTopics\}/);
});

test("switching accounts clears topic data and shows generation loading", () => {
  const switchSource = appHookSource.slice(
    appHookSource.indexOf("const switchAccount = useCallback"),
    appHookSource.indexOf("const refreshAccountReport = useCallback")
  );
  assert.match(switchSource, /setTopics\(\[\]\)/);
  assert.match(switchSource, /setFavoriteTopics\(\[\]\)/);
  assert.match(switchSource, /setIsRefreshingTopics\(true\)/);
  assert.match(switchSource, /await loadAccountBundle\(accountId\)/);
});

test("topic cards render recommended platforms and reason", () => {
  assert.match(topicCenterSource, /topic\.platforms/);
  assert.match(topicCenterSource, /className="topic-platforms"/);
  assert.match(topicCenterSource, /className="topic-reason"/);
  assert.match(styles, /\.topic-platforms\s*\{/);
  assert.match(styles, /\.topic-reason\s*\{/);
  assert.match(topicCenterSource, /const formatTopicReason = \(topic\) =>/);
  assert.match(topicCenterSource, /topic\?\.referenceNote\?\.contentId/);
  assert.match(topicCenterSource, /const reason = formatTopicReason\(topic\)/);
});

test("topic cards expose bound hot-note evidence for image and video", () => {
  assert.match(topicCenterSource, /topic\?\.referenceNote/);
  assert.match(topicCenterSource, /resolveReferenceNote/);
  assert.match(topicCenterSource, /noteType !== topicType/);
  assert.match(topicCenterSource, /参考爆款/);
  assert.match(topicCenterSource, /referenceNote\.publicUrl/);
  assert.match(topicCenterSource, /selectionReason/);
  assert.match(topicCenterSource, /topic-copy-hit-tag">🔥 抄爆/);
  assert.match(topicCenterSource, /activeFilter === "抄爆".*resolveReferenceNote/s);
  assert.match(topicCenterSource, /className="topic-reference-title"/);
  assert.match(topicCenterSource, /TopicReferenceNote/);
  assert.match(topicCenterSource, /expanded \? "收起" : "展开"/);
  assert.match(topicCenterSource, /expanded \? \([\s\S]*topic-reference-title[\s\S]*\) : null/);
  assert.match(topicStyles, /\.topic-reference-note\s*\{/);
  assert.match(topicStyles, /\.topic-reference-title\s*\{[\s\S]*text-overflow:\s*ellipsis;[\s\S]*white-space:\s*nowrap;/);
  assert.match(topicStyles, /\.topic-reference-toggle/);
});

test("topic cards preserve Kim CTA hierarchy and recommendation stars", () => {
  assert.match(topicCenterSource, /platformLabelWithEmoji/);
  assert.match(topicCenterSource, /className="topic-score"/);
  assert.match(topicCenterSource, /const recommendStars = \(topic\) =>/);
  assert.match(topicCenterSource, /topic\?\.score \?\? topic\?\.heat \?\? topic\?\.recommendScore \?\? topic\?\.recommend_score/);
  assert.match(topicCenterSource, /Math\.max\(1, Math\.min\(5/);
  assert.match(topicCenterSource, /return "⭐"\.repeat\(3 \+ \(hash % 3\)\)/);
  assert.match(topicCenterSource, /const stars = recommendStars\(topic\)/);
  assert.match(topicCenterSource, /title="推荐指数">\{stars\}/);
  assert.doesNotMatch(topicCenterSource, /⭐ AI 推荐/);
  assert.doesNotMatch(topicCenterSource, /Math\.random/);
  assert.match(topicCenterSource, /className="btn btn-create"/);
  assert.match(topicCenterSource, /去创作/);
  assert.doesNotMatch(topicCenterSource, /换一个/);
  assert.match(topicCenterSource, /收藏/);
  assert.match(styles, /\.btn-create\s*\{/);
  assert.match(styles, /\.topic-actions \.btn-ghost/);
  assert.match(styles, /\.topic-score\s*\{/);
});

test("topic center uses the current account dashboard and Kim namespaced stats", () => {
  assert.match(topicCenterSource, /app\.dashboard\?\.creation\s*\?\?\s*0/);
  assert.match(topicCenterSource, /className="topic-stats"/);
  assert.match(topicCenterSource, /className="topic-stat"/);
  assert.match(topicCenterSource, /className="topic-stat-value"/);
  assert.doesNotMatch(topicCenterSource, /summary\?\.\[0\]/);
  assert.doesNotMatch(topicCenterSource, /\|\|\s*5/);
  assert.match(topicStyles, /\.topic-stats\s*\{/);
  assert.match(topicStyles, /\.topic-ux-filters\s*\{/);
  assert.match(topicStyles, /@media\s*\(max-width:\s*700px\)/);
});

test("topic favorites use a durable dedicated view with delete and creation actions", () => {
  assert.match(topicCenterSource, /activeView/);
  assert.match(topicCenterSource, /我的收藏/);
  assert.match(topicCenterSource, /app\.favoriteTopics/);
  assert.match(topicCenterSource, /app\.favoriteTopic\(topic\.id\)/);
  assert.match(topicCenterSource, /app\.deleteFavoriteTopic\(topic\.id\)/);
  assert.match(topicCenterSource, /card\(topic, activeView === "favorites"\)/);
  assert.match(topicCenterSource, /openCreationPreferences\(topic\)/);
  assert.match(topicCenterSource, /还没有收藏选题/);
  assert.match(topicStyles, /\.topic-view-tabs\s*\{/);
  assert.match(topicStyles, /\.topic-empty-state\s*\{/);
  assert.doesNotMatch(topicCenterSource, /useState\(\[\]\).*favorites/);
});

test("image topic creation shows reference-aware loading feedback", () => {
  assert.match(topicCenterSource, /import LoadingOverlay/);
  assert.match(topicCenterSource, /isCreating\s*\?\s*\(/);
  assert.match(topicCenterSource, /<LoadingOverlay/);
  assert.match(topicCenterSource, /正在解析参考爆款/);
  assert.match(topicCenterSource, /正在进入 AI 图文创作/);
  assert.match(topicCenterSource, /完成后将进入解析结果页面/);
  assert.match(topicCenterSource, /无需参考笔记，AI 将根据选题和账号信息生成生图提示词/);
  assert.ok(topicCenterSource.indexOf("setIsCreating(true)") < topicCenterSource.indexOf("<LoadingOverlay"));
  assert.match(topicCenterSource, /selectedTopic\?\.type === "video" && !isCreating/);
  assert.doesNotMatch(topicCenterSource, /generateCreation\(topic\.id,\s*["']小红书["']/);
});

test("topic recommendation metadata is normalized before rendering", () => {
  assert.match(topicCenterSource, /normalizeTopicMetaText/);
  assert.match(topicCenterSource, /typeof value === "string" \|\| typeof value === "number"/);
  assert.match(topicCenterSource, /String\(value\)\.trim\(\)/);
  assert.match(topicCenterSource, /topic\.platforms\)\s*\?\s*topic\.platforms\.map\(normalizeTopicMetaText\)\.filter\(Boolean\)/);
  assert.match(topicCenterSource, /const reason = normalizeTopicMetaText\(topic\?\.reason\)/);
});

test("image topic button skips preferences while video still opens them", () => {
  assert.match(topicCenterSource, /const \[selectedTopic,\s*setSelectedTopic\] = useState\(null\)/);
  assert.match(topicCenterSource, /onClick=\{\(\) => openCreationPreferences\(topic\)\}/);
  assert.match(topicCenterSource, /if \(topic\.type !== "video"\)/);
  assert.match(topicCenterSource, /void createFromTopic\(topic, \{ targetPlatform: resolveImageTargetPlatform\(topic\) \}\)/);
  assert.match(topicCenterSource, /selectedTopic\?\.type === "video"/);
  assert.doesNotMatch(topicCenterSource, /onClick=\{\(\) => app\.generateCreation/);
});

test("image topics without a hot-note link still enter creation and start an AI prompt plan", () => {
  assert.doesNotMatch(topicCenterSource, /图文选题缺少可用的图文爆款链接/);
  assert.match(generateCreationSource, /const hasImageReference =/);
  assert.match(generateCreationSource, /if \(!hasImageReference\)/);
  const noReferenceBranch = generateCreationSource.slice(
    generateCreationSource.indexOf("if (!hasImageReference)"),
    generateCreationSource.indexOf("const extractedLinkReference")
  );
  assert.match(noReferenceBranch, /useOriginalAsReference:\s*false/);
  assert.match(noReferenceBranch, /setActivePage\("creation"\)/);
  assert.match(noReferenceBranch, /starxApi\.createTopicPromptJob\(currentAccountId/);
  assert.match(noReferenceBranch, /imagePromptJobId:\s*jobId/);
  assert.match(noReferenceBranch, /imagePromptPlanStartError:\s*failureMessage/);
});

test("video creation remains preference-confirmed", () => {
  assert.match(topicCenterSource, /<CreationPreferenceModal/);
  assert.match(topicCenterSource, /topic=\{selectedTopic\}/);
  assert.match(topicCenterSource, /variant="video"/);
  assert.match(topicCenterSource, /account=\{app\.currentAccount\}/);
  assert.match(topicCenterSource, /onCancel=\{closeCreationPreferences\}/);
  assert.match(topicCenterSource, /generateCreation:\s*app\.generateCreation/);
  assert.match(topicCenterSource, /setSelectedTopic\(null\)/);
  assert.match(generateCreationSource, /async \(topicId, targetPlatform, preferences\)/);
});

test("skeleton failure retains the selected topic and preferences for retry", () => {
  assert.match(topicCenterSource, /submitTopicCreation/);
  assert.match(topicCenterSource, /initialPreferences=\{retryPreferences\}/);
  assert.match(topicCenterSource, /setRetryPreferences\(preferences\)/);
  assert.match(topicCenterSource, /addToast/);
});

test("video handoff opens the skeleton before starting a preference-aware script job", () => {
  const setCreationIndex = generateCreationSource.indexOf("setCreation(");
  const setActivePageIndex = generateCreationSource.indexOf('setActivePage("creation")');
  const createVideoScriptJobIndex = generateCreationSource.indexOf("starxApi.createVideoScriptJob(");

  assert.ok(setCreationIndex >= 0);
  assert.ok(setActivePageIndex > setCreationIndex);
  assert.ok(createVideoScriptJobIndex > setActivePageIndex);
  assert.match(generateCreationSource, /starxApi\.createVideoScriptJob\(currentAccountId,\s*\{/);
  assert.match(generateCreationSource, /topicId,/);
  assert.match(generateCreationSource, /targetPlatform:\s*nextCreation\.targetPlatform \|\| targetPlatform/);
  assert.match(generateCreationSource, /durationSeconds:\s*preferences\.durationSeconds/);
  assert.match(generateCreationSource, /contentGoal:\s*preferences\.contentGoal/);
  assert.match(generateCreationSource, /videoFormat:\s*preferences\.videoFormat/);
  assert.match(generateCreationSource, /toneStyle:\s*preferences\.toneStyle/);
  assert.match(generateCreationSource, /customRequirements:\s*preferences\.customRequirements/);
  assert.doesNotMatch(generateCreationSource, /createScriptRewriteJob|script-rewrite-jobs|scriptRewriteJobId/);
});

test("video handoff stores its active job and confirmed retry preferences", () => {
  const createVideoScriptJobIndex = generateCreationSource.indexOf("starxApi.createVideoScriptJob(");
  assert.ok(generateCreationSource.indexOf("videoScriptDurationSeconds") < createVideoScriptJobIndex);
  assert.match(generateCreationSource, /applyAutostartVideoScriptJobResult\(currentCreation/);
  assert.match(generateCreationSource, /jobId:\s*job\.id/);
  assert.match(generateCreationSource, /videoScriptDurationSeconds:\s*preferences\.durationSeconds/);
  assert.match(generateCreationSource, /videoScriptContentGoal:\s*preferences\.contentGoal/);
  assert.match(generateCreationSource, /videoScriptFormat:\s*preferences\.videoFormat/);
  assert.match(generateCreationSource, /videoScriptToneStyle:\s*preferences\.toneStyle/);
  assert.match(generateCreationSource, /videoScriptCustomRequirements:\s*preferences\.customRequirements/);
  assert.match(generateCreationSource, /setCreation\(\(currentCreation\) =>/);
  assert.match(generateCreationSource, /可在创作页面重试/);
  assert.match(generateCreationSource, /addToast\([^;]+,\s*"warning"\)/s);
});

test("image handoff parses the hot note and opens parse review before prompt reversal", () => {
  const setActivePageIndex = generateCreationSource.lastIndexOf('setActivePage("creation")');
  const extractIndex = generateCreationSource.indexOf("starxApi.extractLinkReference(");
  const stateIndex = generateCreationSource.lastIndexOf("showImageParseResult");

  assert.ok(extractIndex >= 0);
  assert.ok(stateIndex > extractIndex);
  assert.ok(setActivePageIndex > stateIndex);
  assert.doesNotMatch(generateCreationSource, /starxApi\.reversePrompt\(/);
  assert.match(generateCreationSource, /imageLinkPromptRows:\s*\[\]/);
  assert.match(generateCreationSource, /showImageParseResult:\s*true/);
  assert.match(generateCreationSource, /creationWizardStep:\s*0/);
  assert.match(generateCreationSource, /completedCreationWizardSteps:\s*\[\]/);
  assert.match(generateCreationSource, /image:\s*\{ currentStep:\s*0, completedSteps:\s*\[\] \}/);
  assert.doesNotMatch(generateCreationSource, /startImageTopicPromptPlan|applyImagePromptJobResult/);
  assert.doesNotMatch(generateCreationSource, /createImageJob/);
});

test("preference dialog supports accessible cancellation without handoff side effects", () => {
  assert.match(preferenceModalSource, /role="dialog"/);
  assert.match(preferenceModalSource, /aria-modal="true"/);
  assert.match(preferenceModalSource, /event\.key === "Escape"/);
  assert.match(preferenceModalSource, /const requestCancel = \(\) =>/);
  assert.match(preferenceModalSource, /onClick=\{requestCancel\}/);
  assert.match(preferenceModalSource, /type="button"[^>]*onClick=\{requestCancel\}/s);
  assert.doesNotMatch(preferenceModalSource, /generateCreation|navigate|activePage/);
});

test("preference dialog owns focus across first open and failure remount", () => {
  assert.match(preferenceModalSource, /const dialogRef = useRef\(null\)/);
  assert.match(preferenceModalSource, /const previouslyFocused = document\.activeElement/);
  assert.match(preferenceModalSource, /event\.key !== "Tab"/);
  assert.match(preferenceModalSource, /querySelectorAll/);
  assert.match(preferenceModalSource, /previouslyFocused\.focus\(\)/);
  assert.match(preferenceModalSource, /ref=\{dialogRef\}/);
  assert.match(preferenceModalSource, /tabIndex=\{-1\}/);
});

test("preference dialog exposes approved video controls and visible length validation", () => {
  assert.match(preferenceModalSource, /resolveCreationPreferenceVariant\(variant\)/);
  for (const label of ["目标平台", "视频时长", "内容目的", "视频形式", "表达风格", "补充要求（选填）"]) {
    assert.match(preferenceModalSource, new RegExp(label));
  }
  assert.match(preferenceModalSource, /customRequirements\.length > 500/);
  assert.match(preferenceModalSource, /补充要求不能超过 500 个字符/);
  assert.match(styles, /\.creation-preference-modal\s*\{/);
  assert.match(styles, /\.creation-preference-error\s*\{/);
});

test("preference dialog exposes the approved image controls", () => {
  assert.match(preferenceModalSource, /图片创作偏好/);
  for (const label of ["生成张数", "图片组织", "独立图片", "系列图", "图片比例", "创意程度", "视觉风格"]) {
    assert.match(imagePreferenceFieldsSource, new RegExp(label));
  }
  assert.match(imagePreferenceFieldsSource, /disabled=\{seriesDisabled\}/);
  assert.match(preferenceModalSource, /确认偏好并生成提示词/);
  assert.match(styles, /\.creation-preference-segments\s*\{/);
});
