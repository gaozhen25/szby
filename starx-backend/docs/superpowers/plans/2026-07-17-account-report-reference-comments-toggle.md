# 账号报告参考评论开关实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为账号报告增加默认关闭的“参考内容评论”开关，关闭时既不采集评论，也不向 AI 提供评论证据。

**Architecture:** 前端把页面会话内的布尔选择传给账号报告创建接口，后端将其作为 workflow 不可变输入持久化。工作流用该输入覆盖本次 MediaSpider 评论参数，并在 AI 证据边界再次移除评论，形成采集层与提示词层双重隔离。

**Tech Stack:** React、Node.js test runner、FastAPI、Pydantic、SQLAlchemy、pytest、MediaSpider。

## Global Constraints

- 设计与实施文档使用中文。
- 后端测试必须使用名为 `starx` 的 conda 环境。
- `referenceComments` 缺省值必须为 `false`。
- 页面刷新或切换账号后开关关闭；同一账号页面会话内保留选择。
- 不修改全局 MediaSpider 评论配置，不影响账号报告以外的爬取调用方。
- 关闭时当前账号与行业采集都不请求评论，AI 输入也不得包含评论证据。

---

### Task 1: 后端请求模型与 workflow 输入持久化

**Files:**
- Modify: `app/schemas/reports.py`
- Modify: `app/api/routes/reports.py`
- Modify: `app/services/workflow/service.py`
- Modify: `app/services/workflow/workflow_store.py`
- Test: `tests/test_account_report_api.py`
- Test: `tests/test_account_report_workflow.py`

**Interfaces:**
- Produces: `CreateAccountReportWorkflowRequest(referenceComments: bool = False)`。
- Produces: `WorkflowService.create_account_report_job(user_id, account_id, reference_comments=False)`。
- Produces: `account_report_context(...)["referenceComments"] -> bool`。

- [ ] **Step 1: 写 API 与存储上下文失败测试**

在 `tests/test_account_report_api.py` 增加空请求默认关闭、显式开启、复用活跃任务不覆盖输入的断言；在 `tests/test_account_report_workflow.py` 增加上下文只接受严格布尔值 `True` 的测试。核心断言：

```python
assert created.json()["inputPayload"]["referenceComments"] is False
assert enabled.json()["inputPayload"]["referenceComments"] is True
assert reused.json()["inputPayload"]["referenceComments"] is False
assert context["referenceComments"] is False
```

- [ ] **Step 2: 运行测试并确认失败原因是参数尚未实现**

Run:

```bash
conda run --no-capture-output -n starx pytest -q tests/test_account_report_api.py tests/test_account_report_workflow.py -k "reference_comments or repeated_report_refresh"
```

Expected: FAIL，响应或上下文缺少 `referenceComments`，或服务方法不接受新参数。

- [ ] **Step 3: 实现最小后端输入链路**

请求模型：

```python
class CreateAccountReportWorkflowRequest(BaseModel):
    referenceComments: bool = False
```

路由把 `payload.referenceComments` 传给服务。服务签名与持久化字段：

```python
def create_account_report_job(
    self,
    user_id: str,
    account_id: str,
    reference_comments: bool = False,
) -> tuple[WorkflowSchema, bool]:
    ...
    input_payload={
        "accountId": account.id,
        "platforms": platforms,
        "referenceComments": bool(reference_comments),
    },
```

存储上下文使用身份判断，避免字符串等历史异常值被当成开启：

```python
"referenceComments": (workflow.input_payload or {}).get("referenceComments") is True,
```

- [ ] **Step 4: 运行目标测试确认通过**

Run: 同 Step 2。

Expected: PASS。

### Task 2: 工作流评论采集控制与 AI 双重隔离

**Files:**
- Modify: `app/services/account_report/crawl_options.py`
- Modify: `app/services/account_report/workflow.py`
- Test: `tests/test_account_report_crawl_options.py`
- Test: `tests/test_account_report_workflow.py`

