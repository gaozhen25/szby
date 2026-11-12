# Kim UX 移植实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留 `develop` 业务能力，将 `Kim` 分支除账号报告外的布局、分步创作流程、流程管理发布路径和加载动画移植到 `develop`。

**Architecture:** 页面继续拥有状态、API 调用、任务轮询、恢复、保存和发布逻辑；内容创作新增可持久化的受控步骤状态，流程管理编排现有发布 API。加载层、步骤条、流程矩阵、详情抽屉和发布弹窗只负责展示并通过回调上报操作；所有移植样式使用页面或组件命名空间。

**Tech Stack:** React 18、Vite 7、原生 CSS、Node.js `node:test`

## Global Constraints

- `develop` 是唯一业务逻辑基线，不得用 `Kim` 的核心页面或 Hook 整文件覆盖。
- 纳入范围页面的 DOM 层级、卡片比例、间距、按钮层级和响应式布局以 `origin/Kim` 的实际实现为强参考；偏离时必须有保留 `develop` 功能或真实数据的明确理由。
- 除用户明确决定移除的内容创作直接发布入口外，保留全部 `develop` 功能入口；`Kim` 没有对应位置时，使用相同视觉语言重新安置。
- 发布入口按用户决策统一为“保存到流程管理 → 任务详情抽屉 → 发布弹窗”；内容创作页不得保留直接发布入口。
- 发布 API、设备校验、媒体校验、状态轮询、时间线和设备配置入口沿用 `develop` 行为；按用户确认扩展后端待发布校验与独立重试尝试契约。
- 发布可见性固定为 `0=公开`、`1=好友`、`2=仅自己`；前后端发布门禁都直接检查任务原始 `status === "pending_review"`，用于展示的状态别名归一化不得用于授权。
- 只有可信的失败或取消终态可以显式重试，进行中、成功或不确定提交状态拒绝重复提交；不确定提交必须保持同一 `attempt` 和外部任务 ID 继续恢复或轮询。
- 只有能够确认请求在发送前失败或外部服务明确拒绝时才写入 `failed`；读取/写入异常、5xx、409 后恢复失败、缺少或不匹配身份字段的畸形 2xx 都按不确定提交处理。
- 发布文案去除首尾空白后必须非空；前端禁止确认并提示，后端返回校验错误，不得回填旧正文。
- `000022_creation_publish_attempts` 降级必须先把最新发布投影和最后 50 条尝试历史合并回旧 `creation_state`，并保留其中其他业务键，再删除尝试表。
- 明确排除 `src/pages/AccountReport.jsx` 及账号报告专属样式。
- 展示组件不得直接调用 API、启动领域任务轮询或持久化业务状态。
- 新增样式使用 `creation-`、`workflow-`、`competitor-`、`topic-`、`account-`、`knowledge-` 或 `tool-` 前缀。
- 动画必须支持 `prefers-reduced-motion: reduce`。
- 任何需要改变用户操作顺序、删除入口、合并步骤、改变默认值或改变成功/失败反馈的 UX 冲突，立即停止实施并询问用户。
- 每项生产代码变更必须先新增失败测试并确认 RED，再实现并确认 GREEN。
- 不新增前端依赖。

---

## 文件结构

- 新建 `src/components/creation/LoadingOverlay.jsx`：无业务状态的科技感加载层。
- 新建 `src/components/creation/StepWizard.jsx`：无业务状态的步骤导航。
- 新建 `src/components/creation/CreationUx.preview.test.js`：加载层、步骤条和动画降级契约。
- 修改 `src/pages/ContentCreation.jsx`：连接视觉组件，保留现有内容创作状态与处理函数。
- 修改 `src/pages/ContentCreation.preview.test.js`：同时验证新 UX 与现有业务恢复、轮询和发布能力。
- 新建 `src/components/process/WorkflowMatrix.jsx`：流程阶段矩阵展示。
- 新建 `src/components/process/WorkflowDetailDrawer.jsx`：流程详情和操作入口展示。
- 新建 `src/components/process/WorkflowPublishModal.jsx`：流程发布确认、状态时间线和失败恢复展示。
- 新建 `src/utils/workflowPublish.js`：从已保存创作恢复发布草稿并构建发布请求。
- 新建 `src/utils/workflowPublish.test.js`：发布草稿、媒体和请求契约。
- 修改 `src/hooks/useStarxApp.js`：按 `creationId` 隔离发布状态并提供只读的任务创作加载函数。
- 修改 `src/pages/ProcessManagement.jsx`：将现有筛选、分页和动作连接到新展示组件。
- 新建 `src/pages/ProcessManagement.preview.test.js`：流程视觉结构与回调连接契约。
- 新建（后端仓库）`app/services/publish_attempts.py` 与 `alembic/versions/20260716_000022_creation_publish_attempts.py`：独立尝试领域状态、并发预留及可逆数据迁移。
- 修改（后端仓库）`app/services/autophone_service.py`、`app/api/routes/creations.py`、`app/api/routes/tasks.py`、`app/db/models.py`、`app/schemas/creations.py`、`app/services/db_service.py`：严格发布门禁、不确定提交恢复和尝试投影。
- 新建（后端仓库）`tests/test_publish_attempt_reliability.py`、`tests/test_publish_attempt_migration.py`，修改 `tests/test_publish_api.py`、`tests/test_autophone_service.py`：门禁、可靠性和迁移契约。
- 修改 `src/pages/CompetitorMonitor.jsx` 和 `src/pages/CompetitorMonitor.preview.test.js`：真实监控状态接入 `Kim` 视觉层。
- 修改 `src/pages/TopicCenter.jsx` 和 `src/pages/TopicCenter.preview.test.js`：选题筛选、推荐卡片和创建反馈视觉。
- 修改 `src/pages/AccountProfile.jsx`、`src/components/KnowledgeBaseModal.jsx`：账号视觉以及知识库管理/编辑模式、焦点和忙碌态关闭锁。
- 新建 `src/components/knowledge-base/KnowledgeBaseManager.jsx`、`src/components/knowledge-base/KnowledgeBaseEditor.jsx`：真实列表与两步编辑器。
- 新建 `src/styles/account-profile.css`、`src/styles/knowledge-base.css`：账号与知识库隔离样式和减少动态降级。
- 新建 `src/pages/AccountProfile.preview.test.js`：账号、知识库和业务入口共存契约。
- 修改 `src/pages/Toolbox.jsx`：持有三个工具的共享状态与真实处理函数。
- 新建 `src/components/toolbox/ToolboxNav.jsx`：`Kim` 风格侧栏及当前工具可访问状态。
- 新建 `src/components/toolbox/AiImageWorkspace.jsx`、`src/components/toolbox/ScriptRewriteWorkspace.jsx`、`src/components/toolbox/ProhibitedWordWorkspace.jsx`：三个 `develop` 工具的展示工作区。
- 新建 `src/styles/toolbox.css`：工具箱隔离视觉、响应式布局和减少动态降级。
- 新建 `src/pages/Toolbox.preview.test.js`：模块边界、状态保持、可访问名称、真实动作和账号报告隔离契约。
- 修改 `src/styles/components.css`、`src/styles/pages.css`：按命名空间移植其他页面实际使用的样式。

