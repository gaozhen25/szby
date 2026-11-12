# 账号报告采集语义与 AI 证据分流实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 修正账号报告首阶段的公开文案，并把当前账号主页证据与行业关键词证据严格分流后再交给 AI。

**架构：** 通用 MediaSpider 事件保持不变，由账号报告领域层按 `creator`/`keyword` 模式翻译公开语义。工作流分别收集当前账号与行业结果，证据层输出 `currentAccountEvidence` 和 `industryEvidence`，AI 上下文采用字段白名单并在输出后按行业证据执行内容与账号候选过滤。

**技术栈：** Python 3、FastAPI、Pydantic、pytest、React、Node.js `node:test`。

## 全局约束

- 所有设计与实施文档使用中文。
- 后端测试必须使用名为 `starx` 的 conda 环境。
- 不修改 MediaSpider 通用 `creator` 模式、账号报告最终七个顶层输出块、数据库结构或报告 API。
- 当前账号作品不得进入行业 `hotContents`、`similarAccounts` 或 `topBloggers` 候选。
- 账号报告 AI prompt 不得包含内部 `id`、`userId`、联系方式、Logo、图片素材 URL、官网 URL、账号主页 URL 或运行凭证。
- 评论继续遵守：每条内容最多 3 条、每个平台最多 10 条、两组证据合计最多 20 条，并执行既有脱敏与禁止逐字输出规则。
- 报告结果中的“头部博主参考”保持不变。

## 文件结构

- 新建 `app/services/account_report/ai_context.py`：账号报告 AI 字段白名单与上下文构造。
- 修改 `app/services/workflow/workflow_store.py`：只为账号报告返回安全知识库文本。
- 修改 `app/services/account_report/models.py`：定义当前账号证据、行业证据和组合证据契约。
- 修改 `app/services/account_report/evidence.py`：分别归一化两类采集结果，共享评论上限。
- 修改 `app/services/account_report/prompts.py`：构造双分组证据 prompt。
- 修改 `app/services/account_report/workflow.py`：采集结果分流、AI 安全上下文、行业候选白名单。
- 修改 `app/services/account_report/crawl_progress.py` 与 `crawl_notice_catalog.py`：账号报告领域公开文案。
- 修改前端 `src/utils/accountReport.js` 与 `src/pages/account-report/AccountReportWorkflowProgress.jsx`：阶段和计数展示。
- 修改对应后端与前端测试，覆盖隐私、分流、候选过滤和文案。

---

### Task 1：建立账号报告 AI 安全上下文

**文件：**
- 新建：`app/services/account_report/ai_context.py`
- 修改：`app/services/workflow/workflow_store.py:76-119,137-157`
- 测试：`tests/test_account_report_workflow.py`

**接口：**
- 输入：`build_account_report_ai_context(account: dict[str, Any], *, knowledge_enabled: bool, knowledge_context: str) -> dict[str, Any]`
- 输出：后续关键词规划和报告分析共用的安全 `accountContext`。

- [ ] **Step 1：写失败测试，锁定账号与知识库白名单**

在 `tests/test_account_report_workflow.py` 增加：

```python
from app.services.account_report.ai_context import build_account_report_ai_context


def test_account_report_ai_context_excludes_internal_and_contact_fields():
    context = build_account_report_ai_context(
        {
            "id": "acc-secret",
            "userId": "user-secret",
            "name": "测试账号",
            "description": "通勤底妆",
            "industry": "美妆",
            "productService": "粉底液",
            "platforms": ["小红书"],
            "accountLinks": {"小红书": "https://secret.example/profile"},
        },
        knowledge_enabled=True,
        knowledge_context="产品: 粉底液\n产品介绍: 适合通勤\n联系方式: 13800138000",
    )
    serialized = json.dumps(context, ensure_ascii=False)
    assert context["account"]["name"] == "测试账号"
    assert "acc-secret" not in serialized
    assert "user-secret" not in serialized
    assert "secret.example" not in serialized
    assert "13800138000" not in serialized
```

扩展 `test_store_account_report_context_contains_only_profile_knowledge_and_links`：知识库 fixture 同时提供 Logo、素材、官网和联系方式，断言 `knowledgeContext` 只包含产品名、产品介绍、品牌故事和价格。

- [ ] **Step 2：运行测试并确认 RED**

运行：

