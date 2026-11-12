# 竞品监控实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现真实的监控账号与监控视频添加、删除、主动刷新和后台定时爬取刷新闭环。

**Architecture:** PostgreSQL 保存监控对象、刷新状态、到期时间和指标快照；FastAPI 路由通过竞品监控领域服务创建统一 `competitor_refresh` 工作流；MediaSpider 执行账号或指定内容爬取；生命周期扫描器原子认领到期对象。React 页面通过独立 hook 加载数据和轮询工作流，账号切换时拒绝陈旧响应。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL、MediaSpider、React 18、Vite、Node Test Runner

## Global Constraints

- 设计与实施文档使用中文。
- 后端 Python 命令只能使用名为 `starx` 的 conda 环境。
- 首期平台固定为小红书 `xhs`、抖音 `dy`、快手 `ks`。
- 默认自动刷新周期为 21600 秒，扫描周期为 60 秒，单批认领上限为 20。
- 监控账号和监控视频都必须支持添加与删除。
- 手动刷新与后台定时刷新必须复用同一种工作流和同一套结果持久化逻辑。
- 刷新失败必须保留最后一次成功数据，禁止用空数据覆盖。
- API、日志、工作流结果和快照不得保存 Cookie、请求头或完整底层异常。
- `app/core/config.py` 当前存在用户未提交改动，修改时只增加竞品配置字段，不覆盖或格式化无关区域。

---

## 文件结构

### 后端新增

- `alembic/versions/20260716_000021_competitor_monitoring.py`：三张竞品表、约束与索引。
- `app/schemas/competitors.py`：添加请求、对象响应、批量刷新响应。
- `app/api/routes/competitors.py`：账号隔离的 CRUD 和刷新 API。
- `app/services/competitor_monitoring/models.py`：领域类型和指标结构。
- `app/services/competitor_monitoring/normalizers.py`：三平台数据白名单映射与增量计算。
- `app/services/competitor_monitoring/repository.py`：事务、对象锁、到期认领、快照持久化。
- `app/services/competitor_monitoring/service.py`：添加、删除、刷新任务创建和成功/失败收尾。
- `app/services/competitor_monitoring/workflow.py`：`competitor_refresh` 工作流。
- `app/services/competitor_monitoring/periodic_scheduler.py`：生命周期扫描器。
- `tests/test_competitor_models.py`：数据模型和迁移行为。
- `tests/test_competitor_normalizers.py`：指标白名单与增量。
- `tests/test_competitor_service.py`：业务事务、去重和失败保留。
- `tests/test_competitor_api.py`：CRUD、隔离和刷新 API。
- `tests/test_competitor_periodic_scheduler.py`：到期认领与生命周期。
- `tests/test_mediaspider_detail.py`：指定内容公开服务。

### 后端修改

- `app/db/models.py`：竞品 ORM 模型和关系。
- `app/core/config.py`、`.env.example`：刷新和扫描配置。
- `app/services/mediaspider/models.py`、`service.py`、`runtime/config_scope.py`、`runtime/runner.py`：`detail` 模式。
- `app/services/workflow/scheduler.py`：导入注册竞品工作流。
- `app/api/router.py`：挂载竞品路由。
- `app/main.py`：启动和关闭周期扫描器。

### 前端新增

- `starx-frontend/src/hooks/useCompetitorMonitoring.js`：列表、操作和轮询生命周期。
- `starx-frontend/src/hooks/useCompetitorMonitoring.test.js`：陈旧响应和轮询测试。
- `starx-frontend/src/components/competitors/CompetitorAddModal.jsx`：添加链接表单。
- `starx-frontend/src/components/competitors/CompetitorMetric.jsx`：指标和增量。
- `starx-frontend/src/components/competitors/CompetitorAccountCard.jsx`：账号卡片。
- `starx-frontend/src/components/competitors/CompetitorVideoCard.jsx`：视频卡片。
- `starx-frontend/src/pages/CompetitorMonitor.preview.test.js`：页面行为和无演示数据测试。

### 前端修改

- `starx-frontend/src/api/starx.js`、`starx-frontend/src/api/starx.test.js`：竞品 API。
- `starx-frontend/src/pages/CompetitorMonitor.jsx`：替换演示页。
- `starx-frontend/src/styles.css`：竞品页面局部样式。

