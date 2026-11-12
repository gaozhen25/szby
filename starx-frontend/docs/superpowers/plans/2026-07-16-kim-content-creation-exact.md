# 内容创作界面 Kim 精确对齐实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让内容创作页的主流程、文案、DOM 几何、视觉和交互状态与 `origin/Kim` 一致，同时保留 `develop` 的真实业务逻辑和恢复能力。

**Architecture:** `ContentCreation.jsx` 保留副作用与业务状态，新的 `components/creation/kim/` 只负责 Kim 展示结构。Kim 原始 DOM/CSS 是视觉权威；`develop` 独有能力进入默认关闭的二级抽屉，不能改变主流程常驻布局。

**Tech Stack:** React 18、Vite 7、Node test runner、CSS、Codex Browser 本地视觉验证。

## Global Constraints

- 动态数据允许不同；相同状态下的结构、文案、顺序、尺寸、间距、颜色、响应式和反馈必须与 `origin/Kim` 一致。
- 保留 `develop` 的轮询、恢复、生成、保存、错误处理和流程交接，不采用 Kim 的旧业务请求。
- 不引入 Kim 的 `picsum.photos`、假选题 SVG、假任务、固定统计或旧 API。
- 内容创作页不提供直接发布；发布只发生在流程管理。
- 账号报告及其专属样式不得改变。
- 新组件不直接调用 API、不持有轮询、不持久化业务状态。
- 每个行为改动必须先有失败测试，再写实现。

---

### Task 1: 建立 Kim 精确契约与流程模型

**Files:**
- Create: `src/components/creation/kim/kimCreationContract.js`
- Create: `src/components/creation/kim/KimCreationContract.test.js`
- Modify: `src/components/creation/CreationUx.preview.test.js`

**Interfaces:**
- Produces: `IMAGE_STEPS`、`IMAGE_LINK_STEPS`、`VIDEO_STEPS`、`getKimCreationSteps(flow)`。
- Consumes: 无业务服务。

- [ ] **Step 1: 写失败的步骤与反假数据测试**

```js
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
  assert.equal(getKimCreationSteps("image-link"), IMAGE_LINK_STEPS);
});

test("production creation UI contains no Kim demo media", () => {
  const source = readFileSync(new URL("../../../pages/ContentCreation.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /picsum\.photos|topic_fake_|fakeImageUrl|fakeTopicImageUrl/);
});
```

- [ ] **Step 2: 运行测试并确认因模块缺失而失败**

Run: `node --test src/components/creation/kim/KimCreationContract.test.js`

Expected: FAIL，错误包含 `ERR_MODULE_NOT_FOUND`。

- [ ] **Step 3: 写最小流程契约实现**

```js
export const IMAGE_STEPS = Object.freeze([
  { id: "reference", label: "素材参考", description: "上传或粘贴素材" },
  { id: "style", label: "风格选择", description: "选择标签" },
  { id: "prompt", label: "提示词输入", description: "输入提示词生成" },
]);

export const IMAGE_LINK_STEPS = Object.freeze([
  { id: "reference", label: "链接解析", description: "解析图文素材" },
  { id: "prompt_table", label: "提示词反推", description: "逐图编辑提示词" },
  { id: "generate_table", label: "生成图片", description: "逐图生成改写" },
]);

export const VIDEO_STEPS = Object.freeze([
  { id: "reference", label: "素材参考", description: "上传视频链接" },
  { id: "script", label: "脚本创作", description: "改写脚本" },
]);

export function getKimCreationSteps(flow) {
  if (flow === "image-link") return IMAGE_LINK_STEPS;
  if (flow === "video") return VIDEO_STEPS;
  return IMAGE_STEPS;
}
```

- [ ] **Step 4: 运行定向测试并确认通过**

Run: `node --test src/components/creation/kim/KimCreationContract.test.js`

Expected: `2` tests passed，`0` failed。

- [ ] **Step 5: 提交**

