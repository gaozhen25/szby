# MediaSpider 账号报告 Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MediaSpider 的小红书、抖音、快手双路采集能力迁入 StarX，并通过统一 workflow 自动生成可供前端展示和选题推荐复用的结构化账号报告。

**Architecture:** `app.services.mediaspider` 是无数据库依赖的采集边界，`app.services.account_report` 负责证据归一化、AI 分析和报告持久化。账号创建和手动刷新只创建 `account_report` workflow，现有调度器异步执行，前端轮询状态并在成功后刷新报告。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Pydantic 2、Alembic、Playwright、React 18、Vite、pytest、Node Test Runner

## Global Constraints

- 所有设计与实施文档使用中文。
- 后端 Python 命令只能通过名为 `starx` 的 conda 环境运行。
- 只迁移小红书、抖音、快手；视频号使用无采集降级报告。
- Cookie 只来自后端环境变量，不得进入 API、workflow payload、日志或测试快照。
- MediaSpider 运行保持进程级串行，其他 workflow 不受该锁限制。
- 完整原始帖子和评论不长期入库，只保存结构化报告和精选证据。
- 报告更新必须原子化；失败不得覆盖上一版报告。
- 每个生产行为先写失败测试并确认 RED，再写最小实现并确认 GREEN。
- 不修改或清理工作区中与本功能无关的现有变更。

---

## 文件结构

### 后端新增

- `app/services/mediaspider/`：StarX 内嵌采集包、三平台实现、运行时和许可证。
- `app/services/account_report/models.py`：报告与证据 Pydantic 契约。
- `app/services/account_report/evidence.py`：跨平台数据规范化、评分、去重和截断。
- `app/services/account_report/prompts.py`：关键词规划和完整报告提示词。
- `app/services/account_report/workflow.py`：`account_report` workflow。
- `alembic/versions/20260714_000018_account_report_structured_fields.py`：报告结构化字段迁移。
- `tests/test_mediaspider_service.py`：采集服务边界测试。
- `tests/test_mediaspider_runtime.py`：配置恢复、内存采集和资源清理测试。
- `tests/test_account_report_evidence.py`：证据规范化测试。
- `tests/test_account_report_workflow.py`：完整 workflow 测试。
- `tests/test_account_report_api.py`：自动触发、刷新和查询 API 测试。

### 后端修改

- `requirements.txt`、`pyproject.toml`：加入运行三平台爬虫所需依赖。
- `app/core/config.py`：加入 `STARX_MEDIASPIDER_*` 配置。
- `app/db/models.py`：扩展 `ReportRecord`。
- `app/models/account.py`、`app/schemas/reports.py`：扩展报告领域和 API 契约。
- `app/services/db_service.py`：映射和原子保存结构化报告。
- `app/services/workflow/__init__.py`：注册报告 workflow。
- `app/services/workflow/service.py`：创建和查询报告 workflow。
- `app/services/workflow/workflow_store.py`：报告上下文、持久化与选题上下文。
- `app/services/workflow/workflows/topic_recommendation.py`：将报告证据加入选题提示词。
- `app/api/routes/accounts.py`：创建账号后自动提交报告 workflow。
- `app/api/routes/reports.py`：完整报告 workflow 接口。

### 前端修改

- `src/api/starx.js`、`src/api/starx.test.js`：报告 workflow API。
- `src/hooks/useStarxApp.js`：报告状态、轮询、刷新与账号切换清理。
- `src/pages/AccountReport.jsx`：真实结构化报告页面。
- `src/pages/AccountReport.preview.test.js`：报告页面静态契约测试。
- `src/styles/pages.css`：报告进度、降级提示和结构化卡片样式。

---

### Task 1: MediaSpider 配置、依赖与安全边界

**Files:**
- Modify: `starx-backend/app/core/config.py`
- Modify: `starx-backend/requirements.txt`
- Modify: `starx-backend/pyproject.toml`
- Create: `starx-backend/app/services/mediaspider/__init__.py`
- Create: `starx-backend/app/services/mediaspider/LICENSE`
- Create: `starx-backend/app/services/mediaspider/NOTICE.md`
- Test: `starx-backend/tests/test_mediaspider_config.py`