---

### Task 1: 暴露 MediaSpider 指定内容爬取模式

**Files:**
- Modify: `app/services/mediaspider/models.py`
- Modify: `app/services/mediaspider/service.py`
- Modify: `app/services/mediaspider/platform_resolver.py`
- Modify: `app/services/mediaspider/runtime/config_scope.py`
- Modify: `app/services/mediaspider/runtime/runner.py`
- Test: `tests/test_mediaspider_detail.py`

**Interfaces:**
- Consumes: 三个平台现有指定内容配置 `XHS_SPECIFIED_NOTE_URL_LIST`、`DY_SPECIFIED_ID_LIST`、`KS_SPECIFIED_ID_LIST`。
- Produces: `MediaCrawlerService.crawl_by_detail(*, content_url: str, on_progress: ProgressCallback | None = None, **runtime_options) -> CrawlResult`。

- [ ] **Step 1: 写失败的 detail 配置与服务测试**

```python
import pytest

from app.services.mediaspider.models import CrawlResult, InvalidCrawlRequestError
from app.services.mediaspider.service import MediaCrawlerService


@pytest.mark.asyncio
async def test_crawl_by_detail_builds_detail_config_for_douyin():
    calls = []

    async def runner(config, on_progress=None):
        calls.append(config)
        return CrawlResult(platform=config.platform, crawl_type=config.crawl_type)

    result = await MediaCrawlerService(runner=runner).crawl_by_detail(
        content_url="https://www.douyin.com/video/123",
        cookies="sessionid=test",
    )

    assert result.crawl_type == "detail"
    assert calls[0].platform == "dy"
    assert calls[0].content_url == "https://www.douyin.com/video/123"


@pytest.mark.asyncio
async def test_crawl_by_detail_rejects_creator_and_unknown_urls():
    service = MediaCrawlerService(runner=lambda *_args, **_kwargs: None)
    with pytest.raises(InvalidCrawlRequestError):
        await service.crawl_by_detail(content_url="https://example.com/video/1")
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `conda run --no-capture-output -n starx pytest tests/test_mediaspider_detail.py -q`

Expected: FAIL，提示 `crawl_by_detail` 或 `content_url` 尚不存在。

- [ ] **Step 3: 实现稳定的 detail 公共接口**

在 `CrawlerRunConfig` 中把类型改为 `Literal["search", "creator", "detail"]`，新增：

```python
content_url: str | None = None
```

交叉校验增加：

```python
if self.crawl_type == "detail" and not self.content_url:
    raise InvalidCrawlRequestError("指定内容模式必须提供 content_url")
```

服务方法使用新的 `resolve_content_platform(url: str) -> str` 校验已知域名和内容路径，并调用 `_build_config(crawl_type="detail", content_url=url, keywords=[], creator_url=None, ...)`。配置作用域按平台只设置一个指定内容 URL，runner 在 `detail` 分支调用各平台已有 `get_specified_notes/get_specified_awemes/get_specified_videos` 路径。

- [ ] **Step 4: 运行 MediaSpider 相关测试**

Run: `conda run --no-capture-output -n starx pytest tests/test_mediaspider_detail.py tests/test_mediaspider_service.py tests/test_mediaspider_runtime.py tests/test_mediaspider_config.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add app/services/mediaspider/models.py app/services/mediaspider/service.py app/services/mediaspider/platform_resolver.py app/services/mediaspider/runtime/config_scope.py app/services/mediaspider/runtime/runner.py tests/test_mediaspider_detail.py
git commit -m "feat: support competitor content crawling"
```

### Task 2: 建立竞品持久化模型和迁移

**Files:**
- Create: `alembic/versions/20260716_000021_competitor_monitoring.py`
- Modify: `app/db/models.py`
- Modify: `app/core/config.py`
- Modify: `.env.example`
- Test: `tests/test_competitor_models.py`

**Interfaces:**
- Consumes: `AccountRecord`、`UserRecord`、`WorkflowRecord`。
- Produces: `CompetitorAccountRecord`、`CompetitorVideoRecord`、`CompetitorSnapshotRecord` 和三个正整数配置字段。

- [ ] **Step 1: 写失败的 ORM 与配置测试**

```python
from datetime import UTC, datetime