---

### Task 1: 科技感加载层与步骤导航

**Files:**
- Create: `src/components/creation/LoadingOverlay.jsx`
- Create: `src/components/creation/StepWizard.jsx`
- Create: `src/components/creation/CreationUx.preview.test.js`
- Modify: `src/styles/components.css`

**Interfaces:**
- Consumes: `LoadingOverlay({ message, subMessage, progress, showProgress = true })`；`StepWizard({ steps, currentStep, onStepClick, completedSteps = [] })`。
- Produces: 内容创作和选题中心可复用的展示组件；不产生业务状态。

- [x] **Step 1: 写视觉组件失败测试**

```js
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const readOptional = (url) => existsSync(url) ? readFileSync(url, "utf8") : "";
const loading = readOptional(new URL("./LoadingOverlay.jsx", import.meta.url));
const wizard = readOptional(new URL("./StepWizard.jsx", import.meta.url));
const styles = readFileSync(new URL("../../styles/components.css", import.meta.url), "utf8");

test("loading overlay exposes real message progress and timer cleanup", () => {
  assert.notEqual(loading, "");
  assert.match(loading, /message, subMessage, progress, showProgress = true/);
  assert.match(loading, /return \(\) => clearInterval\(timer\)/);
  assert.match(loading, /loading-spinner-ring/);
  assert.match(styles, /\.loading-overlay\s*\{/);
});

test("step wizard is controlled by the page", () => {
  assert.notEqual(wizard, "");
  assert.match(wizard, /steps, currentStep, onStepClick, completedSteps/);
  assert.match(wizard, /onStepClick\?\.\(index\)/);
  assert.doesNotMatch(wizard, /fetch\(|starxApi|setInterval/);
});

test("continuous animation respects reduced motion", () => {
  assert.match(styles, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
});
```

- [x] **Step 2: 运行测试并确认 RED**

Run: `npm test -- src/components/creation/CreationUx.preview.test.js`

Expected: FAIL，原因是 `LoadingOverlay.jsx` 或 `StepWizard.jsx` 不存在。

- [x] **Step 3: 实现无业务状态的视觉组件**

`LoadingOverlay.jsx` 使用两个可清理计时器：一个轮换辅助文案，一个仅在没有真实 `progress` 时把视觉进度缓动到 90%。`StepWizard.jsx` 只根据传入属性计算完成、当前和可点击状态。

```jsx
export default function StepWizard({ steps, currentStep, onStepClick, completedSteps = [] }) {
  const denominator = Math.max(steps.length - 1, 1);
  return <div className="step-wizard" aria-label="创作进度">
    <div className="step-wizard-line-bg" aria-hidden="true">
      <div className="step-wizard-line-fill" style={{ width: `${(currentStep / denominator) * 100}%` }} />
    </div>
    <div className="step-wizard-nodes">{steps.map((step, index) => {
      const completed = completedSteps.includes(index) || index < currentStep;
      const clickable = completed || index <= currentStep;
      return <button type="button" key={step.id} className={`step-wizard-node ${index === currentStep ? "current" : ""} ${completed ? "completed" : ""}`} disabled={!clickable} onClick={() => onStepClick?.(index)}>
        <span className="step-wizard-circle">{completed && index !== currentStep ? "✓" : index + 1}</span>
        <span className="step-wizard-label"><strong>{step.label}</strong>{step.description ? <small>{step.description}</small> : null}</span>
      </button>;
    })}</div>
  </div>;
}
```

- [x] **Step 4: 移植最小命名空间样式和动画降级**

```css
.loading-overlay { position: fixed; inset: 0; z-index: 1200; display: grid; place-items: center; }
.loading-spinner-ring { position: relative; width: 132px; height: 132px; }
.step-wizard { position: relative; width: min(720px, 100%); margin-inline: auto; }
@media (prefers-reduced-motion: reduce) {
  .loading-spinner-ring .ring,
  .loading-particles .particle { animation: none !important; }
}
```

- [x] **Step 5: 运行组件测试并确认 GREEN**

Run: `npm test -- src/components/creation/CreationUx.preview.test.js`

Expected: PASS。

- [x] **Step 6: 提交视觉基础组件**

```bash
git add src/components/creation/LoadingOverlay.jsx src/components/creation/StepWizard.jsx src/components/creation/CreationUx.preview.test.js src/styles/components.css
git commit -m "feat: add Kim-inspired creation UX primitives"
```

---

### Task 2: 内容创作页面 UX 与发布交接数据

**Files:**
- Modify: `src/pages/ContentCreation.jsx`
- Modify: `src/pages/ContentCreation.preview.test.js`
- Modify: `src/styles/pages.css`

**Interfaces:**
- Consumes: Task 1 的 `LoadingOverlay` 和 `StepWizard`。
- Produces: `creationState.publishMediaCandidates: Array<{ url: string, kind: "image" | "video", label: string }>` 与 `creationState.publishCopy: string`，供流程管理发布。
- Produces: 图文三步、视频两步的 `currentStep` 和 `completedSteps`，持久化为 `creationWizardStep` 与 `completedCreationWizardSteps`。

- [x] **Step 1: 增加新 UX、业务保留和发布交接失败测试**

```js
test("content creation connects Kim UX and persists workflow publish inputs", () => {
  assert.match(contentCreationSource, /import LoadingOverlay from "\.\.\/components\/creation\/LoadingOverlay"/);
  assert.match(contentCreationSource, /import StepWizard from "\.\.\/components\/creation\/StepWizard"/);
  assert.match(contentCreationSource, /creation-ux-shell/);
  assert.match(contentCreationSource, /publishMediaCandidates/);
  assert.match(contentCreationSource, /publishCopy:/);
  assert.match(contentCreationSource, /const IMAGE_STEPS = \[/);
  assert.match(contentCreationSource, /const VIDEO_STEPS = \[/);
  assert.match(contentCreationSource, /creationWizardStep/);
  assert.match(contentCreationSource, /completedCreationWizardSteps/);
  assert.match(contentCreationSource, /pendingScriptRewriteJobKey/);
  assert.match(contentCreationSource, /pendingImageJobKey/);
  assert.match(contentCreationSource, /restorePersistedImagePromptPlan/);
  assert.match(contentCreationSource, /restoreVideoScriptDraft/);
});
```

- [x] **Step 2: 运行内容创作测试并确认 RED**