```bash
conda run -n starx pytest tests/test_account_report_workflow.py::test_account_report_ai_context_excludes_internal_and_contact_fields tests/test_account_report_workflow.py::test_store_account_report_context_contains_only_profile_knowledge_and_links -q
```

预期：FAIL，`ai_context` 模块尚不存在，且 store 仍会包含联系方式和素材 URL。

- [ ] **Step 3：实现最小白名单构造器和账号报告专用知识库过滤**

`app/services/account_report/ai_context.py`：

```python
"""账号报告 AI 输入的最小业务上下文。"""

from typing import Any

_ACCOUNT_FIELDS = (
    "name", "description", "purpose", "type", "industry", "productService",
    "targetCity", "targetAudience", "conversionGoal", "platforms",
)


def build_account_report_ai_context(
    account: dict[str, Any], *, knowledge_enabled: bool, knowledge_context: str
) -> dict[str, Any]:
    safe_account = {key: account[key] for key in _ACCOUNT_FIELDS if account.get(key) not in (None, "")}
    safe_knowledge = "\n".join(
        line for line in str(knowledge_context or "").splitlines()
        if line.startswith(("产品: ", "产品介绍: ", "品牌故事: ", "价格: "))
    )
    return {
        "account": safe_account,
        "knowledgeEnabled": bool(knowledge_enabled and safe_knowledge),
        "knowledgeContext": safe_knowledge,
    }
```

在 `workflow_store.py` 新增 `_account_report_knowledge_context()`，字段表只包含产品名、产品介绍、品牌故事和价格；`account_report_context()` 改用该函数，其他 workflow 继续使用现有 `_enabled_knowledge_context()`。

- [ ] **Step 4：运行测试并确认 GREEN**

运行同 Step 2，预期：2 passed。

- [ ] **Step 5：提交后端变更**

```bash
git add app/services/account_report/ai_context.py app/services/workflow/workflow_store.py tests/test_account_report_workflow.py
git commit -m "fix: minimize account report ai context"
```

---

### Task 2：建立当前账号与行业证据双分组

**文件：**
- 修改：`app/services/account_report/models.py:21-62`
- 修改：`app/services/account_report/evidence.py:195-312`
- 测试：`tests/test_account_report_evidence.py`

**接口：**
- 输入：`build_report_evidence(current_account_results, industry_results, own_creator_hashes, *, unknown_owner_platforms=None) -> AccountReportEvidence`
- 输出：`current_account`（alias `currentAccountEvidence`）与 `industry`（alias `industryEvidence`）。

- [ ] **Step 1：写失败测试，证明两组结果不会混合**

```python
def test_report_evidence_separates_current_account_from_industry_candidates():
    current = _result(
        "xhs",
        contents=[{"note_id": "own-1", "creator_hash": "owner", "title": "自己的高赞作品", "liked_count": 999999}],
        creators=[{"creator_hash": "owner", "nickname": "自己的账号", "fans_count": 1000}],
    )
    industry = _result(
        "xhs",
        contents=[{"note_id": "industry-1", "creator_hash": "peer", "title": "行业样本", "liked_count": 100}],
        creators=[{"creator_hash": "peer", "nickname": "行业账号", "fans_count": 2000}],
    )

    evidence = build_report_evidence([current], [industry], {"owner"})

    assert [item.content_id for item in evidence.current_account.contents] == ["own-1"]
    assert [item.content_id for item in evidence.industry.hot_contents] == ["industry-1"]
    assert all(item.creator_hash != evidence.owner_hashes[0] for item in evidence.industry.similar_accounts)
```

再增加评论测试：当前账号和行业各准备 15 条有效评论，断言两组 `comments` 合计不超过 20，并继续满足每内容 3 条、每平台 10 条。

- [ ] **Step 2：运行测试并确认 RED**

```bash
conda run -n starx pytest tests/test_account_report_evidence.py::test_report_evidence_separates_current_account_from_industry_candidates -q
```

预期：FAIL，现有函数只接受一个采集结果列表，且没有双分组模型。

- [ ] **Step 3：定义证据模型并拆分归一化过程**

在 `models.py` 定义：