from app.core.config import Settings
from app.db.models import CompetitorAccountRecord, CompetitorVideoRecord
from tests.db_test_utils import db_session


def test_competitor_account_and_video_are_scoped_and_deletable():
    with db_session() as session:
        account = CompetitorAccountRecord(
            id="ca_1", account_id="acc1", user_id="u_001", platform="dy",
            profile_url="https://www.douyin.com/user/a", next_refresh_at=datetime.now(UTC),
        )
        video = CompetitorVideoRecord(
            id="cv_1", account_id="acc1", user_id="u_001", platform="dy",
            content_url="https://www.douyin.com/video/1", next_refresh_at=datetime.now(UTC),
        )
        session.add_all([account, video])
        session.commit()
        assert session.get(CompetitorAccountRecord, "ca_1").profile_url.endswith("/a")
        assert session.get(CompetitorVideoRecord, "cv_1").content_url.endswith("/1")


def test_competitor_scheduler_settings_have_safe_positive_defaults():
    settings = Settings(_env_file=None)
    assert settings.COMPETITOR_REFRESH_INTERVAL_SECONDS == 21600
    assert settings.COMPETITOR_SCHEDULER_SCAN_SECONDS == 60
    assert settings.COMPETITOR_SCHEDULER_BATCH_SIZE == 20
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `conda run --no-capture-output -n starx pytest tests/test_competitor_models.py -q`

Expected: FAIL，提示竞品 ORM 类尚不存在。

- [ ] **Step 3: 实现 ORM、关系和配置**

三个模型使用 `DateTime(timezone=True)`、`BigInteger`、`JSON`、`ondelete="CASCADE"`。账号与视频表都包含设计规格中的刷新字段；快照使用：

```python
__table_args__ = (
    UniqueConstraint("target_type", "target_id", "workflow_id", name="uq_competitor_snapshot_workflow"),
)
```

Settings 增加：

```python
COMPETITOR_REFRESH_INTERVAL_SECONDS: int = Field(default=21600, ge=60)
COMPETITOR_SCHEDULER_SCAN_SECONDS: int = Field(default=60, ge=1)
COMPETITOR_SCHEDULER_BATCH_SIZE: int = Field(default=20, ge=1, le=100)
```

迁移创建外键、`(account_id, profile_url)`、`(account_id, content_url)` 唯一约束，以及 `(next_refresh_at, active_workflow_id)` 到期认领索引。

- [ ] **Step 4: 验证模型和迁移**

Run: `conda run --no-capture-output -n starx pytest tests/test_competitor_models.py tests/test_database_init.py -q`

Run: `conda run -n starx alembic upgrade head`

Expected: 测试 PASS，迁移成功到 `20260716_000021`。

- [ ] **Step 5: 提交**

```bash
git add alembic/versions/20260716_000021_competitor_monitoring.py app/db/models.py app/core/config.py .env.example tests/test_competitor_models.py
git commit -m "feat: persist competitor monitoring targets"
```

### Task 3: 实现指标映射、快照和刷新业务服务

**Files:**
- Create: `app/services/competitor_monitoring/__init__.py`
- Create: `app/services/competitor_monitoring/models.py`
- Create: `app/services/competitor_monitoring/normalizers.py`
- Create: `app/services/competitor_monitoring/repository.py`
- Create: `app/services/competitor_monitoring/service.py`
- Test: `tests/test_competitor_normalizers.py`
- Test: `tests/test_competitor_service.py`

**Interfaces:**
- Consumes: `MediaCrawlerService` 的 `CrawlResult`，Task 2 的三个 ORM 类。
- Produces: `CompetitorMonitoringService.add_account/add_video/delete_account/delete_video/create_refresh/complete_refresh/fail_refresh`，以及 `CompetitorRepository.claim_due_targets(now: datetime, limit: int) -> list[WorkflowRecord]`。

- [ ] **Step 1: 写失败的 normalizer 与增量测试**