Run: `npm test -- src/pages/ContentCreation.preview.test.js`

Expected: FAIL，缺少视觉组件引用或发布交接字段。

- [x] **Step 3: 建立可持久化的分步状态**

```jsx
import LoadingOverlay from "../components/creation/LoadingOverlay";
import StepWizard from "../components/creation/StepWizard";

const IMAGE_STEPS = [
  { id: "reference", label: "素材参考", description: "上传、解析或选择历史素材" },
  { id: "style", label: "风格选择", description: "选择标签和图片计划偏好" },
  { id: "generate", label: "提示词与生成结果", description: "编辑提示词、生成并保存" },
];
const VIDEO_STEPS = [
  { id: "reference", label: "素材参考", description: "解析视频并确认分析结果" },
  { id: "script", label: "脚本创作", description: "编辑、改写并保存脚本" },
];

const [currentStep, setCurrentStep] = useState(app.creation.creationState?.creationWizardStep || 0);
const [completedSteps, setCompletedSteps] = useState(app.creation.creationState?.completedCreationWizardSteps || []);
```

增加 `completeStep(stepIndex, nextStep)` 和只允许进入已完成步骤或当前步骤的 `handleStepClick(stepIndex)`。当 `app.creation.creationId` 变化时，从 `creationState` 恢复两个状态。

- [x] **Step 4: 将真实忙碌状态映射到加载层**

```jsx
const loadingOverlayMessage = extractingLink
  ? "正在解析素材链接..."
  : reversing
    ? "正在反推图片提示词..."
    : generating || submitting
      ? "正在生成图片..."
      : busy === "video-script"
        ? "正在生成视频脚本..."
        : "";

{loadingOverlayMessage ? <LoadingOverlay message={loadingOverlayMessage} /> : null}
<StepWizard steps={type === "image" ? IMAGE_STEPS : VIDEO_STEPS} currentStep={currentStep} completedSteps={completedSteps} onStepClick={handleStepClick} />
```

不得让视觉进度改变 `extractingLink`、`reversing`、`generating`、`submitting` 或 `busy`。

- [x] **Step 5: 保存步骤与流程发布所需数据**

在 `buildCreationState` 前定义：

```js
const buildPublishMediaCandidates = () => type === "video"
  ? [getPublishVideoUrl()].filter(Boolean).map((url) => ({ url, kind: "video", label: "创作视频" }))
  : getSelectedVariantAssets(imageGroups, selectedVariants).map((asset, index) => ({ url: asset.url, kind: "image", label: `生成图片 ${index + 1}` }));
```

在 `buildCreationState` 返回值中加入：

```js
publishMediaCandidates: buildPublishMediaCandidates(),
publishCopy: type === "video" ? videoPublishText.trim() : copyText.trim(),
creationWizardStep: currentStep,
completedCreationWizardSteps: completedSteps,
```

将 `getPublishVideoUrl` 移到 `buildCreationState` 之前，保持其当前 URL 解析优先级不变。

- [x] **Step 6: 按用户确认的步骤分配现有功能**

根节点改为 `className={`creation-page creation-ux-shell creation-ux-${type}`}`。图文第 0 步渲染上传、链接解析、提取历史和反推入口；第 1 步渲染标签、标签管理和图片提示词计划偏好；第 2 步渲染提示词编辑、素材图、生图任务、结果、最近任务、反推历史、预览和保存到流程。视频第 0 步渲染链接解析、视频分析和分析历史；第 1 步渲染脚本包、改写、发布文案和保存到流程。

异步操作成功时只调用 `completeStep` 推进其对应步骤；失败时停留当前步骤并显示现有错误。返回已完成步骤不得清空后续表单和任务结果。

- [x] **Step 7: 运行内容创作测试与完整测试**

Run: `npm test -- src/pages/ContentCreation.preview.test.js`

Expected: PASS。

Run: `npm test`

Expected: 全部测试 PASS。

- [x] **Step 8: 提交内容创作 UX 与交接数据**

```bash
git add src/pages/ContentCreation.jsx src/pages/ContentCreation.preview.test.js src/styles/pages.css
git commit -m "feat: prepare Kim creation UX for workflow publishing"
```

---

### Task 3: 按创作隔离的发布领域支持

**Files:**
- Create: `src/utils/workflowPublish.js`
- Create: `src/utils/workflowPublish.test.js`
- Modify: `src/hooks/useStarxApp.js`
- Modify: `src/pages/ContentCreation.preview.test.js`

**Interfaces:**
- Produces: `buildWorkflowPublishDraft(creation, task)`、`buildWorkflowPublishPayload(draft)`、`isWorkflowPublishActive(status)`、`app.loadTaskCreation(task)`、`app.publishStates[creationId]`。

- [x] **Step 1: 写发布草稿与状态隔离失败测试**

```js
import { buildWorkflowPublishDraft, buildWorkflowPublishPayload } from "./workflowPublish.js";

test("buildWorkflowPublishDraft restores persisted workflow media", () => {
  assert.deepEqual(buildWorkflowPublishDraft({
    creationId: "creation-1",
    type: "video",
    targetPlatform: "抖音",
    content: { body: "正文" },
    creationState: { publishCopy: "发布文案", publishMediaCandidates: [{ url: "https://cdn.test/a.mp4", kind: "video", label: "创作视频" }] },
  }, { id: "task-1" }), {
    creationId: "creation-1", taskId: "task-1", type: "video", targetPlatform: "抖音", description: "发布文案",
    mediaCandidates: [{ url: "https://cdn.test/a.mp4", kind: "video", label: "创作视频" }], selectedMediaUrl: "https://cdn.test/a.mp4", visibility: "0", copyToAlbum: true,
  });
});

test("buildWorkflowPublishPayload sends the selected saved media", () => {
  assert.deepEqual(buildWorkflowPublishPayload({ selectedMediaUrl: "https://cdn.test/a.png", description: "文案", visibility: "1", copyToAlbum: false }), {
    assetList: ["https://cdn.test/a.png"], filename: "a.png", description: "文案", visibility: "1", copyToAlbum: false,
  });
});
```

- [x] **Step 2: 运行工具测试并确认 RED**

Run: `npm test -- src/utils/workflowPublish.test.js`

Expected: FAIL，模块不存在。

- [x] **Step 3: 实现纯发布转换函数**

`buildWorkflowPublishDraft` 优先读取 `creation.creationState.publishMediaCandidates`，兼容回退到 `creation.content.assets`；发布文案优先 `publishCopy`，再回退到 `content.body` 和 `task.body`。`buildWorkflowPublishPayload` 只接受 HTTPS 媒体 URL，并从 URL 路径生成文件名；无合法媒体时抛出 `请选择可发布的 HTTPS 素材`。

