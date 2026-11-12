import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import {
  buildVideoAnalysisDraftFields,
  formatVideoScriptLines,
  stripHashtagsFromTitle,
} from "../utils/videoAnalysis.js";

const styles = readFileSync(new URL("../styles/pages.css", import.meta.url), "utf8");
const indexHtml = readFileSync(new URL("../../index.html", import.meta.url), "utf8");
const contentCreationSource = readFileSync(new URL("./ContentCreation.jsx", import.meta.url), "utf8");
const appHookSource = readFileSync(new URL("../hooks/useStarxApp.js", import.meta.url), "utf8");
const imagePromptPlanEditorSource = readFileSync(new URL("../components/ImagePromptPlanEditor.jsx", import.meta.url), "utf8");
const imagePromptPlanHookSource = readFileSync(new URL("../hooks/useImagePromptPlanEditor.js", import.meta.url), "utf8");
const videoShootingCardsSource = readFileSync(new URL("../components/VideoShootingCardList.jsx", import.meta.url), "utf8");
const videoStoryboardSource = readFileSync(new URL("../components/VideoStoryboardTable.jsx", import.meta.url), "utf8");
const videoLinkAnalysisSource = readFileSync(new URL("../components/creation/kim/KimVideoReferenceStep.jsx", import.meta.url), "utf8");
const videoScriptStepSource = readFileSync(new URL("../components/creation/kim/KimVideoScriptStep.jsx", import.meta.url), "utf8");
const imagePromptStepSource = readFileSync(new URL("../components/creation/kim/KimImagePromptStep.jsx", import.meta.url), "utf8");
const tagSelectionPanelSource = readFileSync(new URL("../components/creation/TagSelectionPanel.jsx", import.meta.url), "utf8");
const newPromptTagModalUrl = new URL("../components/creation/NewPromptTagModal.jsx", import.meta.url);
const newPromptTagModalSource = existsSync(newPromptTagModalUrl) ? readFileSync(newPromptTagModalUrl, "utf8") : "";
const tagSelectionStyles = readFileSync(new URL("../styles/content-creation-tags.css", import.meta.url), "utf8");
const kimCreationStyles = readFileSync(new URL("../styles/content-creation-kim-exact.css", import.meta.url), "utf8");
const kimCreationHeaderSource = readFileSync(new URL("../components/creation/kim/KimCreationHeader.jsx", import.meta.url), "utf8");
const creationTypePickerSource = readFileSync(new URL("../components/creation/CreationTypePicker.jsx", import.meta.url), "utf8");
const creationTypePickerStyles = readFileSync(new URL("../styles/content-creation-type-picker.css", import.meta.url), "utf8");