```python
from app.services.competitor_monitoring.normalizers import metric_delta, normalize_video


def test_metric_delta_ignores_missing_values_and_keeps_negative_changes():
    assert metric_delta(
        {"likes": 90, "comments": None, "shares": 8},
        {"likes": 100, "comments": 4, "shares": None},
    ) == {"likes": -10}


def test_normalize_douyin_video_uses_only_public_whitelisted_fields():
    normalized = normalize_video("dy", {
        "aweme_id": "123", "title": "真实标题", "liked_count": 20,
        "comment_count": 3, "share_count": 2, "cookie": "must-not-leak",
    })
    assert normalized.platform_content_id == "123"
    assert normalized.metrics == {"likes": 20, "comments": 3, "shares": 2}
    assert "cookie" not in normalized.model_dump_json()
```

- [ ] **Step 2: 写失败的添加、删除、任务去重与失败保留测试**

```python
def test_add_and_delete_both_target_types(competitor_service):
    account, account_workflow = competitor_service.add_account(
        "u_001", "acc1", "https://www.douyin.com/user/a"
    )
    video, video_workflow = competitor_service.add_video(
        "u_001", "acc1", "https://www.douyin.com/video/1"
    )
    assert account_workflow.input_payload["targetType"] == "account"
    assert video_workflow.input_payload["targetType"] == "video"
    competitor_service.delete_account("u_001", "acc1", account.id)
    competitor_service.delete_video("u_001", "acc1", video.id)
    assert competitor_service.list_accounts("u_001", "acc1") == []
    assert competitor_service.list_videos("u_001", "acc1") == []


def test_repeated_refresh_reuses_active_workflow(competitor_service, saved_video):
    first, first_is_new = competitor_service.create_refresh("u_001", "acc1", "video", saved_video.id, "manual")
    second, second_is_new = competitor_service.create_refresh("u_001", "acc1", "video", saved_video.id, "manual")
    assert first.id == second.id
    assert first_is_new is True
    assert second_is_new is False


def test_failed_refresh_keeps_last_successful_metrics(competitor_service, refreshed_video):
    competitor_service.fail_refresh(refreshed_video.active_workflow_id, "credentials_expired", "平台登录凭证失效")
    saved = competitor_service.get_video("u_001", "acc1", refreshed_video.id)
    assert saved.likes == refreshed_video.likes
    assert saved.refresh_status == "failed"
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `conda run --no-capture-output -n starx pytest tests/test_competitor_normalizers.py tests/test_competitor_service.py -q`

Expected: FAIL，提示领域包尚不存在。

- [ ] **Step 4: 实现领域类型和 normalizer**

定义不可变 Pydantic 类型：

```python
class NormalizedCompetitor(BaseModel):
    platform: Literal["xhs", "dy", "ks"]
    platform_content_id: str = ""
    name: str = ""
    title: str = ""
    description: str = ""
    profile_url: str = ""
    content_url: str = ""
    cover_url: str = ""
    author_name: str = ""
    author_profile_url: str = ""
    published_at: datetime | None = None
    metrics: dict[str, int | None] = Field(default_factory=dict)
```

normalizer 对账号只允许 `followers/following/works/liked`，对视频只允许 `likes/comments/shares/plays/collects`。数值转换拒绝布尔值、负数和无法解析的字符串。

- [ ] **Step 5: 实现 repository 与 service 事务边界**

`add_account/add_video` 在校验账号归属后创建目标和首次工作流；重复 URL 抛出 `DuplicateCompetitorTarget`。删除方法使用 `user_id + account_id + id` 查找，不存在或越权统一抛出 `CompetitorTargetNotFound`。`complete_refresh` 必须检查 `target.active_workflow_id == workflow_id`，否则抛出 `StaleCompetitorWorkflow` 并不写数据。

成功事务按顺序执行：读取上一快照、计算 delta、插入快照、更新白名单字段、清错、清活动 ID、更新三个时间字段。失败事务只更新刷新状态、公开错误和尝试时间。

- [ ] **Step 6: 运行领域测试**

Run: `conda run --no-capture-output -n starx pytest tests/test_competitor_normalizers.py tests/test_competitor_service.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add app/services/competitor_monitoring tests/test_competitor_normalizers.py tests/test_competitor_service.py
git commit -m "feat: add competitor monitoring service"
```

### Task 4: 注册刷新工作流并实现账号/视频 CRUD API

**Files:**
- Create: `app/services/competitor_monitoring/workflow.py`
- Create: `app/schemas/competitors.py`
- Create: `app/api/routes/competitors.py`
- Modify: `app/services/workflow/scheduler.py`
- Modify: `app/api/router.py`
- Test: `tests/test_competitor_api.py`

**Interfaces:**
- Consumes: Task 1 爬虫接口、Task 3 业务服务。
- Produces: `/accounts/{account_id}/competitors/...` 全部 API 和注册类型 `competitor_refresh`。

- [ ] **Step 1: 写失败的账号和视频 CRUD API 测试**

```python
def test_user_can_add_list_and_delete_competitor_account(client):
    created = client.post(
        "/api/v1/accounts/acc1/competitors/accounts",
        json={"profileUrl": "https://www.douyin.com/user/a"},
    )
    assert created.status_code == 201
    target_id = created.json()["target"]["id"]
    assert client.get("/api/v1/accounts/acc1/competitors/accounts").json()[0]["id"] == target_id
    assert client.delete(f"/api/v1/accounts/acc1/competitors/accounts/{target_id}").status_code == 204


