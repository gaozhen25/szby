import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  IMAGE_STEPS,
  IMAGE_LINK_STEPS,
  VIDEO_STEPS,
  getKimCreationSteps,
} from "./kimCreationContract.js";

test("Kim creation flows keep the exact step copy and order", () => {
  assert.deepEqual(IMAGE_STEPS.map(({ label, description }) => [label, description]), [
    ["素材参考", "上传或粘贴素材"],
    ["风格选择", "选择标签"],
    ["提示词输入", "输入提示词生成"],
  ]);
  assert.deepEqual(IMAGE_LINK_STEPS.map(({ label, description }) => [label, description]), [
    ["链接解析", "解析图文素材"],
    ["提示词反推", "逐图编辑提示词"],
    ["生成图片", "逐图生成改写"],
  ]);
  assert.deepEqual(VIDEO_STEPS.map(({ label, description }) => [label, description]), [
    ["素材参考", "上传视频链接"],
    ["脚本创作", "改写脚本"],
  ]);
  assert.equal(getKimCreationSteps("image"), IMAGE_STEPS);
  assert.equal(getKimCreationSteps("image-link"), IMAGE_LINK_STEPS);
  assert.equal(getKimCreationSteps("video"), VIDEO_STEPS);
});

test("production creation UI contains no Kim demo media", () => {
  const source = readFileSync(new URL("../../../pages/ContentCreation.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /picsum\.photos|topic_fake_|fakeImageUrl|fakeTopicImageUrl/);
});

test("Kim shell exposes the exact title and step geometry", () => {
  const header = readFileSync(new URL("./KimCreationHeader.jsx", import.meta.url), "utf8");
  const wizard = readFileSync(new URL("./KimStepWizard.jsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("../../../styles/content-creation-kim-exact.css", import.meta.url), "utf8");

  assert.match(header, /内容创作 ·/);
  assert.doesNotMatch(header, /KimCreationModeSwitch/);
  assert.match(header, /creation-mode-switch/);
  assert.match(header, /onCreationTypeChange\?\.\(mode\)/);
  assert.match(header, /切换创作平台/);
  assert.match(header, /新建创作/);
  assert.match(header, /onNewCreation/);
  assert.match(header, /newCreationDisabled/);
  assert.match(header, /disabled=\{newCreationDisabled\}/);
  assert.match(wizard, /step-wizard-connector/);
  assert.match(wizard, /step-wizard-circle/);
  assert.match(wizard, /aria-current/);
  assert.match(css, /\.kim-creation-shell \.step-wizard-node\.current \.step-wizard-circle/);
  assert.match(css, /\.kim-creation-shell \.creation-masthead/);
});

test("ContentCreation renders the Kim shell instead of the develop wizard card", () => {
  const source = readFileSync(new URL("../../../pages/ContentCreation.jsx", import.meta.url), "utf8");

  assert.match(source, /import KimCreationHeader from "\.\.\/components\/creation\/kim\/KimCreationHeader"/);
  assert.match(source, /import KimStepWizard from "\.\.\/components\/creation\/kim\/KimStepWizard"/);
  assert.match(source, /import \{ getKimCreationSteps \} from "\.\.\/components\/creation\/kim\/kimCreationContract"/);
  assert.match(source, /import "\.\.\/styles\/content-creation-kim-exact\.css"/);
  assert.match(source, /className="creation-page kim-creation-shell"/);
  assert.match(source, /className="creation-masthead"/);
  assert.doesNotMatch(source, /KimCreationModeSwitch/);
  assert.match(source, /<KimCreationHeader/);
  assert.match(source, /<KimStepWizard/);
  assert.doesNotMatch(source, /<section className="glass-card creation-wizard-card">/);
});

test("ContentCreation keeps Kim single-column stage containers instead of develop studio layouts", () => {
  const source = readFileSync(new URL("../../../pages/ContentCreation.jsx", import.meta.url), "utf8");

  assert.equal((source.match(/className="wizard-container"/g) || []).length, 2);
  assert.doesNotMatch(source, /className="creation-studio-shell"/);
  assert.doesNotMatch(source, /className="video-creation-layout"/);
});

test("image reference step keeps Kim upload, link and skip card order", () => {
  const source = readFileSync(new URL("./KimImageReferenceStep.jsx", import.meta.url), "utf8");
  const upload = source.indexOf("上传参考图");
  const link = source.indexOf("粘贴内容链接");
  const skip = source.indexOf("没有素材也能开始");

  assert.ok(upload >= 0 && upload < link && link < skip);
  assert.match(source, /STEP 01 · START/);
  assert.match(source, /选择你的创作起点/);
  assert.match(source, /仅解析公开内容，保留你的数据安全/);
  assert.doesNotMatch(source, /保存到流程管理|进入标签选择 →/);
  assert.doesNotMatch(source, /fetch\(|starxApi|picsum\.photos|fake/);
});

test("ContentCreation uses the Kim image reference step for its default image state", () => {
  const source = readFileSync(new URL("../../../pages/ContentCreation.jsx", import.meta.url), "utf8");

  assert.match(source, /import KimImageReferenceStep from "\.\.\/components\/creation\/kim\/KimImageReferenceStep"/);
  assert.match(source, /currentStep === 0 \? \(showImageParseResult \? <KimLinkParseResult/);
  assert.match(source, /: <KimImageReferenceStep/);
  assert.match(source, /onExtractLink=\{extractLink\}/);
  assert.match(source, /onSkip=\{\(\) => \{[\s\S]{0,180}changeImageRatio\(DEFAULT_IMAGE_RATIO\);[\s\S]{0,120}completeStep\(0, 1, "image"\); \}\}/);
  assert.match(source, /showImageParseResult\s*\?\s*continueImageLinkFlow\s*:\s*\(\) => imagePreviews\[0\] \? reversePrompt/);
  assert.doesNotMatch(source, /<div className="section-row"><h3>参考输入<\/h3><\/div>/);
});

test("Kim tag selection directly preserves Kim's fixed-category component contract", () => {
  const source = [
    "./KimTagSelectionStep.jsx",
    "../TagSelectionPanel.jsx",
    "../SelectedTagsPanel.jsx",
    "../../../config/tagCategoryUi.js",
  ].map((path) => readFileSync(new URL(path, import.meta.url), "utf8")).join("\n");

  assert.match(source, /已选标签/);
  assert.match(source, /搜索标签名称/);
  assert.match(source, /标签分类筛选/);
  assert.match(source, /跳过标签/);
  assert.match(source, /下一步 →/);
  assert.match(source, /SelectedTagsPanel/);
  assert.match(source, /TagCategoryCard/);
  assert.match(source, /fixedCategories = \(categories \|\| \[\]\)\.filter\(\(category\) => \["purpose", "style", "scene", "quality"\]\.includes\(category\.id\)\)/);
  assert.match(source, /onCreateTag/);
  assert.match(source, /className="creation-add-tag"/);
  assert.doesNotMatch(source, /onManage|button-row/);
});

test("ContentCreation renders the Kim tag page with develop tag data and actions", () => {
  const source = readFileSync(new URL("../../../pages/ContentCreation.jsx", import.meta.url), "utf8");

  assert.match(source, /import KimTagSelectionStep from "\.\.\/components\/creation\/kim\/KimTagSelectionStep"/);
  assert.match(source, /<KimTagSelectionStep/);
  assert.match(source, /categories=\{mergedCategories\}/);
  assert.match(source, /selectedTagIds=\{selectedTagIds\}/);
  assert.match(source, /onToggle=\{toggleTag\}/);
  assert.match(source, /onClear=\{clearTags\}/);
  assert.match(source, /currentStep === 1 \? <KimTagSelectionStep[\s\S]*?: currentStep === 2 \? <KimImagePromptStep/);
  assert.match(source, /<KimTagSelectionStep[\s\S]{0,800}onCreateTag=\{openNewTagModal\}/);
  assert.doesNotMatch(source, /<KimTagSelectionStep[\s\S]{0,800}onManage=/);
});

test("prompt templates are discoverable in tag selection and reusable from the final prompt", () => {
  const source = readFileSync(new URL("../../../pages/ContentCreation.jsx", import.meta.url), "utf8");
  const tagStep = readFileSync(new URL("./KimTagSelectionStep.jsx", import.meta.url), "utf8");
  const tagSelectionPanelSource = readFileSync(new URL("../TagSelectionPanel.jsx", import.meta.url), "utf8");
  const templateShelf = readFileSync(new URL("./PromptTemplateShelf.jsx", import.meta.url), "utf8");
  const promptStep = readFileSync(new URL("./KimImagePromptStep.jsx", import.meta.url), "utf8");
  const styles = readFileSync(new URL("../../../styles/content-creation-tags.css", import.meta.url), "utf8");

  assert.match(tagStep, /afterCategories=\{<PromptTemplateShelf templates=\{templates\}/);
  assert.match(tagSelectionPanelSource, /\{afterCategories\}[\s\S]*className="creation-tag-next"/);
  assert.match(templateShelf, /从提示词模板开始/);
  assert.match(templateShelf, /搜索提示词模板/);
  assert.match(templateShelf, /aria-pressed=\{active\}/);
  assert.match(source, /templates=\{templates\}/);
  assert.match(source, /onApplyTemplate=\{applyTemplate\}/);
  assert.match(source, /setNegativePrompt\(tpl\.negativePrompt \|\| ""\)/);
  assert.match(source, /changeImageRatio\(tpl\.params\.ratio\)/);
  assert.match(source, /clearImagePromptPlan\(\)/);
  assert.match(promptStep, /保存为模板/);
  assert.match(promptStep, /onClick=\{onSaveTemplate\}/);
  assert.match(source, /params: \{ ratio: ratio \|\| DEFAULT_IMAGE_RATIO, count: String\(genCount \|\| 1\) \}/);
  assert.match(source, /savingTemplate \? "保存中\.\.\." : "确认保存"/);
  assert.match(styles, /\.prompt-template-grid\s*\{/);
  assert.match(styles, /@media \(max-width:640px\)[\s\S]{0,240}\.prompt-template-grid\s*\{\s*grid-template-columns:1fr/);
});

test("Kim link flow keeps parse review, per-image prompts and per-image results", () => {
  const parse = readFileSync(new URL("./KimLinkParseResult.jsx", import.meta.url), "utf8");
  const prompts = readFileSync(new URL("./KimLinkPromptStep.jsx", import.meta.url), "utf8");
  const results = readFileSync(new URL("./KimLinkResultStep.jsx", import.meta.url), "utf8");

  assert.match(parse, /解析结果/);
  assert.doesNotMatch(parse, /继续创作 →|onNext/);
  assert.match(parse, /parse-copy-btn/);
  assert.match(parse, /parse-copy-follow/);
  assert.match(parse, /aria-label=\{`复制\$\{label\}`\}/);
  assert.match(parse, /label="标题"/);
  assert.match(parse, /label="正文"/);
  assert.match(parse, /navigator\.clipboard/);
  assert.match(parse, /一键下载全部素材/);
  assert.match(parse, /downloadAllMedia|downloadingAll/);
  assert.match(parse, /downloadMediaZip/);
  assert.match(prompts, /逐图反推提示词/);
  assert.match(prompts, /对应提示词/);
  assert.match(prompts, /下一步：生成图片/);
  assert.match(prompts, /media-preview-trigger/);
  assert.match(prompts, /onPreview\?\.\(index\)/);
  assert.match(prompts, /downloadMedia\(/);
  assert.match(results, /生成图片结果/);
  assert.match(results, /重新生成全部/);
  assert.match(results, /输入要求重新生成/);
  assert.match(results, /link-generated-original/);
  assert.match(results, />原图</);
  assert.match(results, /src=\{row\.imageUrl\}/);
  assert.match(results, /创作参考/);
  assert.match(results, /新生成/);
  assert.match(results, /onSelectVariant/);
  assert.doesNotMatch(`${parse}\n${prompts}\n${results}`, /picsum\.photos|fakeTopic|fakeImage/);
});

test("ContentCreation switches to Kim link steps and preserves real API actions", () => {
  const source = readFileSync(new URL("../../../pages/ContentCreation.jsx", import.meta.url), "utf8");

  assert.match(source, /getKimCreationSteps\(imageUsesLinkFlow \? "image-link" : type\)/);
  assert.match(source, /<KimLinkParseResult/);
  assert.match(source, /<KimLinkPromptStep/);
  assert.match(source, /<KimLinkResultStep/);
  assert.match(source, /await app\.extractLinkReference/);
  assert.match(source, /await app\.reversePrompt/);
  assert.match(source, /await app\.createImageJob/);
  assert.match(source, /setImageLinkPromptRows\(\[\]\);[\s\S]{0,160}void applyReferenceImageRatio\(r\.images \|\| \[\]\);[\s\S]{0,80}setShowImageParseResult\(true\);/);
  assert.match(source, /setLinkReference\(null\);\s*setImageLinkPromptRows\(\[\]\);\s*setShowImageParseResult\(false\);/);
  assert.match(source, /showImageParseResult \? "继续创作 →" : "进入标签选择 →"/);
  assert.match(source, /showImageParseResult\s*\?\s*continueImageLinkFlow/);
  assert.match(source, /showImageParseResult:\s*true|showImageParseResult,/);
});

test("Kim image prompt step directly preserves Kim's complete prompt and result hierarchy", () => {
  const source = readFileSync(new URL("./KimImagePromptStep.jsx", import.meta.url), "utf8");
  assert.match(source, /生图提示词/);
  assert.match(source, /负向提示词/);
  assert.match(source, /图片比例/);
  assert.match(source, /创意程度/);
  assert.match(source, /素材图（可选）/);
  assert.match(source, /生成结果/);
  assert.match(source, /reverse-result-card/);
  assert.match(source, /result-hint/);
  assert.match(source, /result-source-prompt/);
  assert.match(source, /placeholder-card/);
  assert.match(source, /className="prompt-input-step"/);
  assert.doesNotMatch(source, /kim-prompt-step/);
  assert.doesNotMatch(source, /专业工具|advancedTools/);
});

test("Kim video reference step keeps the concise two-choice entry", () => {
  const source = readFileSync(new URL("./KimVideoReferenceStep.jsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("../../../styles/content-creation-kim-exact.css", import.meta.url), "utf8");
  assert.match(source, /视频素材参考/);
  assert.match(source, /开始解析/);
  assert.match(source, /跳过参考链接，直接写脚本/);
  assert.match(source, /视频封面预览/);
  assert.match(source, /video-reference-cover/);
  assert.match(source, /video-reference-player/);
  assert.match(source, /buildVideoPreviewUrl/);
  assert.match(source, /controls playsInline preload="metadata"/);
  assert.match(css, /\.kim-creation-shell \.video-reference-step\s*\{[\s\S]*max-width:\s*600px;[\s\S]*margin:\s*0 auto;/);
  assert.match(css, /\.kim-creation-shell \.full-width-textarea\s*\{[\s\S]*width:\s*100%;[\s\S]*padding:\s*var\(--space-md\);/);
  assert.match(css, /\.kim-creation-shell \.btn-lg\s*\{[\s\S]*padding:\s*var\(--space-md\) var\(--space-xl\);[\s\S]*font-size:\s*var\(--text-base\);/);
  assert.doesNotMatch(source, /视频解析历史|kim-advanced-tools/);
});

test("Kim video script step keeps editing and adds the structured storyboard hierarchy", () => {
  const source = readFileSync(new URL("./KimVideoScriptStep.jsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("../../../styles/content-creation-kim-exact.css", import.meta.url), "utf8");

  assert.match(source, /爆款原版脚本/);
  assert.match(source, /AI 改写版脚本/);
  assert.match(source, /AI 改写脚本/);
  assert.match(source, /发布文案/);
  assert.match(source, /编辑发布文案/);
  assert.match(source, /script-creation-grid/);
  assert.match(source, /video-meta-section/);
  assert.match(source, /VideoStoryboardTable/);
  assert.match(source, /逐镜拍摄执行表/);
  assert.match(source, /HOOK · 前 3–5 秒/);
  assert.match(source, /导出分镜/);
  assert.match(source, /downloadVideoStoryboardCsv/);
  assert.match(source, /packageResult=\{packageResult\}/);
  assert.match(css, /\.kim-creation-shell \.script-creation-grid\s*\{[\s\S]*grid-template-columns:\s*1fr 1fr/);
  assert.match(css, /\.kim-creation-shell \.video-storyboard-row\s*\{[\s\S]*grid-template-columns:/);
  assert.doesNotMatch(source, /VideoShootingCardList|BGM 建议/);
});

test("Kim workflow handoff is opened from a concise action and completed in a modal", () => {
  const source = readFileSync(new URL("./KimWorkflowSaveModal.jsx", import.meta.url), "utf8");

  assert.match(source, /保存到流程管理/);
  assert.match(source, /填写交接信息后，将进入/);
  for (const label of ["负责人", "截止日期", "优先级", "初始阶段", "交接备注"]) {
    assert.match(source, new RegExp(label));
  }
  assert.match(source, /aria-modal="true"/);
  assert.match(source, /event\.key === "Escape"/);
  assert.match(source, /确认保存/);
  assert.match(source, /完成创作，进入审核/);
  assert.match(source, /之后仍可返回继续修改/);
});

test("develop-only creation controls live in a dismissible centered modal", () => {
  const source = readFileSync(new URL("./KimCreationExtrasDrawer.jsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("../../../styles/content-creation-kim-extras.css", import.meta.url), "utf8");

  assert.match(source, /专业工具/);
  assert.match(source, /role="dialog"/);
  assert.match(source, /aria-modal="true"/);
  assert.match(source, /event\.key === "Escape"/);
  assert.match(source, /lastFocusedElement/);
  assert.match(source, /kim-extras-modal/);
  assert.match(source, /kim-extras-close/);
  assert.match(source, /aria-label="关闭专业工具"/);
  assert.match(source, />\s*×\s*</);
  assert.doesNotMatch(source, /kim-extras-drawer/);
  assert.match(source, /content-creation-kim-extras\.css/);
  assert.match(source, /createPortal/);
  assert.match(css, /\.kim-extras-overlay\s*\{[\s\S]*place-items:\s*center/);
  assert.match(css, /\.kim-extras-overlay\s*\{[\s\S]*pointer-events:\s*auto/);
  assert.match(css, /\.kim-extras-modal\s*\{/);
  assert.match(css, /\.kim-extras-close\s*\{/);
});

test("ContentCreation uses Kim workflow stages and keeps develop extras outside the main flow", () => {
  const source = readFileSync(new URL("../../../pages/ContentCreation.jsx", import.meta.url), "utf8");

  assert.match(source, /import KimCreationExtrasDrawer/);
  assert.match(source, /import KimWorkflowSaveModal/);
  assert.match(source, /const workflowStageOptions = type === "video"/);
  assert.match(source, /\[\["script", "脚本"\], \["review", "审核"\], \["pending_review", "待发布"\]\]/);
  assert.match(source, /<KimCreationExtrasDrawer/);
  assert.match(source, /<VideoShootingCardList packageResult=\{activeVideoScriptPackage\}/);
  assert.match(source, /<ImagePromptPlanEditor/);
  assert.match(source, /<KimWorkflowSaveModal/);
  assert.match(source, /const handleSaveToWorkflow = async \(\) => \{\s*setSavingWorkflow\(true\)/);
  assert.match(source, /readyForWorkflowCompletion/);
  assert.match(source, /继续修改图片/);
  assert.match(source, /完成创作，进入审核 →/);
  assert.match(source, /readyForWorkflowCompletion[\s\S]*app\.setActivePage\?\.\("process"\)/);
  assert.doesNotMatch(source, /请先填写发布文案，文案为空不能进入发布流程/);
  assert.doesNotMatch(source, /className="glass-card workflow-handoff"/);
});

test("Kim creation mobile layout collapses only its own shell and stacks prompt controls", () => {
  const css = readFileSync(new URL("../../../styles/content-creation-kim-exact.css", import.meta.url), "utf8");

  assert.match(css, /\.shell:has\(\.kim-creation-shell\) \.side\s*\{[\s\S]*min-width:\s*56px/);
  assert.match(css, /\.kim-creation-shell \.prompt-advanced-grid,[\s\S]*\.kim-creation-shell \.generation-controls\s*\{[\s\S]*grid-template-columns:\s*1fr/);
  assert.doesNotMatch(css, /\.account-report[^\n{]*\{|\.report-page[^\n{]*\{/);
});