**Interfaces:**
- Consumes: `context["referenceComments"] -> bool`。
- Produces: `account_report_runtime_options(runtime_settings, platform, *, reference_comments=False)`。
- Produces: 关闭评论时传给证据构建器的 `CrawlResult.comments == []` 且 `comment_count == 0`。

- [ ] **Step 1: 写运行参数失败测试**

覆盖默认关闭、显式开启、子评论受全局配置约束：

```python
assert account_report_runtime_options(settings, "xhs")["enable_comments"] is False
assert account_report_runtime_options(settings, "xhs")["enable_sub_comments"] is False
enabled = account_report_runtime_options(settings, "xhs", reference_comments=True)
assert enabled["enable_comments"] is True
assert enabled["enable_sub_comments"] is settings.MEDIASPIDER_ENABLE_SUB_COMMENTS
```

- [ ] **Step 2: 写工作流 AI 隔离失败测试**

用返回评论的爬虫测试桩执行关闭评论的 workflow，记录主页和关键词调用参数，并截获最终报告 prompt。断言：

```python
assert all(call["enable_comments"] is False for call in crawler.calls)
assert all(call["enable_sub_comments"] is False for call in crawler.calls)
assert "不应进入提示词的评论" not in ai_service.prompts[-1]
```

另保留显式开启测试，断言评论文本的脱敏聚合证据仍可进入输入 JSON，但报告不得逐字输出。

- [ ] **Step 3: 运行目标测试确认失败**

Run:

```bash
conda run --no-capture-output -n starx pytest -q tests/test_account_report_crawl_options.py tests/test_account_report_workflow.py -k "comment"
```

Expected: FAIL，账号报告仍继承全局评论配置或 prompt 仍含测试评论。

- [ ] **Step 4: 实现运行参数覆盖与结果清理**

`crawl_options.py`：

```python
def account_report_runtime_options(
    runtime_settings: Any,
    platform: str,
    *,
    reference_comments: bool = False,
) -> dict[str, object]:
    options = dict(runtime_settings.mediaspider_runtime_options(platform))
    ...
    options["enable_comments"] = reference_comments
    options["enable_sub_comments"] = (
        reference_comments and bool(options.get("enable_sub_comments"))
    )
    return options
```

`workflow.py` 读取上下文并传入运行参数。新增小型纯函数清理关闭模式的结果，使用 Pydantic 不可变复制，不修改爬虫返回对象：

```python
def _without_comments(result: CrawlResult) -> CrawlResult:
    return result.model_copy(update={"comments": [], "comment_count": 0})
```

在 `build_report_evidence` 前，仅当 `reference_comments` 为假时映射当前账号和行业结果。

- [ ] **Step 5: 运行目标测试确认通过**

Run: 同 Step 3。

Expected: PASS。

### Task 3: 前端 API、刷新协调器与页面开关

**Files:**
- Modify: `starx-frontend/src/api/starx.js`
- Modify: `starx-frontend/src/api/starx.test.js`
- Modify: `starx-frontend/src/hooks/accountReportPolling.js`
- Modify: `starx-frontend/src/hooks/accountReportPolling.test.js`
- Modify: `starx-frontend/src/hooks/useStarxApp.js`
- Modify: `starx-frontend/src/pages/AccountReport.jsx`
- Modify: `starx-frontend/src/pages/AccountReport.preview.test.js`
- Modify: `starx-frontend/src/styles/pages.css`

**Interfaces:**
- Produces: `starxApi.createReportWorkflow(accountId, referenceComments=false)`。
- Produces: `refreshAccountReport(referenceComments=false)`。
- Consumes: `app.currentAccount.id` 用于账号切换重置。

- [ ] **Step 1: 写 API 与协调器失败测试**

API 断言请求体：

```javascript
await starxApi.createReportWorkflow("acc1", true);
assert.deepEqual(calls[0].body, { referenceComments: true });
```