def test_user_can_add_list_and_delete_competitor_video(client):
    created = client.post(
        "/api/v1/accounts/acc1/competitors/videos",
        json={"contentUrl": "https://www.douyin.com/video/1"},
    )
    assert created.status_code == 201
    target_id = created.json()["target"]["id"]
    assert client.get("/api/v1/accounts/acc1/competitors/videos").json()[0]["id"] == target_id
    assert client.delete(f"/api/v1/accounts/acc1/competitors/videos/{target_id}").status_code == 204
```

- [ ] **Step 2: 写失败的隔离、重复和刷新测试**

```python
def test_competitor_targets_are_account_scoped(client, saved_video):
    response = client.delete(f"/api/v1/accounts/acc2/competitors/videos/{saved_video.id}")
    assert response.status_code == 404


def test_duplicate_target_returns_conflict(client):
    payload = {"contentUrl": "https://www.douyin.com/video/1"}
    assert client.post("/api/v1/accounts/acc1/competitors/videos", json=payload).status_code == 201
    assert client.post("/api/v1/accounts/acc1/competitors/videos", json=payload).status_code == 409


def test_single_and_batch_refresh_submit_new_workflows_once(client, recording_scheduler, saved_video):
    first = client.post(f"/api/v1/accounts/acc1/competitors/videos/{saved_video.id}/refresh")
    second = client.post(f"/api/v1/accounts/acc1/competitors/videos/{saved_video.id}/refresh")
    assert first.json()["id"] == second.json()["id"]
    assert recording_scheduler.submissions == [("competitor_refresh", first.json()["id"])]
```

- [ ] **Step 3: 运行 API 测试并确认失败**

Run: `conda run --no-capture-output -n starx pytest tests/test_competitor_api.py -q`

Expected: FAIL，路由返回 404。

- [ ] **Step 4: 实现 workflow、schema 和路由**

工作流：

```python
@WorkflowRegister.register
class CompetitorRefreshWorkflow(BaseWorkflow):
    type = "competitor_refresh"
    requires_ai = False

    async def execute(self) -> dict[str, object]:
        service = self.context.get("_competitor_service") or CompetitorMonitoringService()
        return await service.execute_refresh(self.workflow_id)