- [x] **Step 4: 运行工具测试并确认 GREEN**

Run: `npm test -- src/utils/workflowPublish.test.js`

Expected: PASS。

- [x] **Step 5: 在应用 Hook 中按 creationId 记录发布状态**

```js
const [publishStates, setPublishStates] = useState({});
const loadTaskCreation = useCallback(async (task) => {
  if (!currentAccountId || !task?.creationId) throw new Error("这个流程没有关联创作内容");
  return starxApi.getCreation(currentAccountId, task.creationId);
}, [currentAccountId]);
```

`publishCreation` 和 `refreshPublishStatus` 收到结果后都执行：

```js
setPublishStates((prev) => ({ ...prev, [creationId]: recorded }));
setCreation((prev) => prev.creationId === creationId ? normalizeCreationRecord({
  ...prev,
  creationState: { ...prev.creationState, publish: recorded, publishHistory: [...(prev.creationState?.publishHistory || []), recorded].slice(-50) },
}) : prev);
```

将 `loadTaskCreation` 和 `publishStates` 加入 Hook 返回值；账号切换和退出登录时执行 `setPublishStates({})`。不得让历史任务发布改变另一条当前创作的 `creationId` 或内容。

- [x] **Step 6: 增加 Hook 源码契约并运行完整测试**

在 `ContentCreation.preview.test.js` 读取 `useStarxApp.js`，断言存在 `publishStates`、`loadTaskCreation` 和 `prev.creationId === creationId`。

Run: `npm test`

Expected: 全部测试 PASS。

- [x] **Step 7: 提交发布领域支持**

```bash
git add src/utils/workflowPublish.js src/utils/workflowPublish.test.js src/hooks/useStarxApp.js src/pages/ContentCreation.preview.test.js
git commit -m "feat: support workflow-managed publish state"
```

---

### Task 4: 流程矩阵、详情抽屉与唯一发布入口

**Files:**
- Create: `src/components/process/WorkflowMatrix.jsx`
- Create: `src/components/process/WorkflowDetailDrawer.jsx`
- Create: `src/components/process/WorkflowPublishModal.jsx`
- Create: `src/pages/ProcessManagement.preview.test.js`
- Modify: `src/pages/ProcessManagement.jsx`
- Modify: `src/pages/ContentCreation.jsx`
- Modify: `src/pages/ContentCreation.preview.test.js`
- Modify: `src/styles/pages.css`
- Modify（后端仓库）: `app/api/routes/creations.py`
- Modify（后端仓库）: `app/api/routes/tasks.py`
- Modify（后端仓库）: `app/db/models.py`
- Modify（后端仓库）: `app/schemas/creations.py`
- Modify（后端仓库）: `app/services/autophone_service.py`
- Modify（后端仓库）: `app/services/db_service.py`
- Create（后端仓库）: `app/services/publish_attempts.py`
- Create（后端仓库）: `alembic/versions/20260716_000022_creation_publish_attempts.py`
- Modify（后端仓库）: `tests/test_publish_api.py`
- Modify（后端仓库）: `tests/test_autophone_service.py`
- Create（后端仓库）: `tests/test_publish_attempt_reliability.py`
- Create（后端仓库）: `tests/test_publish_attempt_migration.py`

**Interfaces:**
- Consumes: Task 3 的发布转换函数、`app.loadTaskCreation`、`app.publishCreation`、`app.refreshPublishStatus`、`app.publishStates`。
- Produces: 流程管理唯一发布入口；展示组件不直接调用 `app`。
- Produces: 服务端原始 `pending_review` 状态闸门、严格可见性映射、失败或取消后使用递增外部 ID 的独立发布尝试历史，以及不确定提交的同尝试恢复语义。

- [x] **Step 1: 写流程发布与入口切换失败测试**

```js
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import { canPublishWorkflowTask } from "../utils/workflowProcess.js";

const readOptional = (url) => existsSync(url) ? readFileSync(url, "utf8") : "";
const pageSource = readOptional(new URL("./ProcessManagement.jsx", import.meta.url));
const drawerSource = readOptional(new URL("../components/process/WorkflowDetailDrawer.jsx", import.meta.url));
const contentCreationSource = readOptional(new URL("./ContentCreation.jsx", import.meta.url));

test("workflow drawer is the only publish entry", () => {
  assert.match(pageSource, /WorkflowPublishModal/);
  assert.match(pageSource, /app\.loadTaskCreation/);
  assert.match(pageSource, /app\.publishCreation/);
  assert.match(pageSource, /app\.refreshPublishStatus/);
  assert.match(pageSource, /canPublishWorkflowTask/);
  assert.match(drawerSource, /onPublish\?\.\(task\)/);
  assert.match(drawerSource, /canPublish/);
  assert.doesNotMatch(contentCreationSource, /onClick=\{openPublishConfirm\}/);
  assert.doesNotMatch(contentCreationSource, /showPublishConfirm && pendingPublishDraft/);
});

test("publish authorization rejects normalized aliases", () => {
  assert.equal(canPublishWorkflowTask({ status: "pending_review", creationId: "creation-1" }), true);
  assert.equal(canPublishWorkflowTask({ status: "pending", creationId: "creation-1" }), false);
  assert.equal(canPublishWorkflowTask({ status: "pending_publish", creationId: "creation-1" }), false);
});
```

- [x] **Step 2: 运行测试并确认 RED**

Run: `npm test -- src/pages/ProcessManagement.preview.test.js src/pages/ContentCreation.preview.test.js`

Expected: FAIL，流程发布组件不存在且内容创作仍含直接发布。

- [x] **Step 3: 创建受控矩阵、抽屉和发布弹窗**

`WorkflowMatrix({ columns, selectedTaskId, onSelectTask })` 渲染阶段列和受控选中状态；`WorkflowDetailDrawer({ task, canPublish, onClose, onAdvance, onMove, onOpen, onPublish })` 只在 `canPublish` 为真时渲染发布按钮；`WorkflowPublishModal({ draft, publishState, deviceConfigured, busy, onChange, onConfirm, onRefresh, onConfigureDevice, onClose })` 渲染媒体选择、文案、可见性、保存相册、时间线、失败重试和设备配置。

三个组件只调用传入回调，不导入 API 或 Hook。

- [x] **Step 4: 在 ProcessManagement 编排发布流程**

```js
const openPublish = async (task) => {
  if (!canPublishWorkflowTask(task)) return;
  const creation = await app.loadTaskCreation(task);
  const latestTask = tasksRef.current.find((item) => item.id === task.id);
  if (!canPublishWorkflowTask(latestTask)) return;
  setPublishDraft(buildWorkflowPublishDraft(creation, latestTask));
  setPublishingTaskId(latestTask.id);
};
const confirmPublish = async () => {
  const latestTask = tasksRef.current.find((task) => task.id === publishingTaskId);
  if (!canPublishWorkflowTask(latestTask) || latestTask.creationId !== publishDraft.creationId) return;
  const retry = ["failed", "cancelled"].includes(app.publishStates[publishDraft.creationId]?.status);
  const payload = buildWorkflowPublishPayload({ ...publishDraft, retry });
  await app.publishCreation(publishDraft.creationId, payload);
};
```