刷新协调器断言选择透传：

```javascript
await coordinator.refresh("acc1", true);
assert.deepEqual(createdWith, [{ accountId: "acc1", referenceComments: true }]);
```

- [ ] **Step 2: 写页面结构失败测试**

在预览测试中断言开关使用受控布尔状态、可访问标签、两个生成入口都传入当前值，并监听账号 ID 重置：

```javascript
assert.match(source, /useState\(false\)/);
assert.match(source, /aria-checked=\{referenceComments\}/);
assert.match(source, /refreshAccountReport\(referenceComments\)/);
assert.match(source, /setReferenceComments\(false\)/);
```

- [ ] **Step 3: 运行前端目标测试确认失败**

Run:

```bash
npm test -- src/api/starx.test.js src/hooks/accountReportPolling.test.js src/pages/AccountReport.preview.test.js
```

Expected: FAIL，请求仍为空对象、协调器不接收选项、页面没有开关。

- [ ] **Step 4: 实现参数透传与页面状态**

API：

```javascript
createReportWorkflow: (accountId, referenceComments = false) =>
  apiClient.post(`/accounts/${accountId}/report/workflows`, { referenceComments }),
```

协调器：

```javascript
const refresh = async (accountId, referenceComments = false) => {
  ...
  const workflow = await createWorkflow(accountId, referenceComments);
```

`useStarxApp` 将参数继续传入 API。页面增加 `referenceComments` 状态，并用 `useEffect` 在 `currentAccount.id` 变化时重置。开关使用原生 `button role="switch"`，生成期间禁用；点击只切换页面状态。两个生成按钮都调用统一 `refresh` 函数。

- [ ] **Step 5: 增加局部响应式样式**

新增 `.report-comment-toggle`、`.report-comment-switch`、`.report-comment-switch[aria-checked="true"]` 和焦点样式；窄屏时与现有 hero 操作纵向排列，不改动其他页面公共开关。

- [ ] **Step 6: 运行前端目标测试确认通过**

Run: 同 Step 3。

Expected: PASS。

### Task 4: 回归验证与交付检查

**Files:**
- Verify: 上述所有修改文件

**Interfaces:**
- Consumes: Tasks 1–3 的完整链路。
- Produces: 可交付的默认关闭评论账号报告功能。

- [ ] **Step 1: 运行后端账号报告回归**

Run:

```bash
conda run --no-capture-output -n starx pytest -q \
  tests/test_account_report_api.py \
  tests/test_account_report_crawl_options.py \
  tests/test_account_report_evidence.py \
  tests/test_account_report_workflow.py
```

Expected: PASS。

- [ ] **Step 2: 运行前端回归**

Run:

```bash
npm test -- src/api/starx.test.js src/hooks/accountReportPolling.test.js src/pages/AccountReport.preview.test.js
```

Expected: PASS。

- [ ] **Step 3: 静态检查变更**

分别在后端和前端仓库运行：

```bash
git diff --check
git status --short
```

Expected: `git diff --check` 退出码 0；只出现本功能文件和已提交文档。

- [ ] **Step 4: 提交实现**

后端：

```bash
git add app/schemas/reports.py app/api/routes/reports.py app/services/workflow/service.py app/services/workflow/workflow_store.py app/services/account_report/crawl_options.py app/services/account_report/workflow.py tests/test_account_report_api.py tests/test_account_report_crawl_options.py tests/test_account_report_workflow.py docs/superpowers/plans/2026-07-17-account-report-reference-comments-toggle.md
git commit -m "feat: make account report comments opt in"
```

前端：

```bash
git add src/api/starx.js src/api/starx.test.js src/hooks/accountReportPolling.js src/hooks/accountReportPolling.test.js src/hooks/useStarxApp.js src/pages/AccountReport.jsx src/pages/AccountReport.preview.test.js src/styles/pages.css
git commit -m "feat: add account report comment toggle"
```