```

路由依赖注入 `CompetitorMonitoringService` 和现有 `WorkflowScheduler`。新增返回 `201`；删除返回 `204`；重复返回 `409`；输入校验返回 `422`；越权与不存在返回 `404`。新工作流在数据库事务提交后提交；scheduler 提交失败时调用 `fail_refresh`。

- [ ] **Step 5: 运行 API 与工作流注册测试**

Run: `conda run --no-capture-output -n starx pytest tests/test_competitor_api.py tests/test_competitor_service.py tests/test_generation_jobs.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add app/services/competitor_monitoring/workflow.py app/schemas/competitors.py app/api/routes/competitors.py app/services/workflow/scheduler.py app/api/router.py tests/test_competitor_api.py
git commit -m "feat: expose competitor monitoring api"
```

### Task 5: 实现数据库驱动的后台定时刷新

**Files:**
- Create: `app/services/competitor_monitoring/periodic_scheduler.py`
- Modify: `app/main.py`
- Test: `tests/test_competitor_periodic_scheduler.py`
- Modify: `tests/test_job_shutdown.py`

**Interfaces:**
- Consumes: `CompetitorRepository.claim_due_targets(now, limit)`，`WorkflowScheduler.submit`。
- Produces: `CompetitorPeriodicScheduler.start() -> None`、`stop() -> Awaitable[None]`、`scan_once() -> int`。

- [ ] **Step 1: 写失败的到期认领和重复扫描测试**

```python
@pytest.mark.asyncio
async def test_scan_submits_due_account_and_video_once(periodic_scheduler, repository, recording_scheduler):
    repository.save_due_account("ca_due")
    repository.save_due_video("cv_due")
    assert await periodic_scheduler.scan_once() == 2
    assert await periodic_scheduler.scan_once() == 0
    assert [item[0] for item in recording_scheduler.submissions] == [
        "competitor_refresh", "competitor_refresh"
    ]


@pytest.mark.asyncio
async def test_one_submission_failure_does_not_stop_other_targets(periodic_scheduler, recording_scheduler):
    recording_scheduler.fail_workflow_ids.add("wf_first")
    assert await periodic_scheduler.scan_once() == 2
    assert recording_scheduler.attempted == ["wf_first", "wf_second"]
```

- [ ] **Step 2: 写失败的 FastAPI 生命周期测试**

```python
def test_app_lifespan_starts_and_stops_competitor_scheduler(monkeypatch):
    calls = []
    monkeypatch.setattr("app.main.competitor_periodic_scheduler.start", lambda: calls.append("start"))

    async def stop():
        calls.append("stop")

    monkeypatch.setattr("app.main.competitor_periodic_scheduler.stop", stop)
    with TestClient(app):
        assert calls == ["start"]
    assert calls == ["start", "stop"]
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `conda run --no-capture-output -n starx pytest tests/test_competitor_periodic_scheduler.py tests/test_job_shutdown.py -q`

Expected: FAIL，周期扫描器尚不存在。

- [ ] **Step 4: 实现扫描器和生命周期**

`start` 用当前事件循环创建一个任务；run loop 使用 `asyncio.Event.wait()` 配合 `asyncio.wait_for(..., timeout=scan_seconds)`，避免不可中断的长 sleep。`scan_once` 调用 repository 的 PostgreSQL `with_for_update(skip_locked=True)` 认领；SQLite 测试退化为事务内普通行锁语义。每个提交独立 try/except 并记录安全错误。

FastAPI lifespan 顺序固定为：清理陈旧活动 ID、启动扫描器、`yield`、停止扫描器、执行现有未完成工作流关停处理。

- [ ] **Step 5: 运行调度与关停测试**

Run: `conda run --no-capture-output -n starx pytest tests/test_competitor_periodic_scheduler.py tests/test_job_shutdown.py -q`

Expected: PASS，且没有遗留 asyncio task 警告。

- [ ] **Step 6: 提交**

```bash
git add app/services/competitor_monitoring/periodic_scheduler.py app/main.py tests/test_competitor_periodic_scheduler.py tests/test_job_shutdown.py
git commit -m "feat: schedule competitor refreshes"
```

### Task 6: 增加前端 API 和可测试的监控生命周期 hook

**Files:**
- Modify: `../starx-frontend/src/api/starx.js`
- Modify: `../starx-frontend/src/api/starx.test.js`
- Create: `../starx-frontend/src/hooks/useCompetitorMonitoring.js`
- Create: `../starx-frontend/src/hooks/useCompetitorMonitoring.test.js`

**Interfaces:**
- Consumes: Task 4 REST API。
- Produces: `useCompetitorMonitoring({ accountId, api, addToast })`，返回列表、加载状态、活动操作和 CRUD/刷新方法。

- [ ] **Step 1: 写失败的前端 API 测试**