当 `isWorkflowPublishActive(app.publishStates[publishDraft.creationId]?.status)` 为真时，每 5 秒调用 `app.refreshPublishStatus(publishDraft.creationId, { silent: true })`，并在弹窗关闭或状态终止时清理计时器。

向详情抽屉传入 `canPublish={canPublishWorkflowTask(selectedTask)}`。`canPublishWorkflowTask` 必须直接比较原始 `task.status` 并确认存在 `creationId`，不能调用 `normalizeWorkflowStatus`；其他阶段和旧别名只能使用现有阶段推进操作，不能打开发布弹窗。

页面在打开弹窗和确认发布前都从最新任务集合重新读取任务，并严格校验原始 `pending_review`；同步请求闸门阻止双击和状态切换竞态，发布 POST 进行中禁止通过 Escape、遮罩或关闭按钮退出弹窗。状态别名仍可用于矩阵展示、筛选和旧数据导航，但不能参与发布授权。

- [x] **Step 5: 扩展后端发布契约**

先在 `tests/test_publish_api.py`、`tests/test_publish_attempt_reliability.py`、`tests/test_publish_attempt_migration.py` 和 `tests/test_autophone_service.py` 增加失败测试，覆盖无关联任务、原始状态门禁、非法可见性、普通重复发布、独立重试、不确定提交和迁移降级。实现要求：

- `visibility` 仅接受字符串 `"0"`、`"1"`、`"2"`；请求增加布尔字段 `retry`，响应暴露当前 `attempt`。
- `description` 去除首尾空白后必须非空；空文案由请求校验拒绝，不使用创作正文兜底。
- 发布前重新读取创作关联任务，校验任务与创作属于同一账号、关联一致，且任务原始 `status` 严格等于 `pending_review`。`pending`、`pending_publish` 等别名必须拒绝；`000022` 迁移也不得静默改写这些旧任务状态，旧数据需通过正常流程推进到真实待发布状态。
- 首次发布保留既有外部任务 ID；仅当前权威终态为 `failed` 或 `cancelled` 且 `retry=true` 时创建递增的 `_attempt_N`，失败尝试的外部任务 ID 不得复用。普通重复请求、提交中重试和成功重试返回冲突错误。
- 先在短事务中预留独立尝试及外部任务 ID，再提交事务并调用外部服务；尝试状态更新必须保持终态单调，旧尝试的迟到回调不得覆盖较新的当前投影。
- 只有能够确认请求在发送前失败，或外部服务返回明确拒绝时，当前尝试才能写为 `failed`。`ReadError`、`WriteError`、外部 5xx、409 后状态恢复失败，以及其他无法确认是否已被接收的异常均保持原尝试和外部任务 ID，投影维持提交中，不开放重试。
- POST 和后续 GET 的成功响应都必须校验 `external_id` 与预留值一致且 `status` 非空；缺失、错配或空状态的畸形 2xx 按不确定提交处理，不得持久化空身份、伪造失败或创建下一次尝试。
- `000022_creation_publish_attempts` 升级创建独立尝试表并回填可识别的旧发布投影；降级在删除表前，按每条创作物化最新投影及最后 50 条尝试历史到旧 `content_creations.creation_state`，合并而不是替换原有 JSON 其他键。

Run: `conda run --no-capture-output -n starx pytest -q tests/test_publish_api.py tests/test_publish_attempt_reliability.py tests/test_publish_attempt_migration.py tests/test_autophone_service.py tests/test_database_init.py tests/test_db_service.py`

另用全新的 `/tmp` SQLite 数据库初始化后运行 API 流程测试，禁止连接开发者默认数据库：

Run: `STARX_DATABASE_URL=sqlite:////tmp/starx-kim-publish-api.sqlite conda run --no-capture-output -n starx python -m app.db.init_db`

Run: `STARX_DATABASE_URL=sqlite:////tmp/starx-kim-publish-api.sqlite conda run --no-capture-output -n starx pytest -q tests/test_api_flows.py`

Expected: 全部 PASS。

- [x] **Step 6: 完成入口切换**

从 `ContentCreation.jsx` 删除直接发布按钮、确认弹窗、页面内发布时间线及仅为这些视图服务的局部状态；保留 `getPublishVideoUrl` 供保存媒体候选，保留 `app.publishCreation` 和 `refreshPublishStatus` 在应用 Hook 中。更新原发布测试，使其验证流程管理弹窗拥有设备校验、请求、轮询、时间线、重试和配置入口。

- [x] **Step 7: 添加命名空间样式并验证**

Run: `npm test -- src/pages/ProcessManagement.preview.test.js src/pages/ContentCreation.preview.test.js src/utils/workflowPublish.test.js`

Expected: PASS。

Run: `npm test`

Expected: 全部测试 PASS。

- [x] **Step 8: 提交流程管理发布 UX**

```bash
git add src/components/process/WorkflowMatrix.jsx src/components/process/WorkflowDetailDrawer.jsx src/components/process/WorkflowPublishModal.jsx src/pages/ProcessManagement.jsx src/pages/ProcessManagement.preview.test.js src/pages/ContentCreation.jsx src/pages/ContentCreation.preview.test.js src/styles/pages.css
git commit -m "feat: move publishing into Kim workflow UX"
```

---

### Task 5: 竞品监控与选题中心 UX

**Files:**
- Modify: `src/pages/CompetitorMonitor.jsx`
- Modify: `src/pages/CompetitorMonitor.preview.test.js`
- Modify: `src/components/competitors/CompetitorAccountCard.jsx`
- Modify: `src/components/competitors/CompetitorVideoCard.jsx`
- Modify: `src/components/competitors/CompetitorAddModal.jsx`
- Modify: `src/components/competitors/CompetitorMetric.jsx`
- Modify: `src/components/CreationPreferenceModal.jsx`
- Modify: `src/pages/TopicCenter.jsx`
- Modify: `src/pages/TopicCenter.preview.test.js`
- Modify: `src/styles/pages.css`
- Create: `src/styles/competitor-monitor.css`
- Create: `src/styles/topic-center.css`

**Interfaces:**
- Consumes: `useCompetitorMonitoring` 的真实状态；`submitTopicCreation` 和 `CreationPreferenceModal`。
- Produces: 新视觉外壳，不改变监控和创作交接行为。

- [x] **Step 1: 增加两页 UX 失败测试**

