import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const readOptional = (url) => (existsSync(url) ? readFileSync(url, "utf8") : "");

const toolboxSource = readFileSync(new URL("./Toolbox.jsx", import.meta.url), "utf8");
const navSource = readOptional(new URL("../components/toolbox/ToolboxNav.jsx", import.meta.url));
const imageSource = readOptional(new URL("../components/toolbox/AiImageWorkspace.jsx", import.meta.url));
const scriptSource = readOptional(new URL("../components/toolbox/ScriptRewriteWorkspace.jsx", import.meta.url));
const checkSource = readOptional(new URL("../components/toolbox/ProhibitedWordWorkspace.jsx", import.meta.url));
const personReplacementSource = readOptional(new URL("../components/toolbox/PersonReplacementWorkspace.jsx", import.meta.url));
const toolboxStyles = readOptional(new URL("../styles/toolbox.css", import.meta.url));
const accountReportSource = readFileSync(new URL("./AccountReport.jsx", import.meta.url), "utf8");
const allToolboxSources = [toolboxSource, navSource, imageSource, scriptSource, checkSource, personReplacementSource].join("\n");

test("toolbox uses Kim sidebar and workspace shell with the develop tool set", () => {
  assert.match(toolboxSource, /import "\.\.\/styles\/toolbox\.css"/);
  assert.match(toolboxSource, /className="toolbox-shell toolbox-ux-shell"/);
  assert.match(toolboxSource, /<section className="toolbox-main">/);
  assert.match(toolboxSource, /<ToolboxNav/);
  assert.match(toolboxSource, /<AiImageWorkspace/);
  assert.match(toolboxSource, /<ScriptRewriteWorkspace/);
  assert.match(toolboxSource, /<ProhibitedWordWorkspace/);
  assert.match(toolboxSource, /<PersonReplacementWorkspace/);
  for (const label of ["AI对话生图", "AI 人物替换", "脚本改写", "违禁词检测"]) {
    assert.match(navSource, new RegExp(label));
  }
  assert.doesNotMatch(navSource, /一键解析|一键转写|封面制作/);
});

test("AI person replacement uses two role-specific images, polling and a real result", () => {
  assert.match(personReplacementSource, /targetImage/);
  assert.match(personReplacementSource, /personImage/);
  assert.match(personReplacementSource, /createPersonReplacementJob/);
  assert.match(personReplacementSource, /getGenerationJob/);
  assert.match(personReplacementSource, /resultPayload\?\.images/);
  assert.match(personReplacementSource, /与人物参考图相同/);
  assert.match(personReplacementSource, /与场景参考图相同/);
  assert.doesNotMatch(personReplacementSource, /personDetectedRatio|sceneDetectedRatio/);
  assert.match(personReplacementSource, /persistenceStatus/);
  assert.match(personReplacementSource, /图片已生成，正在后台转存/);
  assert.match(personReplacementSource, /downloadPersonReplacementResult/);
  assert.match(personReplacementSource, /下载原图/);
  assert.doesNotMatch(personReplacementSource, /href=\{resultUrl\}[^>]*download/);
  assert.match(toolboxStyles, /\.person-replacement-inputs/);
  assert.match(toolboxStyles, /\.person-replacement-ratio/);
});

test("AI person replacement previews person, scenes and results on double click", () => {
  assert.match(personReplacementSource, /import MediaLightbox, \{ useMediaLightbox \}/);
  assert.match(personReplacementSource, /const mediaLightbox = useMediaLightbox\(\)/);
  assert.match(personReplacementSource, /previewPerson/);
  assert.match(personReplacementSource, /previewScene/);
  assert.match(personReplacementSource, /previewResult/);
  assert.match(personReplacementSource, /onDoubleClick/);
  assert.match(personReplacementSource, /<MediaLightbox/);
  assert.match(toolboxStyles, /\.person-replacement-previewable/);
});

test("person reference card does not expose the local filename", () => {
  assert.match(personReplacementSource, /file \? "人物参考图" : "上传人物参考图"/);
  assert.doesNotMatch(personReplacementSource, /file \? file\.name : "上传人物参考图"/);
});

test("AI person replacement no longer shows an authorization confirmation checkbox", () => {
  assert.doesNotMatch(personReplacementSource, /我确认图片仅用于本人/);
  assert.doesNotMatch(personReplacementSource, /setConsentConfirmed/);
  assert.match(personReplacementSource, /consentConfirmed: true/);
});