```bash
git add src/components/creation/kim/kimCreationContract.js src/components/creation/kim/KimCreationContract.test.js src/components/creation/CreationUx.preview.test.js
git commit -m "test: define exact Kim creation contract"
```

---

### Task 2: 复刻 Kim 页面框架、标题和步骤条

**Files:**
- Create: `src/components/creation/kim/KimCreationHeader.jsx`
- Create: `src/components/creation/kim/KimStepWizard.jsx`
- Create: `src/styles/content-creation-kim-exact.css`
- Modify: `src/pages/ContentCreation.jsx`
- Modify: `src/components/creation/kim/KimCreationContract.test.js`

**Interfaces:**
- `KimCreationHeader({ accountName, accountType, platforms, targetPlatform, type, onPlatformChange, onTypeChange })`。
- `KimStepWizard({ steps, currentStep, completedSteps, onStepClick })`。
- Consumes: Task 1 的步骤常量。

- [ ] **Step 1: 写失败的源码结构测试**

```js
test("Kim shell exposes the exact title, type switch and step geometry", () => {
  const header = readFileSync(new URL("./KimCreationHeader.jsx", import.meta.url), "utf8");
  const wizard = readFileSync(new URL("./KimStepWizard.jsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("../../../styles/content-creation-kim-exact.css", import.meta.url), "utf8");
  assert.match(header, /内容创作 ·/);
  assert.match(header, /🖼️ 图文创作/);
  assert.match(header, /🎬 视频创作/);
  assert.match(wizard, /step-wizard-line-bg/);
  assert.match(wizard, /step-wizard-circle/);
  assert.match(css, /\.step-wizard-node\.current \.step-wizard-circle/);
  assert.match(css, /\.creation-type-tabs/);
});
```

- [ ] **Step 2: 运行测试并确认组件缺失失败**

Run: `node --test src/components/creation/kim/KimCreationContract.test.js`

Expected: FAIL，缺少 `KimCreationHeader.jsx`。

- [ ] **Step 3: 以 Kim DOM 为权威实现 Header 和 Wizard**

```jsx
export function KimCreationHeader({ accountName, accountType, platforms, targetPlatform, type, onPlatformChange, onTypeChange }) {
  return <>
    <div className="section-header creation-topline">
      <h2>内容创作 · {accountName || ""}</h2>
      <div className="section-header-right">
        <span className="muted">{accountType || "普通号"} ·</span>
        <select aria-label="切换创作平台" value={targetPlatform} onChange={(event) => onPlatformChange(event.target.value)}>
          {platforms.map((platform) => <option value={platform} key={platform}>{platform}</option>)}
        </select>
      </div>
    </div>
    <div className="creation-type-tabs">
      <button className={`btn ${type === "image" ? "btn-primary" : ""}`} onClick={() => onTypeChange("image")}>🖼️ 图文创作</button>
      <button className={`btn ${type === "video" ? "btn-primary" : ""}`} onClick={() => onTypeChange("video")}>🎬 视频创作</button>
    </div>
  </>;
}
```

`KimStepWizard.jsx` 使用 Kim 的 `step-wizard`、`step-wizard-line-bg`、`step-wizard-line-fill`、`step-wizard-nodes`、`step-wizard-node`、`step-wizard-circle`、`step-number`、`step-check`、`step-wizard-label`、`step-wizard-title`、`step-wizard-desc` 层级；节点使用 `<button type="button">` 保留键盘语义，但通过 CSS 清除按钮默认样式，视觉与 Kim 的 `<div>` 相同。

- [ ] **Step 4: 从 Kim 精确移植对应 CSS 并接入页面**

把 `origin/Kim:src/styles/pages.css` 中内容创作顶栏、类型按钮和步骤条规则复制到 `content-creation-kim-exact.css`；在 `ContentCreation.jsx` 引入专属样式并用 Header/Wizard 替换现有 `creation-wizard-card`。

- [ ] **Step 5: 运行定向测试**