```python
class CurrentAccountEvidence(EvidenceModel):
    profiles: list[CreatorEvidence] = Field(default_factory=list, max_length=4)
    contents: list[ContentEvidence] = Field(default_factory=list, max_length=20)
    comments: list[CommentEvidence] = Field(default_factory=list, max_length=20)


class IndustryEvidence(EvidenceModel):
    hot_contents: list[ContentEvidence] = Field(default_factory=list, alias="hotContents", max_length=20)
    similar_accounts: list[CreatorEvidence] = Field(default_factory=list, alias="similarAccounts", max_length=20)
    top_bloggers: list[CreatorEvidence] = Field(default_factory=list, alias="topBloggers", max_length=10)
    comments: list[CommentEvidence] = Field(default_factory=list, max_length=20)


class AccountReportEvidence(EvidenceModel):
    current_account: CurrentAccountEvidence = Field(alias="currentAccountEvidence")
    industry: IndustryEvidence = Field(alias="industryEvidence")
    owner_hashes: list[str] = Field(default_factory=list, alias="ownerHashes")
```

在 `evidence.py` 抽取内容/账号去重与评论选择的私有函数。先处理当前账号评论并返回已使用的总量、平台量和内容量，再用同一预算处理行业评论。当前账号内容只写入 `CurrentAccountEvidence.contents`；行业内容才参与 `hotContents`、`similarAccounts`、`topBloggers` 排名。

- [ ] **Step 4：运行证据测试并确认 GREEN**

```bash
conda run -n starx pytest tests/test_account_report_evidence.py -q
```

预期：该文件全部通过；按新签名机械更新既有测试调用，不放宽既有断言。

- [ ] **Step 5：提交后端变更**

```bash
git add app/services/account_report/models.py app/services/account_report/evidence.py tests/test_account_report_evidence.py
git commit -m "feat: separate account and industry report evidence"
```

---

### Task 3：让 workflow 和 prompt 使用双分组证据

**文件：**
- 修改：`app/services/account_report/prompts.py:83-103`
- 修改：`app/services/account_report/workflow.py:149-475`
- 修改：`app/services/account_report/__init__.py`
- 测试：`tests/test_account_report_evidence.py`
- 测试：`tests/test_account_report_workflow.py`

**接口：**
- 消费：Task 1 的 `build_account_report_ai_context()`。
- 消费：Task 2 的 `AccountReportEvidence` 和四参数 `build_report_evidence()`。
- 输出：现有 `AccountReportPayload`，最终 API 与持久化契约不变。

- [ ] **Step 1：写失败测试，锁定 prompt、结果分流和内容白名单**

在 `test_account_report_evidence.py` 增加：

```python
def test_prompt_names_current_account_and_industry_evidence_separately():
    evidence = build_report_evidence(
        [_result("xhs", contents=[{"note_id": "own", "creator_hash": "owner"}])],
        [_result("xhs", contents=[{"note_id": "industry", "creator_hash": "peer"}])],
        {"owner"},
    )
    prompt = build_account_report_prompt(
        {"account": {"industry": "美妆"}}, evidence, {"platforms": ["小红书"]}
    )
    assert '"currentAccountEvidence"' in prompt
    assert '"industryEvidence"' in prompt
    assert "不得用当前账号作品填充行业热门内容" in prompt
```

在 `test_account_report_workflow.py` 增加工作流测试：Stub crawler 的 creator 返回 `own-1`，keyword 返回 `industry-1`；捕获第二次 AI prompt，断言两条内容分别位于正确分组且 prompt 不包含 fixture 中的内部 ID、联系方式和主页 URL。

增加 `_filter_report_candidates` 测试：AI 同时返回 `own-1`、`industry-1` 和 `invented-1`，过滤后 `hot_contents` 只能保留 `industry-1`。

- [ ] **Step 2：运行测试并确认 RED**

```bash
conda run -n starx pytest tests/test_account_report_evidence.py::test_prompt_names_current_account_and_industry_evidence_separately tests/test_account_report_workflow.py -q
```

预期：FAIL，workflow 尚未分流，prompt 尚未使用别名序列化，热门内容也没有白名单过滤。

- [ ] **Step 3：实现 workflow 分流、prompt 约束和候选过滤**

`workflow.py` 将 `crawl_results` 替换为：

```python
current_account_results: list[CrawlResult] = []
industry_results: list[CrawlResult] = []
```

`crawl_by_creator` 成功后只追加到 `current_account_results`；`crawl_by_keyword` 成功后只追加到 `industry_results`。关键词规划与报告分析都使用：