```js
test("competitor UX renders real refresh summary in Kim visual shell", () => {
  assert.match(pageSource, /monitor-grid/);
  assert.match(pageSource, /refreshSummary/);
  assert.match(pageSource, /monitoring\.refreshAccounts/);
  assert.match(pageSource, /monitoring\.refreshVideos/);
  assert.match(accountCardSource, /glass-card monitor-card/);
  assert.match(videoCardSource, /glass-card monitor-card/);
});

test("topic UX keeps preference handoff and exposes loading feedback", () => {
  assert.match(topicCenterSource, /className="topic-ux-shell"/);
  assert.match(topicCenterSource, /CreationPreferenceModal/);
  assert.match(topicCenterSource, /submitTopicCreation/);
  assert.match(topicCenterSource, /LoadingOverlay/);
  assert.match(topicCenterSource, /app\.dashboard\?\.creation\s*\?\?\s*0/);
  assert.doesNotMatch(topicCenterSource, /const seed|hash\s*%|\|\|\s*5/);
});
```

- [x] **Step 2: 运行两个页面测试并确认 RED**

Run: `npm test -- src/pages/CompetitorMonitor.preview.test.js src/pages/TopicCenter.preview.test.js`

Expected: FAIL，缺少新页面外壳或创建反馈结构。

- [x] **Step 3: 重排竞品监控展示结构**

```jsx
<div className="competitor-page competitor-ux-shell">
  <div className="section-header competitor-page-header">
    <div>{标题与说明}</div>
    <div className="button-row">{模式切换、刷新全部、添加}</div>
  </div>
  <div className="competitor-summary" aria-label="刷新状态概览">
  <div className="monitor-grid">
```

账号和视频卡片使用 `Kim` 的 `glass-card monitor-card → monitor-card-top → monitor-thumb / 标题 → monitor-desc → monitor-metrics → 操作区` 外壳。桌面严格三列，1100px 两列，700px 单列；中等宽度把 `develop` 新增的批量刷新控制换到标题下方，避免挤压 `Kim` 标题。添加弹窗提供键盘焦点闭环和关闭后的焦点恢复。不得替换 `useCompetitorMonitoring`、真实外链、卡片删除确认或刷新函数；不得复制静态趋势、`example.com`、模拟新增内容和 URL 平台猜测。

- [x] **Step 4: 重排选题中心并连接真实创建状态**

```jsx
<div className="topic-ux-shell">
  <div className="section-header topic-ux-header">
  <div className="view-toggle-group topic-ux-filters">
  <div className="topic-grid topic-ux-grid">
  {isCreating ? <LoadingOverlay message="正在生成创作内容..." /> : null}
  {selectedTopic ? <CreationPreferenceModal variant={selectedTopic.type === "video" ? "video" : "image"} topic={selectedTopic} account={app.currentAccount} initialPreferences={retryPreferences} isSubmitting={isCreating} onCancel={closeCreationPreferences} onConfirm={confirmCreation} /> : null}
</div>
```

保持 `Kim` 的七项筛选、三列卡片、金色推荐位、标签和按钮层级；把统计内联样式整理为命名空间类。不得抽走 `openCreationPreferences`。加载反馈继续读取已经存在的 `isCreating`，且只在偏好确认后出现，不得改变 `submitTopicCreation` 的调用顺序。没有真实评分时显示“⭐ AI 推荐”，真实创作数读取 `app.dashboard?.creation ?? 0`。

- [x] **Step 5: 运行页面测试和完整测试**

Run: `npm test -- src/pages/CompetitorMonitor.preview.test.js src/pages/TopicCenter.preview.test.js`

Expected: PASS。

Run: `npm test`

Expected: 全部测试 PASS。

- [x] **Step 6: 提交竞品与选题 UX**

```bash
git add src/pages/CompetitorMonitor.jsx src/pages/CompetitorMonitor.preview.test.js src/components/competitors/CompetitorAccountCard.jsx src/components/competitors/CompetitorVideoCard.jsx src/components/competitors/CompetitorAddModal.jsx src/components/competitors/CompetitorMetric.jsx src/components/CreationPreferenceModal.jsx src/pages/TopicCenter.jsx src/pages/TopicCenter.preview.test.js src/styles/competitor-monitor.css src/styles/topic-center.css src/styles/pages.css
git commit -m "feat: port Kim monitoring and topic UX"
```

---

### Task 6: 账号资料与知识库 UX

**Files:**
- Modify: `src/pages/AccountProfile.jsx`
- Modify: `src/components/KnowledgeBaseModal.jsx`
- Create: `src/components/knowledge-base/KnowledgeBaseManager.jsx`
- Create: `src/components/knowledge-base/KnowledgeBaseEditor.jsx`
- Create: `src/pages/AccountProfile.preview.test.js`
- Create: `src/styles/account-profile.css`
- Create: `src/styles/knowledge-base.css`
- Modify（后端仓库）: `app/api/routes/knowledge_bases.py`
- Modify（后端仓库）: `app/db/models.py`
- Modify（后端仓库）: `app/models/account.py`
- Modify（后端仓库）: `app/schemas/knowledge_bases.py`
- Modify（后端仓库）: `app/services/db_service.py`
- Create（后端仓库）: `alembic/versions/20260716_000023_knowledge_base_industry.py`
- Modify（后端仓库）: `tests/test_api_flows.py`

**Interfaces:**
- Consumes: 当前账号分页、搜索、删除、编辑和知识库 CRUD 回调。
- Produces: 账号卡片、manager-first 知识库弹窗、两步编辑器，以及可创建、读取、更新并再次读取的知识库 `industry` 字段。

- [x] **Step 1: 写账号和知识库失败测试**

```js
test("account UX keeps paging search editing and knowledge base actions", () => {
  assert.match(accountSource, /className="account-profile-ux-shell"/);
  assert.match(accountSource, /loadAccountsPage/);
  assert.match(accountSource, /app\.openAccountModal/);
  assert.match(accountSource, /confirmDelete/);
  assert.match(managerSource, /app\.loadKnowledgeBasesPage/);
  assert.match(managerSource, /app\.deleteKnowledgeBase/);
  assert.match(editorSource, /form\.industry/);
  assert.match(editorSource, /app\.createKnowledgeBase\(payload\)/);
  assert.match(editorSource, /app\.updateKnowledgeBase\(app\.editingKnowledgeBase\.id, payload\)/);
});
```

- [x] **Step 2: 运行测试并确认 RED**

Run: `npm test -- src/pages/AccountProfile.preview.test.js`

Expected: FAIL，缺少 UX 外壳类。

- [x] **Step 3: 移植账号筛选、卡片和分页视觉**