```javascript
test("competitor account and video APIs support add delete and refresh", async () => {
  await starxApi.getCompetitorAccounts("acc1");
  await starxApi.addCompetitorAccount("acc1", "https://www.douyin.com/user/a");
  await starxApi.deleteCompetitorAccount("acc1", "ca_1");
  await starxApi.refreshCompetitorAccount("acc1", "ca_1");
  await starxApi.getCompetitorVideos("acc1");
  await starxApi.addCompetitorVideo("acc1", "https://www.douyin.com/video/1");
  await starxApi.deleteCompetitorVideo("acc1", "cv_1");
  await starxApi.refreshCompetitorVideos("acc1");
  assert.deepEqual(calls.map(({ options }) => options.method), [
    undefined, "POST", "DELETE", "POST", undefined, "POST", "DELETE", "POST"
  ]);
});
```

- [ ] **Step 2: 写失败的轮询和账号切换测试**

```javascript
test("account switch rejects stale list and workflow responses", async () => {
  const first = deferred();
  const harness = createCompetitorMonitoringHarness({ getCompetitorVideos: () => first.promise });
  harness.load("acc1");
  harness.switchAccount("acc2");
  first.resolve([{ id: "stale" }]);
  await first.promise;
  assert.deepEqual(harness.state.videos, []);
});

test("workflow polling stops after terminal status and reloads lists", async () => {
  const harness = createCompetitorMonitoringHarness({
    getWorkflow: sequence([{ status: "running" }, { status: "completed" }]),
  });
  harness.track("acc1", "wf_1");
  await harness.scheduler.runAll();
  assert.equal(harness.scheduler.size, 0);
  assert.equal(harness.state.reloadCount, 1);
});
```

- [ ] **Step 3: 运行测试并确认失败**

Run: `npm test -- src/api/starx.test.js src/hooks/useCompetitorMonitoring.test.js`

Workdir: `../starx-frontend`

Expected: FAIL，API 方法和 hook 尚不存在。

- [ ] **Step 4: 实现 API 与 hook**

API 使用设计规格中的对称路径。hook 用递增 `runRef` 和 `accountIdRef` 同时保护列表与轮询响应；活动工作流每 2 秒轮询，终态后重载当前类型列表；卸载、退出登录或切换账号时清除全部 timer。删除成功后立即从本地列表移除并后台重载确认。

- [ ] **Step 5: 运行前端数据层测试**

Run: `npm test -- src/api/starx.test.js src/hooks/useCompetitorMonitoring.test.js`

Workdir: `../starx-frontend`

Expected: PASS。

- [ ] **Step 6: 提交前端数据层**

```bash
git add src/api/starx.js src/api/starx.test.js src/hooks/useCompetitorMonitoring.js src/hooks/useCompetitorMonitoring.test.js
git commit -m "feat: add competitor monitoring client"
```

Workdir: `../starx-frontend`

### Task 7: 替换竞品演示页并完成账号/视频添加删除交互

**Files:**
- Create: `../starx-frontend/src/components/competitors/CompetitorAddModal.jsx`
- Create: `../starx-frontend/src/components/competitors/CompetitorMetric.jsx`
- Create: `../starx-frontend/src/components/competitors/CompetitorAccountCard.jsx`
- Create: `../starx-frontend/src/components/competitors/CompetitorVideoCard.jsx`
- Modify: `../starx-frontend/src/pages/CompetitorMonitor.jsx`
- Modify: `../starx-frontend/src/styles.css`
- Create: `../starx-frontend/src/pages/CompetitorMonitor.preview.test.js`

**Interfaces:**
- Consumes: Task 6 hook。
- Produces: 真实竞品页面，账号/视频均支持添加、删除、单项刷新和全部刷新。

- [ ] **Step 1: 写失败的页面结构与行为测试**

```javascript
test("competitor page contains no demo seed and supports both target types", () => {
  assert.doesNotMatch(pageSource, /美妆达人小A|本地美食家老张|const seed/);
  assert.match(pageSource, /监控视频/);
  assert.match(pageSource, /监控账号/);
  assert.match(pageSource, /刷新全部/);
  assert.match(pageSource, /CompetitorAddModal/);
  assert.match(accountCardSource, /deleteAccount/);
  assert.match(videoCardSource, /deleteVideo/);
});

test("missing metrics render a dash and delete asks for confirmation", () => {
  assert.match(metricSource, /value == null/);
  assert.match(metricSource, /—/);
  assert.match(accountCardSource, /window\.confirm/);
  assert.match(videoCardSource, /window\.confirm/);
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm test -- src/pages/CompetitorMonitor.preview.test.js`