```python
ai_context = build_account_report_ai_context(
    account,
    knowledge_enabled=bool(context.get("knowledgeEnabled")),
    knowledge_context=str(context.get("knowledgeContext") or ""),
)
```

证据构造调用改为：

```python
evidence = build_report_evidence(
    current_account_results,
    industry_results,
    owner_hashes,
    unknown_owner_platforms=unknown_owner_platforms,
)
```

`prompts.py` 用 `evidence.model_dump(mode="json", by_alias=True)`，并明确当前账号证据和行业证据的用途。`_reject_verbatim_comments()` 遍历两组评论；`_filter_report_candidates()` 为行业 `hot_contents` 增加 `(platform, content_id)` 白名单，并继续过滤两类账号候选。

- [ ] **Step 4：运行工作流和证据测试并确认 GREEN**

```bash
conda run -n starx pytest tests/test_account_report_evidence.py tests/test_account_report_workflow.py -q
```

预期：两个文件全部通过。

- [ ] **Step 5：提交后端变更**

```bash
git add app/services/account_report/prompts.py app/services/account_report/workflow.py app/services/account_report/__init__.py tests/test_account_report_evidence.py tests/test_account_report_workflow.py
git commit -m "fix: route account report evidence by source"
```

---

### Task 4：修正账号报告进度领域文案

**文件：**
- 修改：`app/services/account_report/crawl_progress.py`
- 修改：`app/services/account_report/crawl_notice_catalog.py`
- 测试：`tests/test_account_report_crawl_progress.py`
- 测试：`tests/test_account_report_workflow.py`

**接口：**
- 输入：现有 tracker callback 的 `mode`（`creator` 或 `keyword`）。
- 输出：账号报告 API 中语义准确的 `crawlProgress`；通用 MediaSpider 事件不变。

- [ ] **Step 1：写失败测试，锁定两种模式的公开文案**

```python
def test_tracker_translates_creator_and_keyword_modes_to_account_report_language():
    tracker = AccountReportCrawlProgressTracker("wf-1", StubStore(), [CrawlTarget("小红书", "xhs")])
    asyncio.run(tracker.record(
        CrawlerProgressEvent(
            platform="xhs", crawlType="creator", action="creator_started",
            status="running", message="底层原始文案",
        ),
        platform_name="小红书",
        mode="creator",
    ))
    assert tracker.snapshot()["current"]["message"] == "开始采集当前账号主页公开信息"

    asyncio.run(tracker.record(
        CrawlerProgressEvent(
            platform="xhs", crawlType="search", action="creator_discovered",
            status="running", message="底层原始文案", subject="行业账号",
        ),
        platform_name="小红书",
        mode="keyword",
    ))
    assert tracker.snapshot()["current"]["message"] == "发现行业公开账号"
```

更新 notice 断言为“当前账号主页链接无效，已跳过主页公开信息采集”，建议为“请在账号档案中填写该平台真实、完整的当前账号主页链接”。

- [ ] **Step 2：运行测试并确认 RED**

```bash
conda run -n starx pytest tests/test_account_report_crawl_progress.py tests/test_account_report_workflow.py -q
```

预期：FAIL，当前 tracker 直接采用通用 `public_action_message()`，notice 仍使用“博主主页”。

- [ ] **Step 3：实现账号报告模式文案映射**

在 `crawl_progress.py` 增加只属于账号报告的映射函数：

```python
def _account_report_action_message(mode: str, action: str) -> str:
    overrides = {
        ("creator", "creator_started"): "开始采集当前账号主页公开信息",
        ("creator", "creator_discovered"): "读取账号公开资料",
        ("keyword", "keyword_started"): "开始采集行业关键词内容",
        ("keyword", "creator_discovered"): "发现行业公开账号",
    }
    return overrides.get((mode, action), public_action_message(action))
```

Tracker callback 保存并使用受限的 `mode`，不能根据后端原始 message 做字符串替换。`crawl_notice_catalog.py` 更新固定 notice 和 suggestion。

- [ ] **Step 4：运行后端进度测试并确认 GREEN**

运行同 Step 2，预期：全部通过。

- [ ] **Step 5：提交后端变更**

```bash
git add app/services/account_report/crawl_progress.py app/services/account_report/crawl_notice_catalog.py tests/test_account_report_crawl_progress.py tests/test_account_report_workflow.py
git commit -m "fix: clarify account report crawl progress"
```