test("blank content creation starts with the image or video type picker", () => {
  assert.match(appHookSource, /entryModeSelectionRequired:\s*true/);
  assert.match(contentCreationSource, /<CreationTypePicker onSelect=\{selectCreationType\}/);
  assert.match(contentCreationSource, /entryModeSelectionRequired:\s*false/);
  assert.match(creationTypePickerSource, /选择你的创作方式/);
  assert.match(creationTypePickerSource, /eyebrow:\s*"图文创作"/);
  assert.match(creationTypePickerSource, /eyebrow:\s*"视频创作"/);
  assert.match(creationTypePickerStyles, /\.creation-type-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(2/);
  assert.match(creationTypePickerStyles, /@media\s*\(max-width:\s*900px\)[\s\S]*grid-template-columns:\s*1fr/);
});

test("content creation header can switch between image and video modes", () => {
  assert.match(kimCreationHeaderSource, /aria-label="切换创作方式"/);
  assert.match(kimCreationHeaderSource, /\["image",\s*"图文创作"/);
  assert.match(kimCreationHeaderSource, /\["video",\s*"视频创作"/);
  assert.match(kimCreationHeaderSource, /onCreationTypeChange\?\.\(mode\)/);
  assert.match(contentCreationSource, /const changeCreationType = \(nextType\) =>/);
  assert.match(contentCreationSource, /type:\s*nextType/);
  assert.match(contentCreationSource, /creationType=\{type\}/);
  assert.match(contentCreationSource, /onCreationTypeChange=\{changeCreationType\}/);
});

test("upload preview uses readable image tiles with stable framing", () => {
  assert.match(styles, /\.upload-preview-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(100px,\s*1fr\)\)/);
  assert.match(styles, /\.upload-preview-item\s*\{[\s\S]*aspect-ratio:\s*9\/16/);
  assert.match(styles, /\.upload-zone\.has-preview\s*\{[\s\S]*padding:\s*var\(--space-lg\)/);
});

test("image material preview stays thumbnail-sized and preserves uploaded image framing", () => {
  assert.match(imagePromptStepSource, /material-upload-zone\$\{materialPreviews\.length \? " has-materials" : ""\}/);
  assert.match(styles, /\.material-preview-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(auto-fill,\s*minmax\(92px,\s*112px\)\)/);
  assert.match(styles, /\.material-preview-grid\s*\{[\s\S]*max-height:\s*154px/);
  assert.match(styles, /\.material-preview-item\s*\{[\s\S]*aspect-ratio:\s*1\s*\/\s*1/);
  assert.match(styles, /\.material-preview-item img\s*\{[\s\S]*object-fit:\s*contain/);
});

test("image reference upload supports selecting and managing multiple reference images", () => {
  const referenceStepSource = readFileSync(new URL("../components/creation/kim/KimImageReferenceStep.jsx", import.meta.url), "utf8");

  assert.match(referenceStepSource, /type="file"[^>]*multiple/);
  assert.match(referenceStepSource, /可多选|可一次选择多张/);
  assert.match(contentCreationSource, /const nextFiles = \[\.\.\.files, \.\.\.sf\]/);
  assert.match(contentCreationSource, /const nextPreviews = \[\.\.\.imagePreviews, \.\.\.previews\]/);
  assert.match(contentCreationSource, /const removeReferencePreview = useCallback/);
  assert.match(contentCreationSource, /onRemovePreview=\{removeReferencePreview\}/);
});

test("extracted video preview keeps a stable frame", () => {
  assert.match(styles, /\.video-preview-list video\s*\{[\s\S]*width:\s*100%/);
  assert.match(styles, /\.video-preview-list video\s*\{[\s\S]*aspect-ratio:\s*16\/9/);
});

test("extracted video preview does not leak the application referrer", () => {
  assert.match(indexHtml, /<meta\s+name="referrer"\s+content="no-referrer"\s*\/?>/);
});

test("video analysis result formats script lines for editing", () => {
  const text = formatVideoScriptLines([
    { timeRange: "00:00-00:03", text: "开场钩子" },
    { timeRange: "00:03-00:08", text: "矛盾展开" },
  ]);

  assert.equal(text, "[00:00-00:03] 开场钩子\n[00:03-00:08] 矛盾展开");
});

test("video analysis result builds editable draft fields", () => {
  const fields = buildVideoAnalysisDraftFields({
    videoScript: [{ timeRange: "00:00-00:03", text: "开场钩子" }],
    shotBreakdown: [{ shot: 1, timeRange: "00:00-00:03", script: "开场钩子" }],
    rewriteReferences: [{ title: "原结构复刻版", script: ["仿写脚本一", "仿写脚本二"] }],
    publishCopy: "随机挑战的一日三餐，结局比想象中更离谱。",
    replicationPrompt: "复刻提示词",
  });

  assert.equal(fields.copyText, "[00:00-00:03] 开场钩子");
  assert.equal(fields.publishCopy, "随机挑战的一日三餐，结局比想象中更离谱。");
  assert.equal(fields.scriptOriginalText, "镜头1 00:00-00:03 开场钩子");
  assert.equal(fields.scriptRewrittenText, "仿写脚本一\n仿写脚本二\n\n复刻提示词");
});

test("completed video analysis stores its storyboard package for the execution table", () => {
  assert.match(contentCreationSource, /buildVideoScriptPackageFromAnalysis\(result,/);
  assert.match(contentCreationSource, /setVideoScriptPackage\(\{ \.\.\.packageResult, sourceJobId: job\?\.id \|\| "" \}\)/);
});

test("video title removes extracted hashtags before filling the title field", () => {
  assert.equal(
    stripHashtagsFromTitle("随机地点随机食物随机一日三餐，都会发生什么离谱事情？ #美食 #搞笑 #随机挑战"),
    "随机地点随机食物随机一日三餐，都会发生什么离谱事情？",
  );
  assert.equal(stripHashtagsFromTitle("随机挑战#美食#搞笑"), "随机挑战");
});

test("image link analysis separates title tags and fills AI publish copy", () => {
  const extractSource = contentCreationSource.match(/const extractLink = useCallback[\s\S]*?const continueImageLinkFlow/)?.[0] || "";
  const imageAnalysisSource = contentCreationSource.match(/const continueImageLinkFlow = useCallback[\s\S]*?const generateImageLinkRows/)?.[0] || "";

  assert.match(extractSource, /stripHashtagsFromTitle\(fields\.title\)/);
  assert.match(extractSource, /description:\s*fields\.body/);
  assert.match(extractSource, /hashtags:\s*fields\.hashtags/);
  assert.match(imageAnalysisSource, /publishCopy: result\.publishCopy \|\| ""/);
  assert.match(imageAnalysisSource, /setCopyText\(generatedPublishCopy\)/);
  assert.match(imageAnalysisSource, /targetPlatform: effectiveTargetPlatform/);
  assert.match(appHookSource, /const cleanReferenceTitle = stripHashtagsFromTitle\(extractedLinkReference\.title\)/);
  assert.match(appHookSource, /showImageParseResult:\s*true/);
  assert.doesNotMatch(appHookSource.match(/const generateCreation = useCallback[\s\S]*?const reversePrompt = useCallback/)?.[0] || "", /starxApi\.reversePrompt\(/);
});

test("video link analysis stays visible before the Kim script editor", () => {
  const analysisIndex = contentCreationSource.indexOf("<KimVideoReferenceStep");
  const workstationIndex = contentCreationSource.indexOf("<KimVideoScriptStep");

  assert.ok(analysisIndex >= 0, "视频创作页应渲染独立的链接解析工作区");
  assert.ok(workstationIndex >= 0, "Kim 视频脚本编辑器应存在");
  assert.ok(analysisIndex < workstationIndex, "链接解析与 AI 分析入口必须位于脚本编辑器之前");
  assert.match(videoLinkAnalysisSource, /视频素材参考/);
  assert.match(videoLinkAnalysisSource, /开始解析/);
  assert.match(videoLinkAnalysisSource, /video-reference-cover/);
  assert.match(videoLinkAnalysisSource, /reference\?\.cover/);
  assert.match(videoLinkAnalysisSource, /video-reference-player/);
  assert.match(videoLinkAnalysisSource, /poster=\{coverUrl \|\| undefined\}/);
  assert.doesNotMatch(videoLinkAnalysisSource, /视频解析历史/);
  const extractFlow = contentCreationSource.match(/const analyzeVideoLink = async \(\) => \{[\s\S]*?\n  \};/)?.[0] || "";
  const continueFlow = contentCreationSource.match(/const continueVideoReferenceFlow = async \(\) => \{[\s\S]*?\n  \};/)?.[0] || "";
  assert.match(extractFlow, /extractLinkReference/);
  assert.doesNotMatch(extractFlow, /createVideoAnalysisJob/);
  assert.match(continueFlow, /createVideoAnalysisJob/);
  assert.match(contentCreationSource, /onClick=\{continueVideoReferenceFlow\}/);
});

test("video script workstation restores, loads, and polls only its active package job", () => {
  assert.match(contentCreationSource, /const \[activeVideoScriptJobId, setActiveVideoScriptJobId\] = useState\(app\.creation\.creationState\?\.activeVideoScriptJobId \|\| ""\)/);
  assert.match(contentCreationSource, /const activeVideoScriptJob = useMemo/);
  assert.match(contentCreationSource, /app\.creation\.creationState\?\.activeVideoScriptJobId/);
  assert.match(contentCreationSource, /stateJobIds = \[[\s\S]*activeVideoScriptJobId/);
  assert.match(contentCreationSource, /const pendingVideoScriptJobKey = useMemo/);
  assert.match(contentCreationSource, /pendingVideoScriptJobIds[\s\S]*refreshTrackedVideoScriptJob\(jobId\)[\s\S]*5000/);
  assert.match(contentCreationSource, /incomingActiveVideoScriptJobId/);
  assert.match(contentCreationSource, /resolveActiveVideoScriptJobId\(activeVideoScriptJobIdRef\.current, incomingActiveVideoScriptJobId\)/);
  assert.match(contentCreationSource, /app\.creation\.creationState\?\.activeVideoScriptJobId\]\)/);
});

test("missing active jobs stop silent polling after bounded failures and expose retry", () => {
  assert.match(contentCreationSource, /const VIDEO_SCRIPT_REFRESH_FAILURE_LIMIT = 3/);
  assert.match(contentCreationSource, /const \[videoScriptTrackingError, setVideoScriptTrackingError\] = useState\(null\)/);
  assert.match(contentCreationSource, /const refreshTrackedVideoScriptJob = useCallback/);
  assert.match(contentCreationSource, /advanceVideoScriptRefreshFailure/);
  assert.match(contentCreationSource, /videoScriptTrackingError\?\.jobId !== activeVideoScriptJobId/);
  assert.match(contentCreationSource, /const retryVideoScriptTracking = \(\) =>/);
  assert.match(contentCreationSource, /onReconnect=\{retryVideoScriptTracking\}/);
  assert.match(videoScriptStepSource, />重新连接<\/button>/);

  const trackingSource = contentCreationSource.match(/const refreshTrackedVideoScriptJob = useCallback[\s\S]*?const retryVideoScriptTracking = \(\) =>[\s\S]*?\n  };/)?.[0] || "";
  assert.doesNotMatch(trackingSource, /setVideoTitle|setVideoScriptOriginal|setVideoScriptRewritten|setVideoCopyText|setVideoPublishText|setVideoHashtags|setVideoBgmSuggestion/);
});

test("only the latest active completed video script job autofills the workstation", () => {
  assert.match(contentCreationSource, /const activeVideoScriptJobIdRef = useRef/);
  assert.match(contentCreationSource, /activeVideoScriptJobIdRef\.current = activeVideoScriptJobId/);
  assert.match(contentCreationSource, /completedJobId !== activeVideoScriptJobIdRef\.current/);
  assert.match(contentCreationSource, /buildVideoScriptDraftFields\(activeVideoScriptJob\.resultPayload \|\| \{\}\)/);
  assert.match(contentCreationSource, /appliedVideoScriptJobIdsRef\.current\.add\(completedJobId\)/);
  assert.match(contentCreationSource, /initialVideoScriptPackage\?\.sourceJobId === activeVideoScriptJobId/);
  assert.match(contentCreationSource, /sourceJobId: completedJobId/);
});

test("video preference changes require confirmation before regeneration", () => {
  assert.match(contentCreationSource, /import CreationPreferenceModal from "\.\.\/components\/CreationPreferenceModal"/);
  assert.match(contentCreationSource, />调整创作偏好<\/button>/);
  assert.match(contentCreationSource, /showVideoPreferences &&/);
  assert.match(contentCreationSource, /initialPreferences=\{videoPreferences\}/);
  assert.match(contentCreationSource, /variant="video"/);
  assert.match(contentCreationSource, /setPendingVideoPreferences\(preferences\)/);
  assert.match(contentCreationSource, /setShowVideoRegenerateConfirm\(true\)/);
  assert.match(contentCreationSource, /确认重新生成/);
  assert.match(contentCreationSource, /const confirmVideoScriptRegeneration = async \(\) =>/);
});

test("late image prompt ownership is adopted and loaded without replacing a newer local job", () => {
  assert.match(contentCreationSource, /resolveActiveImagePromptJobId/);
  assert.match(contentCreationSource, /incomingImagePromptJobId/);
  assert.match(contentCreationSource, /promptJobIdRef/);
  assert.match(contentCreationSource, /setPromptJobId\(nextPromptJobId\)/);
  assert.match(contentCreationSource, /\[app\.creation\.creationState\?\.imagePromptJobId, app\.creation\.creationState\?\.promptJobId\]/);
  assert.match(contentCreationSource, /const stateJobIds = \[\s*promptJobId,/);
  assert.match(contentCreationSource, /app\.creation\.creationId, activeVideoScriptJobId, promptJobId, refreshTrackedVideoScriptJob/);
  assert.match(contentCreationSource, /pendingPromptJobIds[\s\S]*app\.refreshGenerationJob\(jobId\)/);
});

test("active topic image prompt plan restores, polls, and applies only its owned completed job", () => {
  assert.match(contentCreationSource, /useImagePromptPlanEditor\(\{/);
  assert.match(contentCreationSource, /app\.creation\.creationState\?\.imagePromptPlan/);
  assert.match(contentCreationSource, /shouldApplyImagePromptPlanJob\(promptJobIdRef\.current, promptJob, appliedImagePromptJobIdsRef\.current\)/);
  assert.match(contentCreationSource, /buildEditableImagePromptPlan\(promptJob\.resultPayload/);
  assert.match(contentCreationSource, /appliedImagePromptJobIdsRef\.current\.add\(promptJob\.id\)/);
  assert.match(contentCreationSource, /pendingPromptJobIds[\s\S]*app\.refreshGenerationJob\(jobId\)/);
});

test("topic hot-note reversal restores directly into the per-image prompt confirmation step", () => {
  assert.match(contentCreationSource, /useState\(\s*app\.creation\.creationState\?\.imageLinkPromptRows \|\| \[\]\s*\)/);
  assert.match(contentCreationSource, /setImageLinkPromptRows\(app\.creation\.creationState\?\.imageLinkPromptRows \|\| \[\]\)/);
  assert.match(contentCreationSource, /imageLinkPromptRows,[\s\S]*creationWizardStep:\s*currentStep/);
  assert.match(contentCreationSource, /currentStep === 1 \? <KimLinkPromptStep/);
  assert.match(contentCreationSource, /onGenerate=\{generateImageLinkRows\}/);
});

test("topic image plan edits are persisted and one-card plans sync the legacy prompt", () => {
  assert.match(contentCreationSource, /imagePromptPlan,[\s\S]*imageCreationPreferences/);
  assert.match(contentCreationSource, /const buildCreationState = \(currentReference = resolveCurrentExtractReference\(\)\) => \(\{[\s\S]*imagePromptPlan,[\s\S]*imageCreationPreferences/);
  assert.match(imagePromptPlanHookSource, /if \(normalized\.cards\.length === 1\) onSinglePromptChange\(normalized\.cards\[0\]\.prompt\)/);
  assert.match(contentCreationSource, /<ImagePromptPlanEditor/);
});

test("prompt plan editor exposes editable cards, series constraints, and card operations", () => {
  assert.match(imagePromptPlanEditorSource, /图片 Prompt 计划/);
  assert.match(imagePromptPlanEditorSource, /value=\{card\.title\}/);
  assert.match(imagePromptPlanEditorSource, /value=\{card\.prompt\}/);
  assert.match(imagePromptPlanEditorSource, /value=\{plan\.sharedStyle\}/);
  assert.match(imagePromptPlanEditorSource, /onMoveCard/);
  assert.match(imagePromptPlanEditorSource, /onRemoveCard/);
  assert.match(imagePromptPlanEditorSource, /onAddCard/);
});

test("topic image plan generation creates a primary and variant per manual slot only after click", () => {
  const topicPlanBranch = contentCreationSource.match(
    /if \(imagePromptPlan\?\.cards\?\.length\) \{([\s\S]*?)\n\s*return;\n\s*\}/,
  )?.[1] || "";

  assert.match(contentCreationSource, /buildPromptPlanGenerationPayload\(\{/);
  assert.match(topicPlanBranch, /\.\.\.planPayload/);
  assert.doesNotMatch(topicPlanBranch, /variantsPerSlot\s*:/);
  assert.match(topicPlanBranch, /planPayload\.count \* planPayload\.variantsPerSlot/);
  assert.match(contentCreationSource, /onGenerate=\{createImages\}/);
  assert.match(imagePromptStepSource, /onClick=\{onGenerate\}/);
  assert.doesNotMatch(contentCreationSource, /useEffect\([\s\S]{0,500}app\.createImageJob/);
});

test("video package preferences and editable package are persisted", () => {
  assert.match(contentCreationSource, /latestSaveStateRef\.current = \{[\s\S]*activeVideoScriptJobId,[\s\S]*videoScriptPackage/);
  assert.match(contentCreationSource, /videoScriptDurationSeconds,[\s\S]*videoScriptContentGoal,[\s\S]*videoScriptFormat,[\s\S]*videoScriptToneStyle,[\s\S]*videoScriptCustomRequirements/);
  assert.match(contentCreationSource, /const buildCreationState = \(currentReference = resolveCurrentExtractReference\(\)\) => \(\{[\s\S]*activeVideoScriptJobId,[\s\S]*videoScriptPackage/);
});

test("video main flow uses Kim two-column editing while production details stay reachable", () => {
  assert.match(contentCreationSource, /<KimVideoScriptStep/);
  assert.match(videoScriptStepSource, /爆款原版脚本/);
  assert.match(videoScriptStepSource, /AI 改写版脚本/);
  assert.match(videoScriptStepSource, /发布文案/);
  assert.match(contentCreationSource, /<VideoShootingCardList packageResult=\{activeVideoScriptPackage\}/);
  assert.match(contentCreationSource, /BGM 建议/);
  assert.match(kimCreationStyles, /\.kim-creation-shell \.script-creation-grid\s*\{[\s\S]*grid-template-columns:\s*1fr 1fr/);
});

test("active video script failures keep edits and offer an explicit retry", () => {
  assert.match(contentCreationSource, /activeVideoScriptJob\?\.status === "failed"/);
  assert.match(contentCreationSource, /readableError\(activeVideoScriptJob\.error\)/);
  assert.match(contentCreationSource, /onRetry=\{scriptRewriteJob\?\.id === activeKimVideoScriptRewriteJobId \? rewriteVideoScript : retryVideoScriptGeneration\}/);
  assert.match(videoScriptStepSource, />重试生成<\/button>/);
  assert.match(contentCreationSource, /const retryVideoScriptGeneration = \(\) =>/);
});

test("storyboard displays the five production fields and keeps the drawer reuse", () => {
  for (const label of ["镜号", "时间", "画面内容", "景别 / 机位", "声音 / 旁白"]) {
    assert.match(videoStoryboardSource, new RegExp(label));
  }
  assert.match(videoStoryboardSource, /normalizeVideoShootingSegments/);
  assert.match(videoShootingCardsSource, /VideoStoryboardTable/);
  assert.match(contentCreationSource, /<VideoShootingCardList packageResult=\{activeVideoScriptPackage\}/);
  assert.match(contentCreationSource, /packageResult=\{activeVideoScriptPackage\}/);
});

test("initial prompt-plan POST failure without a job id exposes guarded retry", () => {
  assert.match(contentCreationSource, /imagePromptPlanStartError/);
  assert.match(contentCreationSource, /promptPlanRetrying/);
  assert.match(contentCreationSource, /disabled=\{promptPlanRetrying\}/);
  assert.match(contentCreationSource, /重新生成提示词/);
});

test("legacy rewrite cannot overwrite an active package workstation", () => {
  assert.match(contentCreationSource, /shouldApplyLegacyScriptRewrite\(\{/);
  assert.match(contentCreationSource, /activeVideoScriptJobId,/);
  assert.match(contentCreationSource, /trackedScriptRewriteJobId: scriptRewriteJobId/);
  assert.match(contentCreationSource, /legacyVideoFlowActive:/);
  assert.doesNotMatch(contentCreationSource, /scriptRewriteJob\?\.status==="completed"[\s\S]{0,240}setVideoScriptRewritten/);
});

test("confirmed video platform drives save and workflow publish handoff", () => {
  assert.match(contentCreationSource, /const normalizedVideoTargetPlatform = accountPlatforms\.includes\(videoScriptTargetPlatform\) \? videoScriptTargetPlatform : currentTargetPlatform/);
  assert.match(contentCreationSource, /const effectiveTargetPlatform = resolveCreationTargetPlatform\(type, currentTargetPlatform, normalizedVideoTargetPlatform\)/);
  assert.match(contentCreationSource, /publishSettings\?\.\[effectiveTargetPlatform\]/);
  assert.match(contentCreationSource, /submitCreationToWorkflow\(\{[\s\S]*targetPlatform:effectiveTargetPlatform/);
  assert.match(contentCreationSource, /publishMediaCandidates:\s*buildPublishMediaCandidates\(\)/);
  assert.match(contentCreationSource, /publishCopy:\s*type === "video" \? videoPublishText\.trim\(\) : copyText\.trim\(\)/);
  assert.doesNotMatch(contentCreationSource, /app\.publishCreation/);
  assert.match(contentCreationSource, /targetPlatform=\{effectiveTargetPlatform\}/);
});

test("explicit save persists only the current parsed image or video reference", () => {
  assert.match(contentCreationSource, /const currentExtractReference = resolveCurrentExtractReference\(\)/);
  assert.match(contentCreationSource, /type === "video" \? videoLinkReference : linkReference/);
  assert.match(contentCreationSource, /persistExtractAssets:\s*Boolean\(currentExtractReference/);
  assert.match(contentCreationSource, /extractHistoryId:\s*currentExtractReference\?\.historyId \|\| currentExtractReference\?\.id \|\| null/);
  assert.match(contentCreationSource, /saveScriptMaterial,/);
});

test("script material save uses the atomic explicit save request", () => {
  assert.match(contentCreationSource, /const saveScript = async \(\) => submitExplicit\(true\)/);
  assert.doesNotMatch(contentCreationSource, /const saveScript = async \(\) => \{ if \(app\.saveMaterial\)/);
});

test("auto save never requests extracted asset persistence", () => {
  assert.match(appHookSource, /persistExtractAssets:\s*false/);
  assert.match(appHookSource, /const \{ material, assetPersistence, \.\.\.task \} = response/);
  assert.match(appHookSource, /historyIds = \[assetPersistence\?\.historyId \|\| payload\.extractHistoryId\]\.filter\(Boolean\)/);
});

test("asset persistence state has visible pending completed and fallback labels", () => {
  assert.match(contentCreationSource, /pending:\s*"资源转存中"/);
  assert.match(contentCreationSource, /completed:\s*"资源已转存"/);
  assert.match(contentCreationSource, /fallback:\s*"转存失败，当前使用源链接"/);
});

test("editable video state persists without waiting for a generated package", () => {
  assert.match(contentCreationSource, /buildPersistedVideoScriptPackage\(videoScriptPackage, \{/);
  assert.match(contentCreationSource, /title: videoTitle/);
  assert.match(contentCreationSource, /restoreVideoScriptDraft\(\{/);
  assert.match(contentCreationSource, /setVideoTitle\(restoredVideoDraft\.title\)/);
  assert.doesNotMatch(contentCreationSource, /videoScriptPackage \? \{[\s\S]{0,400}\} : null/);
});

test("workstation regeneration inserts the posted job into generation state", () => {
  assert.match(contentCreationSource, /app\.createVideoScriptJob\(\{/);
  assert.doesNotMatch(contentCreationSource, /starxApi\.createVideoScriptJob\(app\.currentAccountId/);
  assert.match(appHookSource, /const createVideoScriptJob = useCallback\(/);
  assert.match(appHookSource, /starxApi\.createVideoScriptJob\(currentAccountId, payload\)/);
  assert.match(appHookSource, /upsertGenerationJob\(job\)/);
  assert.match(appHookSource, /state\.activeVideoScriptJobId/);
  assert.match(appHookSource, /createVideoScriptJob,[\s\S]*createVideoAnalysisJob/);
});

test("video creation submits video-specific draft fields", () => {
  assert.match(contentCreationSource, /const buildContentPayload = \(\) => \{\s*if \(type === "video"\)/);
  assert.match(contentCreationSource, /scriptOriginal:\s*linesFromText\(videoScriptOriginal\)/);
  assert.match(contentCreationSource, /scriptRewritten:\s*linesFromText\(videoScriptRewritten\)/);
  assert.match(contentCreationSource, /title:\s*videoTitle\.trim\(\)\|\|app\.creation\.topicTitle\|\|"未命名创作"/);
  assert.match(contentCreationSource, /body:\s*videoCopyText\.trim\(\)/);
  assert.match(contentCreationSource, /hashtags:\s*linesFromText\(videoHashtags\.replaceAll/);
});

test("content creation restores autostarted prompt and script jobs", () => {
  assert.match(contentCreationSource, /const \[promptJobId, setPromptJobId\] = useState\(app\.creation\.creationState\?\.promptJobId \|\| ""\)/);
  assert.match(contentCreationSource, /const \[scriptRewriteJobId, setScriptRewriteJobId\] = useState\(app\.creation\.creationState\?\.scriptRewriteJobId \|\| ""\)/);
  assert.match(contentCreationSource, /app\.creation\.creationState\?\.promptJobId/);
  assert.match(contentCreationSource, /app\.creation\.creationState\?\.scriptRewriteJobId/);
  assert.match(contentCreationSource, /const promptJob = useMemo/);
  assert.match(contentCreationSource, /promptJob\?\.status !== "completed"[\s\S]*mode === "topic_image_plan"[\s\S]*setPrompt/);
  assert.match(contentCreationSource, /shouldApplyLegacyScriptRewrite\(\{[\s\S]*trackedScriptRewriteJobId: scriptRewriteJobId/);
});

test("pending script rewrite jobs are refreshed until completion", () => {
  assert.match(contentCreationSource, /const pendingScriptRewriteJobKey = useMemo/);
  assert.match(contentCreationSource, /scriptRewriteJob && \["pending", "running"\]\.includes\(scriptRewriteJob\.status\)/);
  assert.match(contentCreationSource, /pendingScriptRewriteJobKey\.split\("\|"\)\.filter\(Boolean\)/);
  assert.match(contentCreationSource, /pendingScriptRewriteJobIds\.forEach\(\(jobId\) => \{\s*app\.refreshGenerationJob\(jobId\)\.catch\(\(\) => \{\}\)/);
  assert.match(contentCreationSource, /\}, 5000\);[\s\S]*window\.clearInterval\(timer\);[\s\S]*pendingScriptRewriteJobKey/);
});

test("submission accepts original script content", () => {
  assert.match(contentCreationSource, /if \(!cp\.body&&!cp\.scriptOriginal\.length&&!cp\.scriptRewritten\.length&&!cp\.imagePrompt\)/);
});

test("image creation exposes editable publish copy", () => {
  assert.match(contentCreationSource, /<label className="field-label">发布文案<\/label>/);
  assert.match(contentCreationSource, /<textarea value=\{copyText\} onChange=\{\((?:e|event)\) => imagePromptPlan \? changeImagePromptPlanField\("publishCopy", (?:e|event)\.target\.value\) : setCopyText\((?:e|event)\.target\.value\)\}/);
  assert.match(contentCreationSource, /body:\s*copyText\.trim\(\)/);
});

test("content creation uses Kim wizard while retaining develop workflows", () => {
  assert.match(contentCreationSource, /import LoadingOverlay from "\.\.\/components\/creation\/LoadingOverlay"/);
  assert.match(contentCreationSource, /import KimStepWizard from "\.\.\/components\/creation\/kim\/KimStepWizard"/);
  assert.match(contentCreationSource, /import \{ getKimCreationSteps \} from "\.\.\/components\/creation\/kim\/kimCreationContract"/);
  assert.match(contentCreationSource, /const IMAGE_STEPS = getKimCreationSteps\("image"\)/);
  assert.match(contentCreationSource, /const VIDEO_STEPS = getKimCreationSteps\("video"\)/);
  assert.match(contentCreationSource, /creationWizardStep/);
  assert.match(contentCreationSource, /completedCreationWizardSteps/);
  assert.match(contentCreationSource, /const completeStep = useCallback\(/);
  assert.match(contentCreationSource, /const handleStepClick = useCallback\(/);
  assert.match(contentCreationSource, /<KimStepWizard/);
  assert.match(contentCreationSource, /className="creation-page kim-creation-shell"/);
  assert.match(contentCreationSource, /className="creation-step-actions"/);
  assert.match(contentCreationSource, /currentStep === 0/);
  assert.match(contentCreationSource, /currentStep === 1/);
  assert.match(contentCreationSource, /currentStep === 2/);
  assert.match(styles, /\.creation-wizard-card\s*\{/);
  assert.match(styles, /\.creation-step-actions\s*\{/);
  assert.match(kimCreationStyles, /@media\s*\(max-width:\s*768px\)[\s\S]*\.kim-creation-shell \.script-creation-grid,[\s\S]*grid-template-columns:\s*1fr/);
  assert.match(styles, /\.creation-account-type\s*\{[\s\S]*white-space:\s*nowrap/);
  assert.match(styles, /\.kim-creation-shell \.creation-topline \.section-header-right\s*\{[\s\S]*flex-wrap:\s*nowrap/);
  assert.match(contentCreationSource, /onNewCreation=\{startNewCreation\}/);
  assert.match(contentCreationSource, /newCreationDisabled=\{currentStep <= 0\}/);
  assert.match(contentCreationSource, /const startNewCreation = useCallback/);
  assert.match(contentCreationSource, /window\.confirm\("是否放弃当前操作并重新开始？"\)/);
  assert.match(contentCreationSource, /app\.startBlankCreation/);
  assert.match(kimCreationHeaderSource, /新建创作/);
  assert.match(styles, /\.creation-new-btn\s*\{/);
  assert.equal((contentCreationSource.match(/下一步：生成与保存/g) || []).length, 0);

  // develop 的任务恢复、轮询和可编辑稿件仍是唯一业务实现。
  assert.match(contentCreationSource, /pendingScriptRewriteJobKey/);
  assert.match(contentCreationSource, /pendingImageJobKey/);
  assert.match(contentCreationSource, /restorePersistedImagePromptPlan/);
  assert.match(contentCreationSource, /restoreVideoScriptDraft/);
});

test("creation wizard maps real busy state and persists workflow publish handoff", () => {
  assert.match(contentCreationSource, /const loadingOverlayMessage = extractingLink/);
  assert.match(contentCreationSource, /<LoadingOverlay/);
  assert.match(contentCreationSource, /const buildPublishMediaCandidates = \(\) =>/);
  assert.ok(
    (contentCreationSource.match(/publishMediaCandidates/g) || []).length >= 3,
    "重新生成后的图片候选需要同步到本地状态、自动保存和流程交接",
  );
  assert.match(contentCreationSource, /publishMediaCandidates:\s*buildPublishMediaCandidates\(\)/);
  assert.match(contentCreationSource, /publishCopy:\s*type === "video" \? videoPublishText\.trim\(\) : copyText\.trim\(\)/);
  assert.match(contentCreationSource, /creationWizardStep:\s*currentStep/);
  assert.match(contentCreationSource, /completedCreationWizardSteps:\s*completedSteps/);
  assert.match(contentCreationSource, /creationWizardProgressByType/);
});

test("image regeneration keeps the active reference and material inputs", () => {
  assert.match(contentCreationSource, /regenerateSlotId: group\.slotId,[\s\S]{0,420}referenceImages: useOriginalAsReference \? files : \[\]/);
  assert.match(contentCreationSource, /regenerateSlotId: group\.slotId,[\s\S]{0,520}materialImages: materialFiles/);
  assert.match(contentCreationSource, /regenerateSlotId: group\.slotId,[\s\S]{0,600}referenceStrength,[\s\S]{0,60}materialStrength/);
});

test("video link analysis keeps the Kim loading animation until analysis polling finishes", () => {
  assert.match(contentCreationSource, /const videoAnalysisLoading = Boolean\(/);
  assert.match(contentCreationSource, /busy === "video-extract"/);
  assert.match(contentCreationSource, /busy === "video-analysis"/);
  assert.match(contentCreationSource, /activeVideoAnalysisJob\?\.id === videoAnalysisJobId/);
  assert.match(contentCreationSource, /\["pending", "running"\]\.includes\(activeVideoAnalysisJob\.status\)/);
  assert.match(contentCreationSource, /loadingOverlayMessage \|\| videoAnalysisLoading \|\| videoTopicScriptLoading \|\| imageGenerationLoading/);
  assert.match(contentCreationSource, /"正在分析视频内容\.\.\."/);
  assert.match(contentCreationSource, /分析完成后会自动进入脚本创作/);
  assert.match(contentCreationSource, /busy=\{videoAnalysisLoading \? \(busy \|\| "video-analysis"\) : busy\}/);
});

test("topic video creation keeps the Kim loading animation until script generation finishes", () => {
  assert.match(contentCreationSource, /const videoTopicScriptLoading = Boolean\(/);
  assert.match(contentCreationSource, /activeVideoScriptJobId/);
  assert.match(contentCreationSource, /\["pending", "running"\]\.includes\(activeVideoScriptJob\.status\)/);
  assert.match(contentCreationSource, /loadingOverlayMessage \|\| videoAnalysisLoading \|\| videoTopicScriptLoading \|\| imageGenerationLoading/);
  assert.match(contentCreationSource, /"AI 正在生成视频脚本\.\.\."/);
  assert.match(contentCreationSource, /subMessage=\{[\s\S]*videoTopicScriptLoading[\s\S]*脚本生成完成后会自动进入编辑页/);
});

test("completed topic video script advances to the Kim script creation step", () => {
  const completionEffect = contentCreationSource.match(/if \(activeVideoScriptJob\?\.status !== "completed"\) return;[\s\S]*?app\.addToast\("视频脚本包已生成，可继续编辑", "success"\);/)?.[0] || "";
  assert.match(completionEffect, /completeStep\(0, 1, "video"\)/);
  assert.doesNotMatch(completionEffect, /completeStep\(1, 1, "video"\)/);
});

test("workflow publish state stays isolated from the currently edited creation", () => {
  assert.match(appHookSource, /import \{ createWorkflowPublishRequestGate \} from "\.\.\/utils\/workflowPublish"/);
  assert.match(appHookSource, /const \[publishStates, setPublishStates\] = useState\(\{\}\)/);
  assert.match(appHookSource, /const workflowPublishRequestGateRef = useRef\(createWorkflowPublishRequestGate\(\)\)/);
  assert.match(appHookSource, /const loadTaskCreation = useCallback/);
  assert.match(appHookSource, /const savedCreation = await starxApi\.getCreation\(requestAccountId, task\.creationId\)/);
  assert.match(appHookSource, /const persistedPublishState = savedCreation\.creationState\?\.publish/);
  assert.match(appHookSource, /setPublishStates\(\(prev\) => \(\{ \.\.\.prev, \[creationId\]: recorded \}\)\)/);
  assert.ok(
    (appHookSource.match(/prev\.creationId === creationId/g) || []).length >= 2,
    "发布和刷新都必须只更新同一条当前创作",
  );
  assert.ok(
    (appHookSource.match(/setPublishStates\(\{\}\)/g) || []).length >= 2,
    "账号切换和退出登录都必须清理发布状态",
  );
  assert.ok(
    (appHookSource.match(/workflowPublishRequestGateRef\.current\.reset\(\)/g) || []).length >= 2,
    "账号生命周期切换必须使旧发布请求失效",
  );
  assert.match(appHookSource, /begin\(`publish:\$\{creationId\}`/);
  assert.match(appHookSource, /begin\("load-task-creation"/);
  assert.match(appHookSource, /publishStates,[\s\S]*loadTaskCreation,/);
});

test("image generation keeps the Kim loading animation until every image job finishes", () => {
  const loadingMapping = contentCreationSource.match(
    /const loadingOverlayMessage = extractingLink[\s\S]*?const completeStep/,
  )?.[0] || "";

  assert.match(contentCreationSource, /const imageGenerationLoading = submitting \|\| pendingImageJobs\.length > 0/);
  assert.match(contentCreationSource, /loadingOverlayMessage \|\| videoAnalysisLoading \|\| videoTopicScriptLoading \|\| imageGenerationLoading/);
  assert.match(contentCreationSource, /message=\{loadingOverlayMessage \|\| \(imageGenerationLoading \? "正在生成图片\.\.\." : videoAnalysisLoading \? "正在分析视频内容\.\.\." : "AI 正在生成视频脚本\.\.\."\)\}/);
  assert.match(loadingMapping, /submitting/);
  assert.match(contentCreationSource, /const activeImageJobTerminal = Boolean/);
  assert.match(contentCreationSource, /if \(!pendingImageJobs\.length && activeImageJobTerminal\) setGenerating\(false\)/);
  assert.match(contentCreationSource, /\[activeImageJobTerminal, pendingImageJobs\.length\]/);
});

test("prompt-plan retry remains visible after advancing to generation", () => {
  assert.match(contentCreationSource, /currentStep >= 1 && \(promptJobId \|\| imagePromptPlanStartError\) && !imagePromptPlan/);
  assert.match(contentCreationSource, /onClick=\{retryImagePromptPlan\}/);
});

test("prompt-plan retry supports image topics without a reference note", () => {
  const retrySource = contentCreationSource.match(
    /const retryImagePromptPlan = useCallback\(async \(\) => \{[\s\S]*?\/\* image generation/,
  )?.[0] || "";

  assert.match(retrySource, /if \(!\(retryReference\?\.images \|\| \[\]\)\.length && referenceUrl\)/);
  assert.match(retrySource, /if \(referenceUrl && !retryReferenceUrls\.length\)/);
  assert.match(retrySource, /if \(retryReferenceUrls\.length\) retryPayload\.referenceUrls = retryReferenceUrls/);
  assert.doesNotMatch(retrySource, /if \(!referenceUrl/);
});

test("creation restore assigns link references to the owning media type", () => {
  assert.match(contentCreationSource, /if \(restoredType === "video"\) \{[\s\S]*setVideoLinkReference\(ref\)[\s\S]*setVideoLinkText\(restoredLinkText\)[\s\S]*setLinkReference\(null\)[\s\S]*setLinkText\(""\)/);
  assert.match(contentCreationSource, /else \{[\s\S]*setLinkReference\(ref\)[\s\S]*setLinkText\(restoredLinkText\)[\s\S]*setVideoLinkReference\(null\)[\s\S]*setVideoLinkText\(""\)/);
  assert.match(contentCreationSource, /useEffect\(\(\) => \{\s*if \(app\.creation\.type === "video"\) return;\s*const ref = app\.creation\.creationState\?\.linkReference[\s\S]*setLinkReference\(\(current\) => current \|\| ref\)/);
});

test("autosave persists the active media type reference without erasing video state", () => {
  assert.match(contentCreationSource, /const activeLinkReference = type === "video" \? videoLinkReference : linkReference/);
  assert.match(contentCreationSource, /const activeLinkText = type === "video" \? videoLinkText : linkText/);
  assert.ok((contentCreationSource.match(/linkReference:\s*activeLinkReference/g) || []).length >= 2);
  assert.ok((contentCreationSource.match(/linkText:\s*activeLinkText/g) || []).length >= 2);
  assert.ok((contentCreationSource.match(/videoLinkReference, videoLinkText/g) || []).length >= 3);
});

test("wizard advances only after the owning flow succeeds", () => {
  const analyzeSource = contentCreationSource.match(/const analyzeVideoLink = async \(\) => \{[\s\S]*?const selectVideoAnalysisJob/)?.[0] || "";
  const applySource = contentCreationSource.match(/const applyVideoAnalysisResult = \(job\) => \{[\s\S]*?\n  \};/)?.[0] || "";
  const createImagesSource = contentCreationSource.match(/\/\* image generation[\s\S]*?\/\* regenerate slot \*\//)?.[0] || "";
  const submitSource = contentCreationSource.match(/const submitExplicit = async \(saveScriptMaterial = false\) => \{[\s\S]*?\n  \};/)?.[0] || "";

  assert.doesNotMatch(analyzeSource, /completeStep/);
  assert.doesNotMatch(createImagesSource, /completeStep/);
  assert.match(applySource, /completeStep\(0, 1, "video"\)/);
  assert.match(contentCreationSource, /activeVideoAnalysisJob\.status !== "completed"/);
  assert.match(contentCreationSource, /appliedVideoAnalysisJobIdsRef\.current\.add\(activeVideoAnalysisJob\.id\)[\s\S]*applyVideoAnalysisResult\(activeVideoAnalysisJob\)/);
  assert.match(contentCreationSource, /activeCreationTypeRef\.current === targetType/);
  assert.match(contentCreationSource, /completeStep\(0, 1, "image"\)/);
  assert.match(contentCreationSource, /completedJobs\.forEach[\s\S]*completeStep\(2, 2, "image"\)/);
  assert.match(submitSource, /completedCreationWizardSteps:\s*finalCompletedSteps/);
  assert.match(submitSource, /completeStep\(finalStep, finalStep, type\)/);
});

test("image creation directly uses Kim fixed-category filters instead of develop pagination", () => {
  assert.match(contentCreationSource, /<KimTagSelectionStep/);
  assert.match(tagSelectionPanelSource, /fixedCategories = \(categories \|\| \[\]\)\.filter/);
  assert.match(tagSelectionPanelSource, /className="creation-tag-filter"/);
  assert.doesNotMatch(tagSelectionPanelSource, /tagCategoryPage|tag-category-pagination|上一类|下一类/);
});

test("image creation shows advanced prompt controls without folding", () => {
  assert.doesNotMatch(contentCreationSource, /showNegative/);
  assert.doesNotMatch(contentCreationSource, /setShowNegative/);
  assert.doesNotMatch(contentCreationSource, /负向提示词 \/ 高级设置/);
  assert.match(imagePromptStepSource, /className="prompt-advanced-grid"/);
  assert.match(imagePromptStepSource, /<label className="field-label">负向提示词<\/label>/);
  assert.match(styles, /\.prompt-advanced-grid\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1\.2fr\) minmax\(260px, \.8fr\)/);
});

test("video publish uses a dedicated publish copy field", () => {
  assert.match(contentCreationSource, /const \[videoPublishText, setVideoPublishText\] = useState/);
  assert.match(videoScriptStepSource, /发布文案/);
  assert.match(contentCreationSource, /publishCopy=\{videoPublishText\}/);
  assert.match(contentCreationSource, /onPublishCopyChange=\{setVideoPublishText\}/);
  assert.match(contentCreationSource, /videoPublishText,\s*videoAnalysisJobId/);
  assert.match(contentCreationSource, /publishCopy:\s*type === "video" \? videoPublishText\.trim\(\) : copyText\.trim\(\)/);
});

test("saving to workflow allows an empty publish copy", () => {
  const saveToWorkflowSource = contentCreationSource.match(
    /const handleSaveToWorkflow = async \(\) => \{[\s\S]*?\n  \};/,
  )?.[0] || "";

  assert.match(saveToWorkflowSource, /await submitExplicit\(false\)/);
  assert.doesNotMatch(saveToWorkflowSource, /publishCopy|videoPublishText|copyText|请先填写发布文案/);
});

test("completing creation navigates to workflow management only after a successful save", () => {
  const saveToWorkflowSource = contentCreationSource.match(
    /const handleSaveToWorkflow = async \(\) => \{[\s\S]*?\n  \};/,
  )?.[0] || "";

  const submitIndex = saveToWorkflowSource.indexOf("await submitExplicit(false)");
  const closeIndex = saveToWorkflowSource.indexOf("setShowWorkflowModal(false)");
  const navigateIndex = saveToWorkflowSource.indexOf('app.setActivePage?.("process")');
  assert.ok(submitIndex >= 0);
  assert.ok(closeIndex > submitIndex);
  assert.ok(navigateIndex > closeIndex);
  assert.match(saveToWorkflowSource, /if \(readyForWorkflowCompletion\)/);
});

test("creation keeps target-platform handoff without exposing direct publish", () => {
  assert.doesNotMatch(contentCreationSource, /const publishDirectly = async \(\) =>/);
  assert.doesNotMatch(contentCreationSource, /app\.publishCreation\(/);
  assert.doesNotMatch(contentCreationSource, /app\.refreshPublishStatus/);
  assert.match(contentCreationSource, /const accountPlatforms = app\.currentAccount\?\.platforms\?\.length/);
  assert.match(contentCreationSource, /const currentTargetPlatform = accountPlatforms\.includes\(app\.creation\.targetPlatform\) \? app\.creation\.targetPlatform : accountPlatforms\[0\]/);
  assert.match(contentCreationSource, /targetPlatform:effectiveTargetPlatform/);
  assert.match(contentCreationSource, /publishMediaCandidates:\s*buildPublishMediaCandidates\(\)/);
  assert.doesNotMatch(contentCreationSource, /发布作品/);
});

test("creation keeps device readiness data while Kim header owns the main flow", () => {
  assert.doesNotMatch(contentCreationSource, /const \[showPublishConfirm, setShowPublishConfirm\] = useState\(false\)/);
  assert.match(contentCreationSource, /const publishSetting = app\.currentAccount\?\.publishSettings\?\.\[effectiveTargetPlatform\]/);
  assert.match(contentCreationSource, /const publishDeviceConfigured = Boolean\(publishSetting\?\.androidId\)/);
  assert.match(contentCreationSource, /targetPlatform=\{effectiveTargetPlatform\}/);
  assert.doesNotMatch(contentCreationSource, /className=\{`publish-config-chip/);
  assert.match(contentCreationSource, /<KimWorkflowSaveModal/);
  assert.doesNotMatch(contentCreationSource, /发布前确认/);
  assert.doesNotMatch(contentCreationSource, /const confirmPublish = async \(\) =>/);
});

test("creation page no longer owns publish status polling", () => {
  assert.doesNotMatch(contentCreationSource, /const publishState = app\.creation\.creationState\?\.publish \|\| null/);
  assert.doesNotMatch(contentCreationSource, /app\.refreshPublishStatus/);
  assert.doesNotMatch(contentCreationSource, /className="publish-status-bar"/);
});

test("creation page no longer owns publish timeline or recovery actions", () => {
  assert.doesNotMatch(contentCreationSource, /const publishTimelineSteps = \[/);
  assert.doesNotMatch(contentCreationSource, /className="publish-status-timeline"/);
  assert.doesNotMatch(contentCreationSource, /className="publish-failure-actions"/);
});

test("pending video analysis jobs are refreshed until completion", () => {
  assert.match(contentCreationSource, /const pendingVideoAnalysisJobKey = useMemo\(\(\) => relatedVideoAnalysisJobs\.filter/);
  assert.match(contentCreationSource, /\["pending", "running"\]\.includes\(job\.status\)/);
  assert.match(contentCreationSource, /pendingVideoAnalysisJobKey\.split\("\|"\)\.filter\(Boolean\)/);
  assert.match(contentCreationSource, /app\.refreshVideoAnalysisJob\(jobId\)\.catch\(\(\) => \{\}\)/);
  assert.match(contentCreationSource, /\}, 5000\);[\s\S]*window\.clearInterval\(timer\);[\s\S]*pendingVideoAnalysisJobKey/);
});

test("image variant groups have stable candidate card styles", () => {
  assert.match(styles, /\.image-result-grid\s*\{[\s\S]*display:\s*grid/);
  assert.match(styles, /\.result-variant-card\s*\{[\s\S]*aspect-ratio:\s*9\/16/);
  assert.match(styles, /\.result-variant-card\.selected\s*\{[\s\S]*background/);
});

test("selected prompt tag chips are read-only summaries instead of delete controls", () => {
  assert.doesNotMatch(
    contentCreationSource,
    /className="selected-tag-chip"\s+onClick=\{\(\) => toggleTag\(id\)\}/
  );
  assert.doesNotMatch(styles, /\.selected-tag-chip:hover\{[^}]*var\(--err\)/);
});

test("custom prompt tag deletion is moved into a dedicated management modal", () => {
  assert.doesNotMatch(contentCreationSource, /className="custom-tag-delete"/);
  assert.match(contentCreationSource, /setShowTagManagerModal\(true\)/);
  assert.match(contentCreationSource, /showTagManagerModal &&/);
  assert.match(contentCreationSource, /className="tag-manager-list"/);
  assert.match(contentCreationSource, /className="btn btn-xs btn-danger tag-manager-delete"[\s\S]*deleteCustomTag\(tag\.id\)/);
});

test("each prompt tag category can open a category-locked creation modal", () => {
  assert.match(tagSelectionPanelSource, /onCreateTag/);
  assert.match(tagSelectionPanelSource, /onClick=\{\(\) => onCreateTag\(category\.id\)\}/);
  assert.match(tagSelectionPanelSource, /aria-label=\{`在\$\{ui\.label\}下新增标签`\}/);
  assert.match(contentCreationSource, /import NewPromptTagModal from "\.\.\/components\/creation\/NewPromptTagModal"/);
  assert.match(contentCreationSource, /onCreateTag=\{openNewTagModal\}/);
  assert.match(contentCreationSource, /<NewPromptTagModal/);
  assert.match(contentCreationSource, /category=\{newTagCategoryDetails\}/);
  assert.match(newPromptTagModalSource, /所属分类/);
  assert.match(newPromptTagModalSource, /category\.label/);
  assert.doesNotMatch(newPromptTagModalSource, /<select/);
  assert.match(newPromptTagModalSource, /await onSubmit\(\{[\s\S]*category: category\.id/);
  assert.match(newPromptTagModalSource, /创建中…/);
  assert.match(tagSelectionStyles, /\.creation-add-tag/);
  assert.match(tagSelectionStyles, /\.new-prompt-tag-modal/);
});

test("image generation results sync from tracked jobs and remain visible while running", () => {
  assert.match(contentCreationSource, /const \[imageJobIds, setImageJobIds\]/);
  assert.match(contentCreationSource, /setImageJobIds\(\(prev\) => addUniqueId\(prev, job\.id\)\)/);
  assert.match(contentCreationSource, /useEffect\(\(\) => \{[\s\S]*normalizeImageGroups\(job\)[\s\S]*mergeImageGroups/);
  assert.match(contentCreationSource, /const pendingImageJobKey = useMemo\(\(\) => pendingImageJobs\.map\(\(job\) => job\.id\)\.join\("\|"\), \[pendingImageJobs\]\)/);
  assert.match(contentCreationSource, /window\.setInterval\([\s\S]*pendingImageJobIds[\s\S]*refreshGenerationJob\(jobId\)[\s\S]*5000\)/);
  assert.match(contentCreationSource, /window\.clearInterval\(timer\)/);
  assert.doesNotMatch(contentCreationSource, /\}, \[app\.refreshGenerationJob, pendingImageJobs\]\)/);
  assert.match(contentCreationSource, /imageGroups=\{imageGroups\}/);
  assert.match(contentCreationSource, /generating=\{generating\}/);
  assert.match(contentCreationSource, /submitting=\{submitting\}/);
  assert.match(imagePromptStepSource, /className="image-result-panel"/);
});

test("image generation submits uploaded and linked reference images", () => {
  assert.match(contentCreationSource, /buildGenerationSlots\(\{[\s\S]*files,[\s\S]*imagePreviews,[\s\S]*linkReferenceImages/);
  assert.match(contentCreationSource, /const \[useOriginalAsReference, setUseOriginalAsReference\]/);
  assert.match(contentCreationSource, /referenceImages:\s*useOriginalAsReference \? files : \[\]/);
  assert.match(contentCreationSource, /referenceUrls:\s*useOriginalAsReference[\s\S]*linkReferenceImages\.map/);
  assert.match(contentCreationSource, /materialImages:\s*materialFiles/);
  assert.doesNotMatch(contentCreationSource, /slots: Array\.from\(\{ length: genCount \}/);
});

test("reference input is preserved after image generation starts", () => {
  const createImagesSource = contentCreationSource.match(/\/\* image generation[\s\S]*?\/\* regenerate slot \*\//)?.[0] || "";

  assert.match(contentCreationSource, /latestSaveStateRef\.current = \{[\s\S]*linkReference,[\s\S]*linkText,[\s\S]*useOriginalAsReference/);
  assert.match(contentCreationSource, /creationState: \{[\s\S]*linkReference,[\s\S]*linkText,[\s\S]*useOriginalAsReference/);
  assert.match(contentCreationSource, /const buildCreationState = \(currentReference = resolveCurrentExtractReference\(\)\) => \(\{[\s\S]*linkReference:\s*currentReference,[\s\S]*linkText,[\s\S]*useOriginalAsReference/);
  assert.doesNotMatch(contentCreationSource, /\}, \[app\.creation, app\.extractHistories\]\)/);
  assert.doesNotMatch(createImagesSource, /clearFiles\(\)/);
  assert.doesNotMatch(createImagesSource, /setLinkReference\(null\)|setLinkText\(""\)/);
});

test("recent image job click restores its reference input", () => {
  assert.match(contentCreationSource, /function buildReferenceFromImageJob\(job\)/);
  assert.match(contentCreationSource, /const input = getJobInputPayload\(job\)/);
  assert.match(contentCreationSource, /asset\.assetType === "reference"/);
  assert.match(contentCreationSource, /setLinkReference\(ref\)/);
  assert.match(contentCreationSource, /setUseOriginalAsReference\(Boolean\(ref\) \|\| Boolean\(input\.referenceImageCount\) \|\| Boolean\(input\.referenceUrlCount\)\)/);
  assert.match(contentCreationSource, /applyImageJobReferenceInput\(j\)/);
  assert.match(contentCreationSource, /applyImageJobReferenceInput\(fullJob\)/);
});

test("recent job titles are truncated before rendering and cannot stretch the sidebar", () => {
  assert.match(contentCreationSource, /const truncateJobText = \(text, maxLength = 30\) =>/);
  assert.match(contentCreationSource, /const jobTitle = truncateJobText\(/);
  assert.match(contentCreationSource, /const displayTitle = truncateJobText\(/);
  assert.match(styles, /\.job-list button\s*\{[\s\S]*min-width:\s*0/);
  assert.match(styles, /\.job-title\s*\{[\s\S]*min-width:\s*0/);
  assert.match(styles, /\.job-title\s*\{[\s\S]*max-width:\s*100%/);
});

test("reverse prompt results are visible and not hidden as generation jobs", () => {
  assert.match(contentCreationSource, /const \[reverseHistories, setReverseHistories\]/);
  assert.match(contentCreationSource, /setImageTabActive\("input"\)/);
  assert.match(imagePromptStepSource, /className="reverse-result-text"/);
  assert.match(contentCreationSource, /className="reverse-history-list"/);
  assert.match(contentCreationSource, /最近反推/);
});

test("generated images and videos open MediaLightbox with download support", () => {
  const mediaLightboxSource = readFileSync(new URL("../components/MediaLightbox.jsx", import.meta.url), "utf8");
  const mediaLightboxUtilSource = readFileSync(new URL("../utils/mediaLightbox.js", import.meta.url), "utf8");
  const mediaLightboxStyles = readFileSync(new URL("../styles/media-lightbox.css", import.meta.url), "utf8");

  assert.match(contentCreationSource, /import MediaLightbox, \{ useMediaLightbox \} from "\.\.\/components\/MediaLightbox"/);
  assert.match(contentCreationSource, /const mediaLightbox = useMediaLightbox\(\)/);
  assert.match(contentCreationSource, /mediaLightbox\.openMedia/);
  assert.match(contentCreationSource, /createImageSlide|createVideoSlide|createMediaSlides/);
  assert.match(contentCreationSource, /downloadMedia\(/);
  assert.match(contentCreationSource, /<MediaLightbox/);
  assert.match(imagePromptStepSource, /media-preview-trigger/);
  assert.match(imagePromptStepSource, /onPreview\?\.\(variant/);
  assert.match(imagePromptStepSource, /⬇️ 下载/);
  assert.match(videoLinkAnalysisSource, /onPreviewCover/);
  assert.match(videoLinkAnalysisSource, /onPreviewVideo/);
  assert.match(videoLinkAnalysisSource, /downloadMedia\(/);
  assert.match(mediaLightboxSource, /yet-another-react-lightbox/);
  assert.match(mediaLightboxSource, /plugins\/zoom/);
  assert.match(mediaLightboxSource, /plugins\/download/);
  assert.match(mediaLightboxSource, /plugins\/video/);
  assert.match(mediaLightboxSource, /className="starx-media-lightbox"/);
  assert.match(mediaLightboxSource, /starx-lightbox-title/);
  assert.match(mediaLightboxStyles, /\.starx-media-lightbox \.yarl__container/);
  assert.match(mediaLightboxStyles, /var\(--color-primary\)/);
  assert.match(mediaLightboxUtilSource, /export async function downloadMedia/);
  assert.match(styles, /\.media-preview-trigger\s*\{/);
  assert.doesNotMatch(contentCreationSource, /const \[previewImage, setPreviewImage\]/);
  assert.doesNotMatch(contentCreationSource, /className="image-preview-modal"/);
});

test("completed image results keep the original reference visible before generated variants", () => {
  const linkResultSource = readFileSync(new URL("../components/creation/kim/KimLinkResultStep.jsx", import.meta.url), "utf8");

  assert.ok(linkResultSource.indexOf("link-generated-original") < linkResultSource.indexOf("variants.map"));
  assert.match(linkResultSource, /src=\{row\.imageUrl\}/);
  assert.match(imagePromptStepSource, /result-original-card/);
  assert.match(imagePromptStepSource, /referenceImages\[groupIndex\]\.url/);
  assert.match(imagePromptStepSource, /onPreviewOriginal/);
});