Run: `node --test src/components/creation/kim/KimCreationContract.test.js src/components/creation/CreationUx.preview.test.js`

Expected: 全部通过。

- [ ] **Step 6: 提交**

```bash
git add src/components/creation/kim/KimCreationHeader.jsx src/components/creation/kim/KimStepWizard.jsx src/styles/content-creation-kim-exact.css src/pages/ContentCreation.jsx src/components/creation/kim/KimCreationContract.test.js
git commit -m "feat: match Kim creation shell"
```

---

### Task 3: 复刻图文素材首屏和链接三步流程

**Files:**
- Create: `src/components/creation/kim/KimImageReferenceStep.jsx`
- Create: `src/components/creation/kim/KimImageLinkPromptStep.jsx`
- Create: `src/components/creation/kim/KimImageLinkResultStep.jsx`
- Modify: `src/pages/ContentCreation.jsx`
- Modify: `src/styles/content-creation-kim-exact.css`
- Modify: `src/components/creation/kim/KimCreationContract.test.js`
- Modify: `src/pages/ContentCreation.preview.test.js`

**Interfaces:**
- `KimImageReferenceStep` 接收上传、拖放、链接平台、链接文本、解析、跳过和忙碌状态。
- `KimImageLinkPromptStep` 接收真实解析图片行、提示词编辑、单行反推、全部反推和下一步回调。
- `KimImageLinkResultStep` 接收真实生成组、选择变体、单行重试、保存素材和下载回调。

- [ ] **Step 1: 写失败的 Kim 首屏结构测试**

```js
test("image reference step keeps Kim upload, link and skip card order", () => {
  const source = readFileSync(new URL("./KimImageReferenceStep.jsx", import.meta.url), "utf8");
  const upload = source.indexOf("上传参考图");
  const link = source.indexOf("粘贴内容链接");
  const skip = source.indexOf("没有素材也能开始");
  assert.ok(upload >= 0 && upload < link && link < skip);
  assert.match(source, /选择你的创作起点/);
  assert.match(source, /仅解析公开内容，保留你的数据安全/);
});
```

- [ ] **Step 2: 运行测试并确认缺少组件失败**

Run: `node --test src/components/creation/kim/KimCreationContract.test.js`

Expected: FAIL，缺少图文参考组件。

- [ ] **Step 3: 按 Kim 原始 JSX 实现三个展示组件**

复制 Kim 的 `reference-entry-page`、`reference-choice-grid`、`reference-upload-card`、`reference-link-card`、`reference-skip-card`，以及 `link-prompt-table-step`、`link-result-table-step` 层级。删除所有 `fakeImageUrl` 和本地模拟成功分支，所有图片、状态和提示词都由 props 提供。

- [ ] **Step 4: 把现有真实动作接入展示组件**

映射现有 `handleReferenceFiles`、`extractLinkReference`、图片反推、`regenerateSlot`、`selectVariant`、`handleSaveToLibrary` 和下载逻辑。链接解析成功后把流程切到 `image-link`；普通上传或跳过保持 `image` 流程。

- [ ] **Step 5: 迁移 Kim 对应 CSS**

从 Kim 原样迁移参考卡、解析结果表、提示词表、生成结果表和响应式规则；删除当前主页面常驻 `.studio-side-panel` 与 `.creation-step-grid` 的使用。

- [ ] **Step 6: 运行内容创作定向测试**

Run: `node --test src/components/creation/kim/KimCreationContract.test.js src/pages/ContentCreation.preview.test.js`

Expected: 全部通过；旧测试若只断言常驻历史栏或双栏工作台，应改为断言对应能力从二级入口可达，而不是删除业务断言。

- [ ] **Step 7: 提交**

```bash
git add src/components/creation/kim src/pages/ContentCreation.jsx src/pages/ContentCreation.preview.test.js src/styles/content-creation-kim-exact.css
git commit -m "feat: match Kim image reference and link flow"
```

---

### Task 4: 复刻标签、普通提示词和图片结果页