---

### Task 5：更新前端阶段、计数和 notice 展示

**文件：**
- 修改：`starx-frontend/src/utils/accountReport.js:1-60`
- 修改：`starx-frontend/src/pages/account-report/AccountReportWorkflowProgress.jsx:45-58`
- 测试：`starx-frontend/src/utils/accountReport.test.js`
- 测试：`starx-frontend/src/pages/AccountReport.preview.test.js`

**接口：**
- 消费：Task 4 的新公开文案及旧 workflow 快照。
- 输出：当前账号和行业阶段含义清晰的账号报告进度 UI。

- [ ] **Step 1：写失败测试，锁定前端可见文案**

在 `accountReport.test.js` 更新并新增：

```javascript
test("account report stages distinguish current account and industry collection", () => {
  assert.equal(getReportStageLabel("creator_crawling"), "采集当前账号主页公开信息");
  assert.equal(getReportStageLabel("keyword_crawling"), "采集行业公开内容");
});

test("crawl counts call creators accounts in progress UI", () => {
  const display = createCrawlActivityDisplay({ creatorCount: 2 });
  assert.deepEqual(display.counts, [{ key: "creatorCount", label: "账号", value: 2 }]);
});
```

Preview 测试断言平台摘要使用 `<dt>账号</dt>`，同时断言报告结果仍包含“头部博主参考”。更新 notice fixture 为新文案。

- [ ] **Step 2：运行前端测试并确认 RED**

```bash
npm test -- src/utils/accountReport.test.js src/pages/AccountReport.preview.test.js
```

预期：FAIL，阶段与数量标签仍使用旧文案。

- [ ] **Step 3：实现最小前端文案修改**

在 `accountReport.js` 更新：

```javascript
creator_crawling: "采集当前账号主页公开信息",
keyword_crawling: "采集行业公开内容",
```

并将 `CRAWL_COUNT_LABELS` 中 `creatorCount` 的标签改为“账号”。`AccountReportWorkflowProgress.jsx` 平台摘要 `<dt>` 同步改为“账号”。不修改 `AccountReportSections.jsx` 的“头部博主参考”。

- [ ] **Step 4：运行前端测试并确认 GREEN**

运行同 Step 2，预期：全部通过。

- [ ] **Step 5：提交前端变更**

```bash
git add src/utils/accountReport.js src/utils/accountReport.test.js src/pages/account-report/AccountReportWorkflowProgress.jsx src/pages/AccountReport.preview.test.js
git commit -m "fix: clarify account report collection labels"
```

---

### Task 6：全量回归与验收审计

**文件：**
- 验证：`starx-backend`
- 验证：`starx-frontend`

**接口：**
- 消费：Tasks 1–5 的全部结果。
- 输出：满足设计文档九项验收标准的可交付修改。

- [ ] **Step 1：运行账号报告后端定向回归**

```bash
conda run -n starx pytest tests/test_account_report_evidence.py tests/test_account_report_crawl_progress.py tests/test_account_report_workflow.py tests/test_account_report_api.py -q
```

预期：全部通过，无 warning 或 error。

- [ ] **Step 2：运行后端完整测试**

```bash
conda run -n starx pytest -q
```

预期：全部通过；若存在与本次无关的既有失败，记录精确测试名并证明定向回归仍通过，不能隐藏失败。

- [ ] **Step 3：运行前端完整测试与构建**

```bash
npm test
npm run build
```

预期：测试全部通过，生产构建成功。

- [ ] **Step 4：执行敏感字段和误导文案静态审计**

```bash
rg -n '爬取博主|开始博主主页采集|配置的博主主页链接无效' src
rg -n 'id|userId|contactInfo|logoUrl|imageMaterials|websiteUrl|accountLinks' app/services/account_report tests/test_account_report_evidence.py tests/test_account_report_workflow.py
```

预期：前端账号报告进度代码无旧误导文案；后端命中仅存在于明确验证“不得进入 prompt”的测试或持久化所需代码，不存在于 AI 安全上下文输出字段。

- [ ] **Step 5：检查两个仓库的最终差异**

```bash
git status --short
git diff --check
git log -6 --oneline
```

分别在 `starx-backend` 和 `starx-frontend` 执行。预期：没有未提交的本次修改，`git diff --check` 无输出，提交历史按任务边界清晰。