**Interfaces:**
- Produces: `settings.mediaspider_runtime_options(platform: str) -> dict[str, object]`，返回不参与序列化的运行参数。
- Consumes: `STARX_MEDIASPIDER_XHS_COOKIES`、`STARX_MEDIASPIDER_DOUYIN_COOKIES`、`STARX_MEDIASPIDER_KUAISHOU_COOKIES` 等环境变量。

- [ ] **Step 1: 写配置默认值、平台 Cookie 和脱敏失败测试**

```python
def test_mediaspider_runtime_options_are_platform_scoped_and_safe(monkeypatch):
    monkeypatch.setenv("STARX_MEDIASPIDER_XHS_COOKIES", "xhs-secret")
    configured = Settings(_env_file=None)

    options = configured.mediaspider_runtime_options("xhs")

    assert options["cookies"] == "xhs-secret"
    assert options["headless"] is True
    assert options["max_notes_count"] == 30
    assert "xhs-secret" not in configured.model_dump_json()


def test_mediaspider_runtime_options_reject_unknown_platform():
    with pytest.raises(ValueError, match="unsupported MediaSpider platform"):
        Settings(_env_file=None).mediaspider_runtime_options("bili")
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `conda run -n starx pytest tests/test_mediaspider_config.py -q`

Expected: FAIL，提示 `mediaspider_runtime_options` 不存在。

- [ ] **Step 3: 实现 Settings 字段和安全运行参数方法**

```python
_MEDIASPIDER_COOKIE_FIELDS = {
    "xhs": "MEDIASPIDER_XHS_COOKIES",
    "dy": "MEDIASPIDER_DOUYIN_COOKIES",
    "ks": "MEDIASPIDER_KUAISHOU_COOKIES",
}

def mediaspider_runtime_options(self, platform: str) -> dict[str, object]:
    field = _MEDIASPIDER_COOKIE_FIELDS.get(platform)
    if field is None:
        raise ValueError(f"unsupported MediaSpider platform: {platform}")
    return {
        "cookies": getattr(self, field),
        "headless": self.MEDIASPIDER_HEADLESS,
        "max_notes_count": self.MEDIASPIDER_MAX_NOTES_COUNT,
        "max_comments_count": self.MEDIASPIDER_MAX_COMMENTS_COUNT,
        "max_concurrency": self.MEDIASPIDER_MAX_CONCURRENCY,
        "enable_comments": self.MEDIASPIDER_ENABLE_COMMENTS,
        "enable_sub_comments": self.MEDIASPIDER_ENABLE_SUB_COMMENTS,
        "enable_cdp_mode": self.MEDIASPIDER_ENABLE_CDP_MODE,
        "cdp_connect_existing": self.MEDIASPIDER_CDP_CONNECT_EXISTING,
        "cdp_debug_port": self.MEDIASPIDER_CDP_DEBUG_PORT,
        "custom_browser_path": self.MEDIASPIDER_CUSTOM_BROWSER_PATH,
        "enable_ip_proxy": self.MEDIASPIDER_ENABLE_IP_PROXY,
        "ip_proxy_provider": self.MEDIASPIDER_IP_PROXY_PROVIDER,
        "static_proxy_url": self.MEDIASPIDER_STATIC_PROXY_URL,
    }