**Files:**
- Create: `src/components/creation/kim/KimTagSelectionStep.jsx`
- Create: `src/components/creation/kim/KimImagePromptStep.jsx`
- Modify: `src/pages/ContentCreation.jsx`
- Modify: `src/styles/content-creation-kim-exact.css`
- Modify: `src/components/creation/kim/KimCreationContract.test.js`
- Modify: `src/pages/ContentCreation.preview.test.js`

**Interfaces:**
- `KimTagSelectionStep({ categories, selectedTagIds, onToggle, onClear, onManage, onSkip, onNext, onBack })`。
- `KimImagePromptStep({ prompt, negativePrompt, ratio, creativityLevel, genCount, materialPreviews, imageGroups, selectedVariants, busy, errors, callbacks })`。

- [ ] **Step 1: 写失败的文案、顺序和默认布局测试**

```js
test("normal image flow keeps Kim tag and prompt copy", () => {
  const tag = readFileSync(new URL("./KimTagSelectionStep.jsx", import.meta.url), "utf8");
  const prompt = readFileSync(new URL("./KimImagePromptStep.jsx", import.meta.url), "utf8");
  assert.match(tag, /跳过标签/);
  assert.match(tag, /下一步 →/);
  assert.match(prompt, /生图提示词/);
  assert.match(prompt, /负向提示词/);
  assert.match(prompt, /图片比例/);
  assert.match(prompt, /创意程度/);
  assert.match(prompt, /素材图（可选）/);
  assert.match(prompt, /生成结果/);
  assert.doesNotMatch(prompt, /快速操作|最近任务|最近反推/);
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `node --test src/components/creation/kim/KimCreationContract.test.js`

Expected: FAIL，缺少标签或提示词组件。

- [ ] **Step 3: 实现 Kim 标签和提示词组件**

标签页复用 `develop` 的真实标签分类，但采用 Kim 的标签卡片、已选摘要和底部操作。提示词页采用 Kim 的单一 `prompt-input-step` 与结果卡，不渲染 director header、提示词计划常驻编辑器或侧栏。

- [ ] **Step 4: 接入真实生成与恢复逻辑**

普通 prompt、结构化 prompt plan 和链接逐图 prompt 都继续调用现有 `createImages`、任务轮询、`normalizeImageGroups` 与 `selectVariant`。结构化 prompt plan 的高级编辑入口进入 Task 6 的抽屉。

- [ ] **Step 5: 运行定向与全量测试**

Run: `node --test src/components/creation/kim/KimCreationContract.test.js src/pages/ContentCreation.preview.test.js && npm test`

Expected: `275` 个基线测试加新增测试全部通过。

- [ ] **Step 6: 提交**

```bash
git add src/components/creation/kim src/pages/ContentCreation.jsx src/pages/ContentCreation.preview.test.js src/styles/content-creation-kim-exact.css
git commit -m "feat: match Kim image prompt workflow"
```

---

### Task 5: 复刻视频素材与双栏脚本流程

**Files:**
- Create: `src/components/creation/kim/KimVideoReferenceStep.jsx`
- Create: `src/components/creation/kim/KimVideoScriptStep.jsx`
- Modify: `src/pages/ContentCreation.jsx`
- Modify: `src/styles/content-creation-kim-exact.css`
- Modify: `src/components/creation/kim/KimCreationContract.test.js`
- Modify: `src/pages/ContentCreation.preview.test.js`

**Interfaces:**
- `KimVideoReferenceStep({ linkText, reference, analyzing, error, onLinkChange, onAnalyze, onSkip })`。
- `KimVideoScriptStep({ original, rewritten, rewritePrompt, title, hashtags, publishText, rewriting, errors, callbacks })`。

- [ ] **Step 1: 写失败的 Kim 视频主界面测试**

```js
test("video flow keeps Kim reference and two-column script shell", () => {
  const reference = readFileSync(new URL("./KimVideoReferenceStep.jsx", import.meta.url), "utf8");
  const script = readFileSync(new URL("./KimVideoScriptStep.jsx", import.meta.url), "utf8");
  assert.match(reference, /视频素材参考/);
  assert.match(reference, /开始解析/);
  assert.match(reference, /跳过参考链接，直接写脚本/);
  assert.match(script, /爆款原版脚本/);
  assert.match(script, /AI 改写版脚本/);
  assert.match(script, /AI 改写脚本/);
  assert.match(script, /发布文案/);
  assert.doesNotMatch(script, /video-script-workstation|拍摄执行/);
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `node --test src/components/creation/kim/KimCreationContract.test.js`

Expected: FAIL，缺少视频组件。

- [ ] **Step 3: 实现 Kim 视频展示组件并迁移 CSS**

按 Kim 复刻 `video-reference-step`、`video-script-step`、`script-creation-grid`、`script-col`、`video-meta-section` 和对应响应式规则。错误和重试置于脚本区上方，不改变双栏主体。

- [ ] **Step 4: 接入 develop 视频业务**

链接解析继续调用 `extractLinkReference` 与 `createVideoAnalysisJob`；脚本生成继续使用 active package job；改写继续尊重知识库和已确认偏好；标题、标签、发布文案及当前平台继续持久化。分镜、BGM、节奏、导演字段从常驻三栏移至 Task 6 抽屉。

- [ ] **Step 5: 更新旧视频测试的展示断言**

保留任务归属、轮询上限、失败重试、包持久化和平台交接断言；将“常驻三栏工作台”改为“Kim 双栏主界面 + 高级抽屉中完整拍摄字段”。

- [ ] **Step 6: 运行定向和全量测试**

Run: `node --test src/components/creation/kim/KimCreationContract.test.js src/pages/ContentCreation.preview.test.js && npm test`

Expected: 全部通过。

- [ ] **Step 7: 提交**

```bash
git add src/components/creation/kim src/pages/ContentCreation.jsx src/pages/ContentCreation.preview.test.js src/styles/content-creation-kim-exact.css
git commit -m "feat: match Kim video creation workflow"
```

---

### Task 6: 渐进披露 develop 独有能力并完成流程保存

**Files:**
- Create: `src/components/creation/kim/KimCreationExtrasDrawer.jsx`
- Create: `src/components/creation/kim/KimWorkflowSaveModal.jsx`
- Modify: `src/pages/ContentCreation.jsx`
- Modify: `src/styles/content-creation-kim-exact.css`
- Modify: `src/components/creation/kim/KimCreationContract.test.js`
- Modify: `src/pages/ContentCreation.preview.test.js`

**Interfaces:**
- `KimCreationExtrasDrawer({ open, mode, onClose, children })` 只提供容器、焦点管理和关闭行为。
- `KimWorkflowSaveModal({ open, handoff, saving, statusOptions, initialStatus, onChange, onCancel, onConfirm })`。

- [ ] **Step 1: 写失败的渐进披露与 Kim 保存弹窗测试**

```js
test("develop extras are secondary and workflow save keeps Kim copy", () => {
  const extras = readFileSync(new URL("./KimCreationExtrasDrawer.jsx", import.meta.url), "utf8");
  const save = readFileSync(new URL("./KimWorkflowSaveModal.jsx", import.meta.url), "utf8");
  assert.match(extras, /role="dialog"/);
  assert.match(extras, /aria-modal="true"/);
  assert.match(save, /保存到流程管理/);
  assert.match(save, /负责人/);
  assert.match(save, /截止日期/);
  assert.match(save, /优先级/);
  assert.match(save, /初始阶段/);
  assert.match(save, /交接备注/);
  assert.match(save, /确认保存/);
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `node --test src/components/creation/kim/KimCreationContract.test.js`

Expected: FAIL，缺少二级容器。

- [ ] **Step 3: 实现抽屉与保存弹窗**

抽屉默认不渲染，打开时锁定焦点，Escape 关闭，关闭后恢复触发按钮。保存弹窗精确采用 Kim DOM 与文案，保存忙碌时禁止遮罩、Escape 和按钮重复关闭。

- [ ] **Step 4: 迁入高级能力**

图片模式提供解析历史、最近任务、最近反推、提示词计划、模板与创作偏好；视频模式提供解析历史、分镜/导演字段、BGM、节奏、视频偏好和追踪恢复。所有现有回调与编辑状态保持不变。

- [ ] **Step 5: 删除主流程中的 develop 常驻结构**

移除主 JSX 对 `.studio-side-panel`、`.video-script-workstation`、常驻 `workflow-handoff`、发布设备提示和直接发布入口的依赖；页面底部只保留 Kim 的“保存到流程管理”和当前步骤的 Kim 主操作。

- [ ] **Step 6: 运行定向测试、全量测试和构建**

Run: `node --test src/components/creation/kim/KimCreationContract.test.js src/pages/ContentCreation.preview.test.js && npm test && npm run build`

Expected: 测试全部通过，Vite build exit `0`。

- [ ] **Step 7: 提交**

```bash
git add src/components/creation/kim src/pages/ContentCreation.jsx src/pages/ContentCreation.preview.test.js src/styles/content-creation-kim-exact.css
git commit -m "feat: preserve advanced creation tools behind Kim UX"
```

---

### Task 7: 浏览器逐屏对齐与完成审计

**Files:**
- Modify: `docs/superpowers/plans/2026-07-16-kim-content-creation-exact.md`
- Modify only if a verified mismatch exists: `src/components/creation/kim/*.jsx`
- Modify only if a verified mismatch exists: `src/styles/content-creation-kim-exact.css`

**Interfaces:**
- Consumes: `origin/Kim` 工作树和 Task 1–6 的实现。
- Produces: 完整验收证据。

- [ ] **Step 1: 启动实现与 Kim 参考服务**

Run in implementation worktree: `npm run dev -- --host 127.0.0.1 --port 3002`

Run in Kim reference worktree: `npm run dev -- --host 127.0.0.1 --port 3003`

Expected: 两个 Vite 服务都显示 ready。

- [ ] **Step 2: 以同一状态逐屏检查桌面视口**

在 `1440×900` 下覆盖：图文素材参考、标签选择、普通提示词、链接解析结果、链接提示词表、链接生成表、视频素材参考、视频脚本、加载遮罩、流程保存弹窗。

Expected: 除真实动态数据外，结构、文案、顺序、几何与视觉一致。

- [ ] **Step 3: 检查响应式视口**

在 `1024×768` 和 `390×844` 重复首屏、提示词、视频脚本与保存弹窗检查。

Expected: 折行、单列、滚动和按钮宽度与 Kim 一致，无横向溢出。

- [ ] **Step 4: 对每个真实差异执行红—绿修正**

先把差异补进 `KimCreationContract.test.js` 或相应行为测试，运行确认失败，再修改 JSX/CSS，最后运行确认通过。不得用一次改动同时猜测多个差异。

- [ ] **Step 5: 运行最终验证**

Run: `npm test`

Expected: 所有测试通过，`0` failed。

Run: `npm run build`

Expected: Vite production build exit `0`。

Run: `git diff --check`

Expected: 无输出，exit `0`。

Run: `git diff 9c8e70a -- src/pages/AccountReport.jsx src/pages/account-report src/styles/account-report.css`

Expected: 无输出。

- [ ] **Step 6: 完成计划记录并提交**

在本计划勾选完成项并记录测试数量、构建模块数、浏览器视口和账号报告零差异证据。

```bash
git add docs/superpowers/plans/2026-07-16-kim-content-creation-exact.md src/components/creation/kim src/pages/ContentCreation.jsx src/pages/ContentCreation.preview.test.js src/styles/content-creation-kim-exact.css
git commit -m "docs: record exact Kim creation verification"
```