```jsx
<div className="account-profile-ux-shell">
  <div className="account-toolbar account-profile-ux-header">
  <form className="inline-search account-profile-ux-filters" onSubmit={searchAccounts}>
  <div className="account-grid account-profile-ux-grid">
  <div className="pagination-row account-profile-ux-pagination" style={{ marginTop: 16 }}>
```

精确采用 `Kim` 的平台图标筛选、当前账号大卡、账号小卡、三列网格和操作层级；继续使用 `develop` 的每页 12 条、上一页/下一页和真实搜索，避免复制 `Kim` 会为大量数据生成全部页码按钮的做法。账号卡片内必须继续调用 `app.switchAccount`、`app.openAccountModal` 和 `confirmDelete`，不得保留无行为的省略号。

- [x] **Step 4: 移植知识库管理列表与两步编辑器视觉**

以 `KnowledgeBaseModal` 作为焦点管理和“管理/编辑”模式控制器，把列表与两步表单拆成独立组件。默认从 `Kim` 管理列表进入；连接 `knowledgeBaseList`、`knowledgeBasePage`、`loadKnowledgeBasesPage`、`openKnowledgeBaseModal` 和 `deleteKnowledgeBase`。

`KnowledgeBaseEditor` 第一步为基础资料，包含名称、产品名称、所属行业、官网和产品介绍；第二步为内容配置，包含品牌故事、价格、Logo、图片素材、联系方式和字段启用开关。它必须继续调用 `normalizeKnowledgeBasePayload`，并把 `industry` 连同其他字段传入真实创建/更新回调。移除伪“已保存草稿”和无行为展开按钮。

弹窗提供初始焦点、Tab / Shift+Tab 闭环、Escape 与遮罩关闭、触发按钮焦点恢复；保存或删除期间锁定重复提交，并禁止关闭按钮、Escape 和遮罩中断操作。`knowledge-base.css` 中的旋转加载和非必要过渡必须在 `prefers-reduced-motion: reduce` 下停用。

- [x] **Step 5: 补齐知识库行业字段的后端持久化**

先在 `tests/test_api_flows.py` 增加创建、详情读取、更新和再次读取测试，证明 `industry` 不只存在于前端表单。实现要求：

- 为 `KnowledgeBaseSchema`、`CreateKnowledgeBaseRequest` 和 `UpdateKnowledgeBaseRequest` 增加 `industry`，创建请求默认可兼容空串，更新请求允许省略。
- 为 `KnowledgeBase` 领域模型和 `KnowledgeBaseRecord` 增加 `industry`；迁移为现有记录写入非空默认空串。
- `knowledge_bases` 路由把字段传给 `DBService`，`_knowledge_base_from_record`、`create_knowledge_base` 和 `update_knowledge_base` 完整映射并回传该字段。
- 创建后 GET、PATCH 后 GET 均返回归一化后的行业值；不得只在 POST/PATCH 响应中回显请求值。

Run: `STARX_DATABASE_URL=sqlite:////tmp/starx-kim-knowledge-industry.sqlite conda run --no-capture-output -n starx python -m app.db.init_db`

Run: `STARX_DATABASE_URL=sqlite:////tmp/starx-kim-knowledge-industry.sqlite conda run --no-capture-output -n starx pytest -q tests/test_api_flows.py`

Expected: 全部 PASS。

- [x] **Step 6: 验证并提交**

Run: `npm test -- src/pages/AccountProfile.preview.test.js src/utils/accountProfileForm.test.js`

Expected: PASS。

Run: `npm test`

Expected: 全部测试 PASS。

```bash
git add src/pages/AccountProfile.jsx src/components/KnowledgeBaseModal.jsx src/components/knowledge-base/KnowledgeBaseManager.jsx src/components/knowledge-base/KnowledgeBaseEditor.jsx src/pages/AccountProfile.preview.test.js src/styles/account-profile.css src/styles/knowledge-base.css docs/superpowers/plans/2026-07-16-kim-ux-port.md docs/superpowers/specs/2026-07-16-kim-ux-port-design.md
git commit -m "feat: port Kim account and knowledge UX"
```

后端仓库单独提交知识库领域字段及迁移，不与前端提交混合：

```bash
git add app/api/routes/knowledge_bases.py app/db/models.py app/models/account.py app/schemas/knowledge_bases.py app/services/db_service.py alembic/versions/20260716_000023_knowledge_base_industry.py tests/test_api_flows.py
git commit -m "feat: persist knowledge base industry"
```

---

### Task 7: 工具箱 UX 与账号报告隔离保护

**Files:**
- Modify: `src/pages/Toolbox.jsx`
- Create: `src/components/toolbox/ToolboxNav.jsx`
- Create: `src/components/toolbox/AiImageWorkspace.jsx`
- Create: `src/components/toolbox/ScriptRewriteWorkspace.jsx`
- Create: `src/components/toolbox/ProhibitedWordWorkspace.jsx`
- Create: `src/styles/toolbox.css`
- Create: `src/pages/Toolbox.preview.test.js`

**Interfaces:**
- Consumes: 工具箱现有 `tab`、对话、脚本输入、违禁词文案与检测结果，以及 `app.materials` / `app.addToast`。
- Produces: 强参考 `Kim` 的侧栏与工作区视觉，但只暴露 `develop` 的“AI对话生图”“脚本改写”“违禁词检测”三项真实工具；所有可编辑状态仍由 `Toolbox.jsx` 持有。

- [x] **Step 1: 写模块边界、状态保持和账号报告保护失败测试**

```js
test("toolbox uses Kim sidebar and workspace shell with the develop tool set", () => {
  assert.match(toolboxSource, /<ToolboxNav/);
  assert.match(toolboxSource, /<AiImageWorkspace/);
  assert.match(toolboxSource, /<ScriptRewriteWorkspace/);
  assert.match(toolboxSource, /<ProhibitedWordWorkspace/);
  for (const label of ["AI对话生图", "脚本改写", "违禁词检测"]) {
    assert.match(navSource, new RegExp(label));
  }
  assert.doesNotMatch(navSource, /一键解析|一键转写|封面制作/);
});

test("switching tools keeps editable state and accessible names", () => {
  assert.match(toolboxSource, /videoLink=\{scriptLink\}/);
  assert.match(toolboxSource, /rewriteRequest=\{rewriteRequest\}/);
  assert.match(navSource, /aria-label="工具箱导航"/);
  assert.match(navSource, /aria-current/);
  assert.match(imageSource, /aria-label="生图描述"/);
  assert.match(checkSource, /aria-label="待检测文案"/);
});

test("toolbox work stays isolated from account report", () => {
  assert.doesNotMatch(accountReportSource, /toolbox-ux-shell|toolbox-nav|toolbox-workspace/);
  assert.doesNotMatch(toolboxStyles, /\.account-report|\.report-/);
});
```

- [x] **Step 2: 运行测试并确认 RED**

Run: `npm test -- src/pages/Toolbox.preview.test.js`