```

Cookie 字段使用 `SecretStr`，`repr=False`；方法通过 `get_secret_value()` 构造仅存在于内存中的 runner 参数。依赖清单从外部项目中只保留实际 import graph 需要的 `aiofiles`、`aiomysql`、`parsel`、`pyexecjs`、`playwright`、`tenacity`、`xhshow` 等包，并保留 StarX 当前版本下限。

- [ ] **Step 4: 加入许可证与来源说明**

将 `external_project/mediaspider/LICENSE` 原文不作修改地放入目标 LICENSE。另建 `NOTICE.md` 记录原始仓库地址、迁移日期和 StarX 已另行取得商业授权；不得删除或改写原版权声明。

- [ ] **Step 5: 运行测试并提交**

Run: `conda run -n starx pytest tests/test_mediaspider_config.py -q`

Expected: PASS。

Commit: `feat: configure embedded mediaspider runtime`

---

### Task 2: 迁移三平台 MediaSpider 运行时与公开服务

**Files:**
- Create: `starx-backend/app/services/mediaspider/models.py`
- Create: `starx-backend/app/services/mediaspider/service.py`
- Create: `starx-backend/app/services/mediaspider/runtime/config_scope.py`
- Create: `starx-backend/app/services/mediaspider/runtime/collector.py`
- Create: `starx-backend/app/services/mediaspider/runtime/runner.py`
- Create: `starx-backend/app/services/mediaspider/platforms/xhs/**`
- Create: `starx-backend/app/services/mediaspider/platforms/douyin/**`
- Create: `starx-backend/app/services/mediaspider/platforms/kuaishou/**`
- Create: `starx-backend/app/services/mediaspider/stores/xhs.py`
- Create: `starx-backend/app/services/mediaspider/stores/douyin.py`
- Create: `starx-backend/app/services/mediaspider/stores/kuaishou.py`
- Create: `starx-backend/app/services/mediaspider/vendor/**`
- Test: `starx-backend/tests/test_mediaspider_service.py`
- Test: `starx-backend/tests/test_mediaspider_runtime.py`

**Interfaces:**
- Produces: `MediaCrawlerService.crawl_by_keyword(...) -> CrawlResult`、`MediaCrawlerService.crawl_by_creator(...) -> CrawlResult`。
- Produces: `CrawlerExecutionError.partial_result`。
- Consumes: Task 1 生成的运行参数字典。

- [ ] **Step 1: 移植公开服务参数映射失败测试**

```python
@pytest.mark.asyncio
async def test_keyword_and_creator_calls_return_structured_results():
    captured = []

    async def runner(config):
        captured.append(config)
        return CrawlResult(platform=config.platform, crawl_type=config.crawl_type)

    service = MediaCrawlerService(runner=runner)
    await service.crawl_by_keyword(
        keywords="护肤, 通勤妆", platform="小红书", cookies="cookie=value"
    )
    await service.crawl_by_creator(
        creator_url="https://www.douyin.com/user/demo", cookies="cookie=value"
    )

    assert captured[0].platform == "xhs"
    assert captured[0].keywords == ["护肤", "通勤妆"]
    assert captured[1].platform == "dy"
    assert captured[1].crawl_type == "creator"
```

- [ ] **Step 2: 运行服务测试并确认 RED**

Run: `conda run -n starx pytest tests/test_mediaspider_service.py -q`

Expected: FAIL，提示 `app.services.mediaspider.service` 不存在。

- [ ] **Step 3: 迁移模型、异常、平台解析和 service**

以外部项目已验证的 `crawler_runtime/models.py`、`exceptions.py`、`platform_resolver.py` 和 `services/crawler_service.py` 为行为基线，改为 StarX 包内导入，并把允许平台固定为：

```python
SUPPORTED_PLATFORMS = {"xhs", "dy", "ks"}
PLATFORM_ALIASES = {
    "xhs": "xhs", "xiaohongshu": "xhs", "小红书": "xhs",
    "dy": "dy", "douyin": "dy", "抖音": "dy",
    "ks": "ks", "kuaishou": "ks", "快手": "ks",
}
```

公开模型不得在 `repr`、异常文本或 `model_dump()` 中包含 Cookie。

- [ ] **Step 4: 写 Collector、配置恢复和串行失败测试**

```python
@pytest.mark.asyncio
async def test_runner_restores_config_and_collector_after_failure(monkeypatch):
    original = crawler_config.PLATFORM
    with pytest.raises(CrawlerExecutionError) as exc_info:
        await run_crawler(make_config(), factory=FakeFactory(FailingCrawler()))
    assert crawler_config.PLATFORM == original
    assert exc_info.value.partial_result.platform == "xhs"
    with pytest.raises(RuntimeError, match="未绑定"):
        await MemoryStore().store_content({"note_id": "outside"})
```

- [ ] **Step 5: 运行 runtime 测试并确认 RED**

Run: `conda run -n starx pytest tests/test_mediaspider_runtime.py -q`

Expected: FAIL，提示运行时模块不存在。

- [ ] **Step 6: 迁移运行时、三平台实现和最小公共依赖**

从外部项目定向迁移：

- `crawler_runtime` 的 config scope、memory store、runner 和 ContextVar 状态。
- `media_platform/xhs`、`media_platform/douyin`、`media_platform/kuaishou`。
- 三个平台对应的 Store 入口。
- 上述模块实际引用的 `base`、`cache`、`config`、`libs`、`model`、`proxy`、`tools`、CDP 管理器和登录组件。

迁移时将工厂固定为：

```python
CRAWLERS = {
    "xhs": XiaoHongShuCrawler,
    "dy": DouYinCrawler,
    "ks": KuaishouCrawler,
}
```

所有顶层导入改为 `app.services.mediaspider...`；删除 CSV、Excel、数据库、词云、WebUI、CLI、B 站、微博、贴吧和知乎分支。Store Factory 在服务包内只暴露 `MemoryStore`，不得写文件或数据库。

- [ ] **Step 7: 运行迁移测试与 import smoke test**

Run: `conda run -n starx pytest tests/test_mediaspider_service.py tests/test_mediaspider_runtime.py -q`

Run: `conda run -n starx python -c "from app.services.mediaspider import MediaCrawlerService; print(MediaCrawlerService.__name__)"`

Expected: 测试 PASS，smoke test 输出 `MediaCrawlerService`。

- [ ] **Step 8: 提交**

Commit: `feat: embed three-platform mediaspider service`

---

### Task 3: 结构化报告持久化契约

**Files:**
- Create: `starx-backend/alembic/versions/20260714_000018_account_report_structured_fields.py`
- Modify: `starx-backend/app/db/models.py`
- Modify: `starx-backend/app/models/account.py`
- Modify: `starx-backend/app/schemas/reports.py`
- Modify: `starx-backend/app/services/db_service.py`
- Test: `starx-backend/tests/test_db_service.py`
- Test: `starx-backend/tests/test_api_flows.py`

**Interfaces:**
- Produces: `DBService.replace_structured_report(user_id, account_id, payload) -> Report`。
- Produces: 扩展后的 `ReportSchema`，旧五字段继续存在。

- [ ] **Step 1: 写默认结构和原子替换失败测试**

```python
def test_structured_report_defaults_and_atomic_replace():
    with db_session() as session:
        service = DBService(session)
        report = service.get_report("u_001", "acc1")
        assert report.similarAccounts == []
        assert report.reportVersion == 0

        updated = service.replace_structured_report(
            "u_001", "acc1", structured_report_payload()
        )
        assert updated.reportVersion == 1
        assert updated.hotContents[0]["title"] == "通勤底妆实测"
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `conda run -n starx pytest tests/test_db_service.py -q`

Expected: FAIL，提示结构化字段或方法不存在。

- [ ] **Step 3: 增加 ORM、迁移、领域对象和 API Schema**

迁移为 `reports` 增加七个非空 JSON 字段、`report_version` 和可空 `generated_at`。所有 JSON 列先用 `'[]'` 或 `'{}'` server default 回填，再移除 server default。领域与 Schema 使用 camelCase：

```python
similarAccounts: list[dict[str, Any]] = field(default_factory=list)
complianceRules: list[dict[str, Any]] = field(default_factory=list)
targetUserProfile: dict[str, Any] = field(default_factory=dict)
hotContents: list[dict[str, Any]] = field(default_factory=list)
topBloggerDetails: list[dict[str, Any]] = field(default_factory=list)
contentStrategy: dict[str, Any] = field(default_factory=dict)
sourceMeta: dict[str, Any] = field(default_factory=dict)
reportVersion: int = 0
generatedAt: datetime | None = None
```

- [ ] **Step 4: 实现事务内完整替换**

`replace_structured_report` 必须先验证账号归属，再在同一事务中更新旧摘要、全部 JSON 字段、递增版本并设置 UTC 时间。异常时 rollback，调用方不得逐字段写入。

`WorkflowStore.replace_account_report()` 只负责打开短生命周期 session，并委托 `DBService(session).replace_structured_report()` 完成同一套映射和事务语义，禁止再实现第二套字段更新逻辑。

- [ ] **Step 5: 执行迁移和测试**

Run: `conda run -n starx alembic upgrade head`

Run: `conda run -n starx pytest tests/test_db_service.py tests/test_api_flows.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

Commit: `feat: persist structured account reports`

---

### Task 4: 跨平台证据归一化与报告提示词

**Files:**
- Create: `starx-backend/app/services/account_report/__init__.py`
- Create: `starx-backend/app/services/account_report/models.py`
- Create: `starx-backend/app/services/account_report/evidence.py`
- Create: `starx-backend/app/services/account_report/prompts.py`
- Test: `starx-backend/tests/test_account_report_evidence.py`

**Interfaces:**
- Produces: `normalize_metric(value) -> int`。
- Produces: `build_report_evidence(crawl_results, own_creator_hashes) -> ReportEvidence`。
- Produces: `parse_account_report(raw) -> AccountReportPayload`。

- [ ] **Step 1: 写数值、去重、排除自身和截断失败测试**

```python
def test_build_report_evidence_normalizes_ranks_and_excludes_owner():
    evidence = build_report_evidence(
        [douyin_result(liked_count="3.2万", creator_hash="competitor")],
        own_creator_hashes={"owner"},
    )
    assert evidence.hot_contents[0].liked_count == 32000
    assert evidence.hot_contents[0].creator_hash == "competitor"
    assert all(item.creator_hash != "owner" for item in evidence.similar_accounts)
    assert len(evidence.hot_contents) <= 20
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `conda run -n starx pytest tests/test_account_report_evidence.py -q`

Expected: FAIL，提示 account_report 模块不存在。

- [ ] **Step 3: 实现证据契约与纯函数**

```python
METRIC_MULTIPLIERS = {"万": 10_000, "亿": 100_000_000}

def engagement_score(item: ContentEvidence) -> int:
    return (
        item.liked_count
        + item.collected_count * 2
        + item.comment_count * 3
        + item.share_count * 4
    )
```

平台字段适配器分别映射 XHS 的 `note_id/note_url`、抖音的 `aweme_id/aweme_url`、快手的 `video_id/video_url`。创作者标识进入报告前使用项目内稳定哈希函数处理。

- [ ] **Step 4: 实现关键词和报告 JSON 契约**

关键词响应限制为每个平台共用的 3–5 个短词。`AccountReportPayload` 对数组数量和必需字段进行 Pydantic 校验，并生成旧五字段的中文兼容摘要。解析函数剥离 markdown fence，但不接受无法解析或缺少主要报告块的结果。

- [ ] **Step 5: 运行测试并提交**

Run: `conda run -n starx pytest tests/test_account_report_evidence.py -q`

Expected: PASS。

Commit: `feat: normalize account report evidence`

---

### Task 5: 实现 account_report workflow

**Files:**
- Create: `starx-backend/app/services/account_report/workflow.py`
- Modify: `starx-backend/app/services/workflow/__init__.py`
- Modify: `starx-backend/app/services/workflow/workflow_store.py`
- Test: `starx-backend/tests/test_account_report_workflow.py`

**Interfaces:**
- Produces: 注册类型 `account_report`。
- Consumes: `MediaCrawlerService`、`settings.mediaspider_runtime_options()`、Task 4 证据函数。
- Produces: `WorkflowStore.account_report_context()`、`WorkflowStore.replace_account_report()`。

- [ ] **Step 1: 写双路采集和完整报告成功失败测试**

```python
def test_account_report_workflow_runs_creator_and_keyword_crawls():
    crawler = StubCrawlerService()
    workflow = run_account_report_workflow(crawler=crawler, ai=valid_report_ai())

    assert [(call.mode, call.platform) for call in crawler.calls] == [
        ("creator", "xhs"), ("keyword", "xhs"),
        ("creator", "dy"), ("keyword", "dy"),
    ]
    assert workflow.status == "completed"
    assert workflow.result_payload["reportVersion"] == 1


def test_account_report_workflow_keeps_old_report_when_all_supported_crawls_fail():
    old = existing_structured_report()
    workflow = run_account_report_workflow(crawler=FailingCrawler(), existing=old)
    assert workflow.status == "failed"
    assert load_report().model_dump() == old.model_dump()
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `conda run -n starx pytest tests/test_account_report_workflow.py -q`

Expected: FAIL，提示 workflow 未注册。

- [ ] **Step 3: 实现上下文加载和平台计划**

```python
PLATFORM_CODES = {"小红书": "xhs", "抖音": "dy", "快手": "ks"}

plans = [
    CrawlPlan(platform_name=name, platform_code=PLATFORM_CODES[name], creator_url=links.get(name, ""))
    for name in account_platforms
    if name in PLATFORM_CODES
]
unsupported = [name for name in account_platforms if name not in PLATFORM_CODES]
```

上下文只返回账号、知识库和主页链接；Cookie 在 workflow 运行中从 Settings 读取，不写入 record 或 step。

- [ ] **Step 4: 实现阶段、平台级降级和一次性持久化**

按设计进度依次更新 `context_loading`、`keyword_planning`、`creator_crawling`、`keyword_crawling`、`evidence_normalization`、`report_analysis` 和 `report_persistence`。每个平台异常写入安全摘要，不包含 Cookie、完整 URL 查询参数或 traceback 中的敏感请求头。

仅视频号时允许档案降级；存在支持平台但没有任何成功采集结果时抛错。AI 报告校验通过后只调用一次 `replace_account_report()`。

- [ ] **Step 5: 运行 workflow 测试并提交**

Run: `conda run -n starx pytest tests/test_account_report_workflow.py -q`

Expected: PASS。

Commit: `feat: add account report workflow`

---

### Task 6: workflow 服务、API 与创建账号自动触发

**Files:**
- Modify: `starx-backend/app/services/workflow/service.py`
- Modify: `starx-backend/app/api/routes/reports.py`
- Modify: `starx-backend/app/api/routes/accounts.py`
- Test: `starx-backend/tests/test_account_report_api.py`

**Interfaces:**
- Produces: `WorkflowService.create_account_report_job()`、`get_latest_account_report_job()`、`get_account_report_job()`、`mark_account_report_job_failed()`。
- Produces: 三个报告 workflow HTTP 接口。

- [ ] **Step 1: 写创建账号自动触发、任务去重和鉴权失败测试**

```python
def test_create_account_submits_one_account_report_workflow(client, scheduler):
    response = client.post("/api/v1/accounts", headers=auth(), json=account_payload())
    assert response.status_code == 200
    account_id = response.json()["id"]
    latest = client.get(
        f"/api/v1/accounts/{account_id}/report/workflows/latest", headers=auth()
    ).json()
    assert latest["type"] == "account_report"
    assert scheduler.submissions == [("account_report", latest["id"])]


def test_repeated_report_refresh_returns_running_workflow(client):
    first = post_report_workflow(client)
    second = post_report_workflow(client)
    assert second.json()["id"] == first.json()["id"]
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `conda run -n starx pytest tests/test_account_report_api.py -q`

Expected: FAIL，接口为 404 或未提交任务。

- [ ] **Step 3: 实现 WorkflowService CRUD 与去重**

创建记录使用：

```python
WorkflowRecord(
    type="account_report",
    status="pending",
    progress=0,
    current_stage="pending",
    target_platform=account.platform,
    requested_count=len(account.platforms or [account.platform]),
    input_payload={"accountId": account.id, "platforms": list(account.platforms)},
    result_payload={},
)
```

查询必须同时限制 `user_id`、`account_id` 和 `type`。

- [ ] **Step 4: 接入 reports 路由和账号创建入口**

账号创建成功后创建 workflow 并调用 `scheduler.submit("account_report", id)`。提交失败时将 workflow 标记失败，但不回滚已经成功创建的账号。手动刷新提交失败返回 500，latest 不存在返回 404。

- [ ] **Step 5: 运行 API 回归测试并提交**

Run: `conda run -n starx pytest tests/test_account_report_api.py tests/test_ai_report_analysis.py tests/test_api_flows.py -q`

Expected: PASS。

Commit: `feat: expose account report workflow api`

---

### Task 7: 选题 workflow 引用账号报告

**Files:**
- Modify: `starx-backend/app/services/workflow/workflow_store.py`
- Modify: `starx-backend/app/services/workflow/workflows/topic_recommendation.py`
- Test: `starx-backend/tests/test_topic_recommendation_workflow.py`

**Interfaces:**
- Consumes: 最新持久化结构化报告。
- Produces: `topic_recommendation_context["accountReport"]`。

- [ ] **Step 1: 写有报告和无报告两条失败测试**

```python
def test_topic_prompt_uses_report_evidence_and_compliance_rules():
    prompt = build_topic_recommendation_user_prompt(context_with_report())
    assert "目标用户画像" in prompt
    assert "通勤底妆实测" in prompt
    assert "避免绝对化功效" in prompt
    assert "不得直接复制竞品标题" in prompt


def test_topic_prompt_still_works_without_report():
    prompt = build_topic_recommendation_user_prompt(context_without_report())
    assert "账号档案" in prompt
    assert "无已生成账号报告" in prompt
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `conda run -n starx pytest tests/test_topic_recommendation_workflow.py -q`

Expected: FAIL，提示词不含报告证据。

- [ ] **Step 3: 加载精简报告上下文并扩展提示词**

上下文最多传入 10 条爆款、10 个相似账号和全部合规规则，只包含选题需要的字段。提示词要求基于证据提炼、服务目标用户、遵守合规规则且不得复刻标题。

- [ ] **Step 4: 运行测试并提交**

Run: `conda run -n starx pytest tests/test_topic_recommendation_workflow.py -q`

Expected: PASS。

Commit: `feat: ground topic recommendations in account reports`

---

### Task 8: 前端报告 API 与安全轮询

**Files:**
- Modify: `starx-frontend/src/api/starx.js`
- Modify: `starx-frontend/src/api/starx.test.js`
- Modify: `starx-frontend/src/hooks/useStarxApp.js`
- Create: `starx-frontend/src/hooks/accountReportPolling.test.js`

**Interfaces:**
- Produces: `createReportWorkflow(accountId)`、`getLatestReportWorkflow(accountId)`、`getReportWorkflow(accountId, workflowId)`。
- Produces: `app.reportWorkflow`、`app.isGeneratingReport`、`app.refreshAccountReport()`。

- [ ] **Step 1: 写 API 路径失败测试**

```javascript
test("report workflow api methods call report workflow endpoints", async () => {
  await starxApi.createReportWorkflow("acc1");
  await starxApi.getLatestReportWorkflow("acc1");
  await starxApi.getReportWorkflow("acc1", "wf_report");
  assert.equal(calls[0].options.method, "POST");
  assert.match(calls[1].url, /\/accounts\/acc1\/report\/workflows\/latest$/);
  assert.match(calls[2].url, /\/accounts\/acc1\/report\/workflows\/wf_report$/);
});
```

- [ ] **Step 2: 运行前端测试并确认 RED**

Run: `npm test -- src/api/starx.test.js`

Expected: FAIL，方法不存在。

- [ ] **Step 3: 实现 API 和独立轮询状态机**

轮询必须使用独立的 timer ref、run ref 和 `currentAccountIdRef` 校验，不能复用选题 timer。完成后读取新报告；失败时保留旧报告；账号切换、退出和卸载时停止轮询。

创建账号后的固定延时假成功逻辑删除，替换为 latest workflow 接管：

```javascript
const workflow = await starxApi.getLatestReportWorkflow(account.id);
startReportWorkflowPolling(account.id, workflow);
setActivePage("report");
```

- [ ] **Step 4: 运行测试并提交**

Run: `npm test`

Expected: PASS。

Commit: `feat: poll account report workflows`

---

### Task 9: 前端账号报告真实数据页面

**Files:**
- Modify: `starx-frontend/src/pages/AccountReport.jsx`
- Create: `starx-frontend/src/pages/AccountReport.preview.test.js`
- Modify: `starx-frontend/src/styles/pages.css`

**Interfaces:**
- Consumes: Task 8 的报告、workflow、刷新动作。
- Produces: 主报告、相似账号、合规详情、目标用户、爆款样本和来源提示视图。

- [ ] **Step 1: 写移除 mock 和结构化展示失败测试**

```javascript
test("account report renders structured data without report mocks", () => {
  assert.doesNotMatch(source, /mockSimilarAccounts|const complianceRules =/);
  assert.match(source, /app\.report\?\.similarAccounts/);
  assert.match(source, /app\.report\?\.complianceRules/);
  assert.match(source, /app\.report\?\.targetUserProfile/);
  assert.match(source, /app\.report\?\.hotContents/);
  assert.match(source, /app\.reportWorkflow/);
  assert.match(source, /app\.refreshAccountReport/);
});
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `npm test -- src/pages/AccountReport.preview.test.js`

Expected: FAIL，页面仍引用 mock。

- [ ] **Step 3: 重构页面为结构化数据渲染**

保留现有视觉层级和主视图/详情视图切换；所有数组使用空数组降级，所有指标通过统一格式化函数展示。首次生成显示骨架和中文阶段名；旧报告更新时继续显示内容并在顶部显示进度。失败平台、视频号不支持和无采集报告使用非阻断提示。

- [ ] **Step 4: 补充响应式样式并验证**

Run: `npm test`

Run: `npm run build`

Expected: 测试 PASS，Vite build 成功且无新增 warning。

- [ ] **Step 5: 提交**

Commit: `feat: render live account report data`

---

### Task 10: 集成验证、部署文档与最终审查

**Files:**
- Modify: `starx-backend/README.md`
- Modify: `starx-backend/.env.example`
- Modify: `starx-backend/docs/superpowers/specs/2026-07-14-account-report-mediaspider-workflow-design.md`（仅在实现发现契约偏差时同步）

**Interfaces:**
- Produces: 可复现的安装、配置、迁移、运行和验证说明。

- [ ] **Step 1: 编写环境与浏览器说明**

文档列出三平台 Cookie、headless、CDP、浏览器路径、代理和采集上限；示例值为空或占位符，绝不写真实 Cookie。说明依赖安装和浏览器运行必须在 `starx` conda 环境中完成。

- [ ] **Step 2: 运行敏感信息扫描**

Run: `rg -n "xhs-secret|cookie=value|MEDIASPIDER_.*COOKIES=.*[^=]$" app tests .env.example README.md`

Expected: 只命中明确的测试假值或空配置，不命中真实凭证和 workflow/API 快照。

- [ ] **Step 3: 运行后端完整验证**

Run: `conda run -n starx alembic upgrade head`

Run: `conda run -n starx pytest tests -q`

Expected: 全部 PASS。

- [ ] **Step 4: 运行前端完整验证**

Run: `npm test`

Run: `npm run build`

Expected: 全部 PASS。

- [ ] **Step 5: 检查两个仓库改动边界**

Run: `git -C starx-backend status --short`

Run: `git -C starx-frontend status --short`

Expected: 只包含本计划文件及实现文件；用户原有变更保持不动。

- [ ] **Step 6: 请求代码审查并处理结论**

使用 `superpowers:requesting-code-review` 对照设计、计划、测试和隐私约束审查。修复所有阻断项后重新运行 Task 10 的完整验证。

- [ ] **Step 7: 最终提交**

后端 Commit: `docs: document account report crawler workflow`

前端若仍有未提交的本功能改动，Commit: `test: verify account report workflow ui`