Workdir: `../starx-frontend`

Expected: FAIL，当前页面仍包含演示 seed。

- [ ] **Step 3: 实现添加弹窗和可复用指标组件**

弹窗使用 `role="dialog"`、`aria-modal="true"`，支持 Escape 和遮罩关闭；提交时禁止空链接和重复提交。类型为 `account` 时调用 `addAccount`，类型为 `video` 时调用 `addVideo`。指标组件对 `null/undefined` 显示 `—`，只在 delta 为数值时显示正负号。

- [ ] **Step 4: 实现账号卡与视频卡**

两种卡片都展示平台、状态、最后成功时间、刷新和删除。账号卡展示粉丝/作品/获赞并打开 `profileUrl`；视频卡展示点赞/评论/分享/播放并打开 `contentUrl`。删除使用明确的对象名称确认文案，成功后调用 hook 的真实删除方法。

- [ ] **Step 5: 重写页面编排与空/失败状态**

页面按 mode 使用对应列表和操作；顶部显示成功、刷新中、失败数量；空列表展示“添加监控账号/视频”主按钮；全部刷新按钮在空列表或全部活动时禁用。首次采集前不渲染伪造名称和数字。

- [ ] **Step 6: 运行页面测试和构建**

Run: `npm test -- src/pages/CompetitorMonitor.preview.test.js src/hooks/useCompetitorMonitoring.test.js src/api/starx.test.js`

Run: `npm run build`

Workdir: `../starx-frontend`

Expected: 测试 PASS，Vite build 成功。

- [ ] **Step 7: 提交前端页面**

```bash
git add src/components/competitors src/pages/CompetitorMonitor.jsx src/pages/CompetitorMonitor.preview.test.js src/styles.css
git commit -m "feat: build competitor monitoring page"
```

Workdir: `../starx-frontend`

### Task 8: 完成跨端回归和目标验收

**Files:**
- Create: `docs/competitor-monitoring-api.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1-7 全部产物。
- Produces: 可复现的测试证据和中文接口/数据库说明。

- [ ] **Step 1: 补充中文 API 与数据库文档**

在 `docs/competitor-monitoring-api.md` 记录两类列表、添加、删除、单项/批量刷新和工作流查询的请求响应，并记录三张表、唯一约束、快照和调度字段。文档明确删除会清理快照、刷新失败保留旧数据。`README.md` 增加文档入口和三个定时配置项。

- [ ] **Step 2: 运行后端竞品专项测试**

Run: `conda run --no-capture-output -n starx pytest tests/test_mediaspider_detail.py tests/test_competitor_models.py tests/test_competitor_normalizers.py tests/test_competitor_service.py tests/test_competitor_api.py tests/test_competitor_periodic_scheduler.py -q`

Expected: PASS。

- [ ] **Step 3: 运行后端全量回归**

Run: `conda run --no-capture-output -n starx pytest -q`

Expected: PASS；若存在与本功能无关的基线失败，记录精确测试名和既有证据，不修改无关业务代码。

- [ ] **Step 4: 运行前端全量回归和生产构建**

Run: `npm test`

Run: `npm run build`

Workdir: `../starx-frontend`

Expected: 全部测试 PASS，构建成功。

- [ ] **Step 5: 验证迁移和代码卫生**

Run: `conda run -n starx alembic upgrade head`

Run: `git diff --check`

Expected: 数据库位于新 head，diff 无空白错误。

- [ ] **Step 6: 按原始目标逐项审计**

检查并记录以下证据：

```text
监控视频实现：模型、CRUD API、页面卡片、专项测试
监控账号实现：模型、CRUD API、页面卡片、专项测试
用户添加删除：两类 POST/DELETE API 与前端确认交互测试
前台主动刷新：单项/批量刷新 API、轮询 hook 与页面状态测试
后台定时爬取：到期认领、生命周期扫描、MediaSpider 工作流测试
数据刷新正确性：快照、增量、失败保留旧数据测试
隔离与安全：用户/运营账号越权和敏感信息白名单测试
```

- [ ] **Step 7: 提交文档**

```bash
git add README.md docs/competitor-monitoring-api.md
git commit -m "docs: document competitor monitoring"
```