Expected: FAIL，原因是工具箱展示组件或 `toolbox.css` 尚不存在。

- [x] **Step 3: 拆分 `Kim` 侧栏与三个真实工作区**

`Toolbox.jsx` 保留 `tab`、`message`、`messages`、`scriptLink`、`rewriteRequest`、`text`、`found` 以及 `send`、检测和一键替换处理函数；这些状态不能下沉到条件渲染的工作区，否则切换标签后会丢失。

```jsx
<div className="toolbox-shell toolbox-ux-shell">
  <ToolboxNav activeTool={tab} onSelect={setTab} />
  <section className="toolbox-main">
    {tab === "ai" ? <AiImageWorkspace {...imageProps} /> : null}
    {tab === "script" ? <ScriptRewriteWorkspace {...scriptProps} /> : null}
    {tab === "check" ? <ProhibitedWordWorkspace {...checkProps} /> : null}
  </section>
</div>
```

- `ToolboxNav` 采用 `Kim` 的左侧品牌栏与工具卡，提供 `aria-label="工具箱导航"` 和当前项 `aria-current`。
- `AiImageWorkspace` 采用参考图、对话、生图素材库三栏，连接真实 `app.materials`、对话发送和重置；不得引入 `picsum.photos`、`fakeImage`、`TAG_CATEGORIES`、`saveMaterial` 或假网络素材。
- `ScriptRewriteWorkspace` 保留视频链接、改写要求、开始改写和结果区；`ProhibitedWordWorkspace` 保留检测、清空和一键替换。
- 文本输入必须由可见 `<label>` 或稳定 `aria-label` 命名，动态对话和检测结果使用 `aria-live`；工作区内部不得再创建 `<main>`，避免重复主地标。

- [x] **Step 4: 新建隔离的工具箱视觉样式**

所有规则放入 `src/styles/toolbox.css`，并以 `.toolbox-ux-shell` 为祖先。桌面端保持 `Kim` 的侧栏和生图三栏比例，中等宽度重排，700px 以下单列；非必要过渡在 `prefers-reduced-motion: reduce` 下关闭。不得修改 `AccountReport.jsx`、账号报告专属样式、`layout.css` 或 `pages.css`，也不得新增 `.account-report` / `.report-` 规则。

- [x] **Step 5: 验证并提交**

Run: `npm test -- src/pages/Toolbox.preview.test.js src/pages/AccountReport.preview.test.js`

Expected: PASS。

Run: `npm test`

Expected: 全部测试 PASS。

```bash
git add src/pages/Toolbox.jsx src/components/toolbox/ToolboxNav.jsx src/components/toolbox/AiImageWorkspace.jsx src/components/toolbox/ScriptRewriteWorkspace.jsx src/components/toolbox/ProhibitedWordWorkspace.jsx src/styles/toolbox.css src/pages/Toolbox.preview.test.js
git commit -m "feat: port Kim toolbox UX"
```

---

### Task 8: 全量验证与移植范围审计

**Files:**
- Verify only: all changed frontend and backend files

**Interfaces:**
- Consumes: Tasks 1–7 的全部成果。
- Produces: 可合并到 `develop` 的验证证据。

- [x] **Step 1: 运行完整测试**

Run: `npm test`

Expected: 0 failures。

- [x] **Step 2: 运行生产构建**

Run: `npm run build`

Expected: Vite 构建成功且退出码为 0。

- [x] **Step 3: 检查差异格式**

Run: `git diff --check`

Expected: 无输出，退出码为 0。

- [x] **Step 4: 审计账号报告未修改**

Run: `git diff 45524dd -- src/pages/AccountReport.jsx`

Expected: 无输出。

- [x] **Step 5: 审计未移植旧业务实现**

Run: `git diff 45524dd -- src/api`

Expected: 无输出；本次 UX 移植不修改 API 客户端。

Run: `git diff 45524dd -- src/hooks/useStarxApp.js`

Expected: 只包含 `publishStates`、`loadTaskCreation`、按 `creationId` 隔离发布状态、账号切换清理和知识库 `industry` 响应缺省归一化；不得包含生成、分析、账号报告或其他领域逻辑改写。

Run: `git status --short`

Expected: 除计划执行产生的已提交记录外，工作区干净。

- [x] **Step 6: 在隔离数据库验证后端发布可靠性与迁移**

Run: `conda run --no-capture-output -n starx pytest -q tests/test_publish_api.py tests/test_publish_attempt_reliability.py tests/test_publish_attempt_migration.py tests/test_autophone_service.py tests/test_database_init.py tests/test_db_service.py`

用全新 `/tmp` SQLite 数据库执行初始化和 API 流程；不得使用默认 PostgreSQL：

Run: `STARX_DATABASE_URL=sqlite:////tmp/starx-kim-final.sqlite conda run --no-capture-output -n starx python -m app.db.init_db`

Run: `STARX_DATABASE_URL=sqlite:////tmp/starx-kim-final.sqlite conda run --no-capture-output -n starx pytest -q tests/test_api_flows.py`

Expected: 原始状态发布门禁、独立尝试、不确定提交、畸形 2xx、`000022` 升降级和知识库 `industry` 端到端测试全部 PASS。

- [x] **Step 7: 检查后端差异与语法**

Run: `conda run --no-capture-output -n starx python -m compileall -q app alembic/versions`

Run: `git diff --check`

Expected: 两条命令退出码均为 0，且差异检查无输出。

- [x] **Step 8: 汇总页面、测试和构建结果**

最终报告必须列出：移植页面、明确排除的账号报告、前后端完整测试数量、构建结果、发布门禁与不确定提交验证、迁移升降级验证、知识库行业字段回读验证，以及所有 UX 冲突询问及用户决策。

## 最终验证记录

- 前端全量测试：`275 passed`。
- 前端生产构建：Vite 成功转换 `99 modules`。
- 后端完整测试：在显式 `/tmp` SQLite 数据库中执行，`632 passed`。
- 发布与迁移联合回归：`91 passed`；Alembic 只有 `20260716_000023` 一个 head。
- `000022` 降级投影与最后 50 条历史回填、`000023` 行业字段升降级、知识库创建/更新/详情/列表回读均通过。
- `git diff 45524dd -- src/pages/AccountReport.jsx src/pages/account-report src/styles/account-report.css` 无输出；账号报告保持排除。
- 浏览器逐屏验收覆盖账号档案、知识库管理/两步编辑、焦点恢复和工具箱跨标签状态保持；未写入验收临时数据。
- 完整回归发现并修复两项既有测试隔离问题：提取历史可继续独立绑定外部 `creationId` 和任务 ID，但任务自身的 `creation_id` 遵守真实创作外键与租户约束；生成 API 测试显式注入假存储，避免访问真实 OSS。