test("AI person replacement supports one-person multi-scene batch generation", () => {
  assert.match(personReplacementSource, /multiple/);
  assert.match(personReplacementSource, /MAX_SCENES/);
  assert.match(personReplacementSource, /targetImages\.map/);
  assert.match(personReplacementSource, /SUBMIT_CONCURRENCY/);
  assert.match(personReplacementSource, /variantsPerScene/);
  assert.match(personReplacementSource, /每个场景生成/);
  assert.match(personReplacementSource, /expectedOutputCount/);
  assert.match(personReplacementSource, /生成 \$\{expectedOutputCount\} 张图片/);
  assert.match(personReplacementSource, /downloadAll/);
  assert.match(personReplacementSource, /JSZip/);
  assert.match(personReplacementSource, /批量上传场景图/);
  assert.match(personReplacementSource, /人物替换步骤/);
  assert.match(toolboxStyles, /\.person-replacement-scenes-grid/);
  assert.match(toolboxStyles, /\.person-replacement-results-grid/);
  assert.match(personReplacementSource, /person-replacement-result-group/);
  assert.match(personReplacementSource, /person-replacement-result-variants/);
  assert.match(personReplacementSource, /friendlyGenerationError/);
  assert.match(toolboxStyles, /\.person-replacement-result-group/);
  assert.match(toolboxStyles, /\.person-replacement-result-variants/);
  assert.match(toolboxStyles, /\.person-replacement-variant-count/);
  assert.match(toolboxStyles, /\.person-replacement-steps/);
});

test("AI image workspace keeps develop chat materials and actions in Kim three columns", () => {
  assert.match(imageSource, /tool-layout toolbox-image-layout/);
  assert.match(imageSource, /<section className="glass-card chat-panel toolbox-chat">/);
  assert.match(imageSource, /参考图/);
  assert.match(imageSource, /chat-messages/);
  assert.match(imageSource, /素材库/);
  assert.match(imageSource, /app\.materials\.slice/);
  assert.match(imageSource, /onSend/);
  assert.match(imageSource, /onReset/);
  assert.match(toolboxSource, /setMessages/);
  assert.match(toolboxSource, /if \(!message\.trim\(\)\) return/);
  assert.doesNotMatch(`${toolboxSource}\n${imageSource}`, /<main\b/);
});

test("script and prohibited-word workspaces retain every develop action", () => {
  assert.match(scriptSource, /视频脚本改写/);
  assert.match(scriptSource, /脚本改写完成/);
  assert.match(checkSource, /违禁词批量检测/);
  assert.match(checkSource, /onDetect/);
  assert.match(checkSource, /onReplaceAll/);
  assert.match(toolboxSource, /prohibited\.filter/);
  assert.match(toolboxSource, /replaceAll/);
  assert.match(toolboxSource, /setFound\(\[\]\)/);
});

test("switching Kim tool tabs preserves every editable develop workspace value", () => {
  assert.match(toolboxSource, /const \[scriptLink, setScriptLink\] = useState\(""\)/);
  assert.match(toolboxSource, /const \[rewriteRequest, setRewriteRequest\] = useState\(""\)/);
  assert.match(toolboxSource, /videoLink=\{scriptLink\}/);
  assert.match(toolboxSource, /rewriteRequest=\{rewriteRequest\}/);
  assert.match(scriptSource, /value=\{videoLink\}/);
  assert.match(scriptSource, /onChange=\{\(event\) => onVideoLinkChange\(event\.target\.value\)\}/);
  assert.match(scriptSource, /value=\{rewriteRequest\}/);
  assert.match(scriptSource, /onChange=\{\(event\) => onRewriteRequestChange\(event\.target\.value\)\}/);
});

test("toolbox text inputs expose stable accessible names", () => {
  assert.match(imageSource, /aria-label="生图描述"/);
  assert.match(checkSource, /aria-label="待检测文案"/);
});

test("toolbox visual port does not import Kim demo generators or fake network media", () => {
  assert.doesNotMatch(allToolboxSources, /picsum\.photos|fakeImage|TAG_CATEGORIES/);
  assert.doesNotMatch(allToolboxSources, /https:\/\/example\.com/);
  assert.doesNotMatch(allToolboxSources, /saveMaterial/);
});

test("toolbox CSS preserves Kim geometry under an isolated namespace", () => {
  assert.match(toolboxStyles, /\.toolbox-ux-shell \.toolbox-nav/);
  assert.match(toolboxStyles, /\.toolbox-ux-shell \.toolbox-nav-item/);
  assert.match(toolboxStyles, /\.toolbox-ux-shell \.toolbox-image-layout/);
  assert.match(toolboxStyles, /grid-template-columns:\s*220px minmax\(0,\s*1fr\) 190px/);
  assert.match(toolboxStyles, /@media\s*\(max-width:\s*1100px\)/);
  assert.match(toolboxStyles, /@media\s*\(max-width:\s*700px\)/);
  assert.doesNotMatch(toolboxStyles, /\.report-|account-report/);
});

test("the excluded account report remains structurally untouched by toolbox work", () => {
  assert.doesNotMatch(accountReportSource, /toolbox-ux-shell|toolbox-nav|toolbox-workspace/);
  assert.doesNotMatch(toolboxStyles, /\.account-report|\.report-/);
});
