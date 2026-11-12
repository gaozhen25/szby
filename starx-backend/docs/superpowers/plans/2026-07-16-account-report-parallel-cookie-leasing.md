# 账号报告多 Cookie 并行关键词采集实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为账号报告实现进程内全局 Cookie 租约、每平台最多 3 个独立子进程并行关键词采集、凭证禁用与指数退避，并在爬虫中途失败时保留可用部分结果继续生成报告。

**Architecture:** 主进程把主页和每个关键词拆成独立采集单元，由平台调度器申请全局 Cookie 租约并启动 `spawn` 子进程；子进程隔离 MediaSpider 模块级配置和浏览器，主进程负责重试、部分结果累加、稳定去重、workflow 持久化与前端进度。第一版租约只保证单后端进程内互斥，未来多 Worker 再替换为 Redis 租约。

**Tech Stack:** Python 3.12、asyncio、multiprocessing `spawn`、Pydantic v2、pytest（必须使用 `starx` Conda 环境）、React 18、Node.js `node:test`。

## Global Constraints

- 后端 Python 命令只能使用 `conda run -n starx ...`，不得创建其他 venv 或 Conda 环境。
- 设计文档和实施说明使用中文；代码按现有项目风格命名。
- 每个平台同时运行的采集子进程默认上限为 `3`。
- Cookie 首次退避 `30` 秒、最大退避 `600` 秒、最多 `3` 轮、采集单元总时限 `900` 秒。
- `credentials_expired` 立即禁用 Cookie，只有 `cookies.json` 规范化内容指纹变化后才恢复候选。
- 同一个 Cookie 在同一后端进程内任何时刻最多只能有一个租约，主页任务也必须经过租约管理器。
- Cookie 不得进入命令行、普通环境变量、日志、异常文本、进度、数据库结果或对象 `repr`。
- 子进程失败时必须返回完整安全部分 `CrawlResult`；至少有一条内容或账号才算可用，只有评论不算。
- 重试前先累加部分结果；重试耗尽但已有可用结果时状态为 `partial`，继续生成报告。
- `sourceMeta.failedPlatforms` 只记录完全无可用结果的平台；部分采集写入 `sourceMeta.partialCrawls`。
- 后端与前端是两个独立 Git 仓库，必须分别提交，不得把一个仓库的改动混入另一个仓库提交。

---

## 文件结构

后端新增模块：

- `app/services/mediaspider/result_merge.py`：安全复制、稳定去重、孤立评论过滤和部分结果累加。
- `app/services/mediaspider/cookie_leases.py`：配置指纹、Cookie 状态机、异步租约、公平等待与热重载。
- `app/services/mediaspider/crawl_units.py`：采集单元、结果状态和关键词级结果模型。
- `app/services/mediaspider/crawl_scheduler.py`：平台并发、Cookie 切换、指数退避和三轮/总时限控制。
- `app/services/mediaspider/subprocess_protocol.py`：父子进程白名单消息协议。
- `app/services/mediaspider/subprocess_worker.py`：可由 `spawn` 导入的子进程入口。
- `app/services/mediaspider/subprocess_runner.py`：异步启动、读取进度、超时和进程树清理。
- `app/services/account_report/parallel_crawl.py`：把主页和关键词转换为采集单元，聚合平台结果。

后端修改模块：

- `app/core/config.py`、`.env.example`：新增租约和调度配置。
- `app/services/mediaspider/models.py`：扩展安全部分结果和采集单元进度字段。
- `app/services/account_report/crawl_progress.py`、`crawl_progress_models.py`：按采集单元聚合计数。
- `app/services/account_report/models.py`：增加 `PartialCrawlMeta` 和 `sourceMeta.partialCrawls`。
- `app/services/account_report/workflow.py`：接入并行协调器并修改成功判定。

前端修改模块：

- `src/utils/accountReport.js`：归一化单元字段并区分单元计数与平台累计。
- `src/pages/account-report/AccountReportWorkflowProgress.jsx`：展示关键词单元、等待、冷却和部分成功。

---

### Task 1: 新增并验证调度配置

**Files:**
- Modify: `app/core/config.py`
- Modify: `.env.example`
- Modify: `tests/test_mediaspider_config.py`

**Interfaces:**
- Produces: `Settings.MEDIASPIDER_PLATFORM_MAX_CONCURRENT: int`
- Produces: `Settings.MEDIASPIDER_COOKIE_BACKOFF_INITIAL_SECONDS: int`
- Produces: `Settings.MEDIASPIDER_COOKIE_BACKOFF_MAX_SECONDS: int`
- Produces: `Settings.MEDIASPIDER_COOKIE_MAX_RETRY_ROUNDS: int`
- Produces: `Settings.MEDIASPIDER_CRAWL_UNIT_TIMEOUT_SECONDS: int`

- [ ] **Step 1: 写配置默认值和环境覆盖失败测试**

在 `tests/test_mediaspider_config.py` 增加：

```python
def test_parallel_cookie_scheduler_defaults():
    configured = Settings(_env_file=None)
    assert configured.MEDIASPIDER_PLATFORM_MAX_CONCURRENT == 3
    assert configured.MEDIASPIDER_COOKIE_BACKOFF_INITIAL_SECONDS == 30
    assert configured.MEDIASPIDER_COOKIE_BACKOFF_MAX_SECONDS == 600
    assert configured.MEDIASPIDER_COOKIE_MAX_RETRY_ROUNDS == 3
    assert configured.MEDIASPIDER_CRAWL_UNIT_TIMEOUT_SECONDS == 900


def test_parallel_cookie_scheduler_reads_starx_environment(monkeypatch):
    monkeypatch.setenv("STARX_MEDIASPIDER_PLATFORM_MAX_CONCURRENT", "2")
    monkeypatch.setenv("STARX_MEDIASPIDER_COOKIE_BACKOFF_INITIAL_SECONDS", "10")
    monkeypatch.setenv("STARX_MEDIASPIDER_COOKIE_BACKOFF_MAX_SECONDS", "120")
    monkeypatch.setenv("STARX_MEDIASPIDER_COOKIE_MAX_RETRY_ROUNDS", "4")
    monkeypatch.setenv("STARX_MEDIASPIDER_CRAWL_UNIT_TIMEOUT_SECONDS", "300")
    configured = Settings(_env_file=None)
    assert configured.MEDIASPIDER_PLATFORM_MAX_CONCURRENT == 2
    assert configured.MEDIASPIDER_COOKIE_BACKOFF_INITIAL_SECONDS == 10
    assert configured.MEDIASPIDER_COOKIE_BACKOFF_MAX_SECONDS == 120
    assert configured.MEDIASPIDER_COOKIE_MAX_RETRY_ROUNDS == 4
    assert configured.MEDIASPIDER_CRAWL_UNIT_TIMEOUT_SECONDS == 300
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n starx pytest tests/test_mediaspider_config.py -q`

Expected: FAIL，提示 `Settings` 缺少新增字段。

- [ ] **Step 3: 增加正整数配置与跨字段校验**

在 `Settings` 中增加：

```python
MEDIASPIDER_PLATFORM_MAX_CONCURRENT: int = Field(default=3, ge=1, le=16)
MEDIASPIDER_COOKIE_BACKOFF_INITIAL_SECONDS: int = Field(default=30, ge=1)
MEDIASPIDER_COOKIE_BACKOFF_MAX_SECONDS: int = Field(default=600, ge=1)
MEDIASPIDER_COOKIE_MAX_RETRY_ROUNDS: int = Field(default=3, ge=1, le=10)
MEDIASPIDER_CRAWL_UNIT_TIMEOUT_SECONDS: int = Field(default=900, ge=30)
```

在现有 `model_validator` 中保证最大退避不小于初始退避：

```python
if self.MEDIASPIDER_COOKIE_BACKOFF_MAX_SECONDS < self.MEDIASPIDER_COOKIE_BACKOFF_INITIAL_SECONDS:
    raise ValueError("Cookie 最大退避时间不能小于初始退避时间")
```

同步在 `.env.example` 写入五个 `STARX_` 配置及中文说明。

- [ ] **Step 4: 运行配置测试**

Run: `conda run -n starx pytest tests/test_mediaspider_config.py -q`

Expected: PASS。

- [ ] **Step 5: 提交后端配置**

```bash
git add .env.example app/core/config.py tests/test_mediaspider_config.py
git commit -m "feat: configure parallel crawler scheduling"
```

---

### Task 2: 保留安全部分结果并实现稳定合并

**Files:**
- Create: `app/services/mediaspider/result_merge.py`
- Modify: `app/services/mediaspider/models.py`
- Create: `tests/test_mediaspider_result_merge.py`
- Modify: `tests/test_mediaspider_runtime.py`

**Interfaces:**
- Produces: `safe_crawl_result(result: CrawlResult) -> CrawlResult`
- Produces: `merge_crawl_results(results: Iterable[CrawlResult], *, platform: str, crawl_type: Literal["search", "creator"]) -> CrawlResult`
- Produces: `PartialResultAccumulator.add(result: CrawlResult) -> None`
- Produces: `PartialResultAccumulator.result() -> CrawlResult`
- Produces: `PartialResultAccumulator.has_usable_evidence: bool`
- Produces: `CrawlerExecutionError.partial_result` 保留完整安全记录。

- [ ] **Step 1: 写失败测试覆盖安全复制、去重和孤立评论**

创建 `tests/test_mediaspider_result_merge.py`：

```python
from app.services.mediaspider.models import CrawlResult
from app.services.mediaspider.result_merge import PartialResultAccumulator


def test_accumulator_merges_retry_results_and_drops_orphan_comments():
    accumulator = PartialResultAccumulator(platform="xhs", crawl_type="search")
    accumulator.add(CrawlResult(
        platform="xhs",
        crawl_type="search",
        keywords=["防晒"],
        contents=[{"note_id": "n1", "title": "旧标题"}],
        comments=[
            {"comment_id": "c1", "note_id": "n1", "content": "有效"},
            {"comment_id": "orphan", "note_id": "missing", "content": "孤立"},
        ],
    ))
    accumulator.add(CrawlResult(
        platform="xhs",
        crawl_type="search",
        keywords=["防晒霜"],
        contents=[
            {"note_id": "n1", "title": "更新标题", "desc": "更完整"},
            {"note_id": "n2", "title": "新增"},
        ],
        comments=[{"comment_id": "c2", "note_id": "n2", "content": "有效二"}],
    ))

    result = accumulator.result()
    assert accumulator.has_usable_evidence is True
    assert [item["note_id"] for item in result.contents] == ["n1", "n2"]
    assert {item["comment_id"] for item in result.comments} == {"c1", "c2"}
    assert result.contents[0]["source_keywords"] == ["防晒", "防晒霜"]
    assert result.content_count == 2
    assert result.comment_count == 2


def test_comments_without_content_or_creator_are_not_usable():
    accumulator = PartialResultAccumulator(platform="xhs", crawl_type="search")
    accumulator.add(CrawlResult(
        platform="xhs",
        crawl_type="search",
        comments=[{"comment_id": "c1", "note_id": "missing"}],
    ))
    assert accumulator.has_usable_evidence is False
    assert accumulator.result().comments == []
```

在 `tests/test_mediaspider_runtime.py` 增加异常保留测试：

```python
def test_execution_error_preserves_safe_partial_records_without_credentials():
    partial = CrawlResult(
        platform="xhs",
        crawl_type="search",
        contents=[{"note_id": "n1", "title": "结果", "cookies": "secret"}],
        creators=[{"creator_hash": "h1", "cookie": "secret"}],
        content_count=1,
        creator_count=1,
    )
    error = CrawlerExecutionError("xhs", RuntimeError("cookie=unsafe"), partial)
    serialized = error.partial_result.model_dump_json()
    assert error.partial_result.contents[0]["note_id"] == "n1"
    assert error.partial_result.creators[0]["creator_hash"] == "h1"
    assert "secret" not in serialized
    assert "unsafe" not in str(error)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n starx pytest tests/test_mediaspider_result_merge.py tests/test_mediaspider_runtime.py::test_execution_error_preserves_safe_partial_records_without_credentials -q`

Expected: FAIL，模块不存在且异常仍丢弃记录。

- [ ] **Step 3: 实现安全复制与累加器**

`result_merge.py` 使用平台内容键 `note_id/aweme_id/video_id/content_id`、评论键 `comment_id`、账号键 `creator_hash`。递归移除规范化后等于 `cookie/cookies/authorization/token/session/secret/password` 的字段，并只保留评论所引用的已存在内容。核心接口：

```python
class PartialResultAccumulator:
    def __init__(self, *, platform: str, crawl_type: str):
        self._platform = platform
        self._crawl_type = crawl_type
        self._results: list[CrawlResult] = []

    def add(self, result: CrawlResult) -> None:
        if result.platform != self._platform:
            raise ValueError("partial result platform mismatch")
        self._results.append(safe_crawl_result(result))

    @property
    def has_usable_evidence(self) -> bool:
        merged = self.result()
        return bool(merged.contents or merged.creators)

    def result(self) -> CrawlResult:
        return merge_crawl_results(
            self._results,
            platform=self._platform,
            crawl_type=self._crawl_type,
        )
```

修改 `CrawlerExecutionError`：

```python
from .result_merge import safe_crawl_result
self.partial_result = safe_crawl_result(partial_result)
```

为避免循环导入，把 `safe_crawl_result` 中对模型的导入放在 `TYPE_CHECKING` 或函数内部；不得从 `result_merge.py` 导入异常类。

- [ ] **Step 4: 运行定向测试**

Run: `conda run -n starx pytest tests/test_mediaspider_result_merge.py tests/test_mediaspider_runtime.py -q`

Expected: PASS。

- [ ] **Step 5: 提交结果合并边界**

```bash
git add app/services/mediaspider/models.py app/services/mediaspider/result_merge.py tests/test_mediaspider_result_merge.py tests/test_mediaspider_runtime.py
git commit -m "feat: preserve partial crawler results"
```

---

### Task 3: 实现全局 Cookie 租约状态机与热重载

**Files:**
- Create: `app/services/mediaspider/cookie_leases.py`
- Modify: `app/services/mediaspider/cookie_pool.py`
- Create: `tests/test_mediaspider_cookie_leases.py`
- Modify: `tests/test_mediaspider_cookie_pool.py`

**Interfaces:**
- Consumes: Task 1 退避配置。
- Produces: `CookieLeaseManager.acquire(platform: str, *, excluded: frozenset[str]) -> CookieLease`
- Produces: `CookieLease.succeed()`, `disable()`, `cool_down()`。
- Produces: `CookieLease.slot: str`；Cookie 明文只能通过私有 `_secret_for_worker()` 交给子进程运行器。
- Produces: `CookiePoolExhaustedError` 和 `AllCookiesDisabledError`。
- Produces: 进程级单例 `get_process_cookie_lease_manager() -> CookieLeaseManager`；测试可显式构造隔离实例。

- [ ] **Step 1: 写租约互斥、公平、禁用、退避和重载测试**

创建 `tests/test_mediaspider_cookie_leases.py`，使用可注入 `clock` 和 `sleep` 的假时钟。至少包含：

```python
def test_same_cookie_is_never_leased_twice(tmp_path):
    async def scenario():
        path = write_pool(tmp_path, {"xhs": ["one"]})
        manager = CookieLeaseManager(path, clock=FakeClock())
        first = await manager.acquire("xhs")
        waiter = asyncio.create_task(manager.acquire("xhs"))
        await asyncio.sleep(0)
        assert waiter.done() is False
        await first.succeed()
        second = await waiter
        assert second.slot == first.slot
        await second.succeed()
    asyncio.run(scenario())


def test_expired_cookie_stays_disabled_until_contents_change(tmp_path):
    async def scenario():
        path = write_pool(tmp_path, {"xhs": ["expired", "valid"]})
        manager = CookieLeaseManager(path, clock=FakeClock())
        expired = await manager.acquire("xhs")
        expired_slot = expired.slot
        await expired.disable()
        assert (await manager.acquire("xhs")).slot != expired_slot
        path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        assert expired_slot in manager.disabled_slots("xhs")
        write_pool(tmp_path, {"xhs": ["expired-updated", "valid"]})
        await manager.reload_if_changed()
        assert manager.disabled_slots("xhs") == set()
    asyncio.run(scenario())
```

再覆盖 FIFO、删除租用中 Cookie 后延迟退役、无效新文件保留旧快照、冷却 `30/60/120/240/480/600`、成功重置退避、全部禁用立即失败、`repr` 和诊断快照不含 Cookie。

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n starx pytest tests/test_mediaspider_cookie_leases.py -q`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 从 `cookie_pool.py` 提取规范化快照**

保留现有文件解析兼容接口，并新增不可变快照：

```python
@dataclass(frozen=True, repr=False)
class CookiePoolSnapshot:
    version: str
    cookies_by_platform: dict[str, tuple[str, ...]]

    def __repr__(self) -> str:
        return "CookiePoolSnapshot(<redacted>)"


def read_cookie_pool_snapshot(path: Path = COOKIE_POOL_PATH) -> CookiePoolSnapshot:
    parsed = _read_normalized_cookie_map(path)
    canonical = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return CookiePoolSnapshot(
        version=hashlib.sha256(canonical.encode()).hexdigest(),
        cookies_by_platform=parsed,
    )
```

`load_cookie_pool` 继续调用同一个解析函数，保证旧调用方和既有测试不立即失效。

- [ ] **Step 4: 实现异步租约管理器**

`CookieLeaseManager` 使用单个 `asyncio.Condition` 保护状态，内部状态按 `(platform, cookie_digest)` 索引。`acquire` 每次循环先调用 `reload_if_changed()`，再按 FIFO 和轮询起点选择 `available` 且不在 `excluded` 中的 Cookie。所有状态出口都通知条件变量。

租约必须幂等结束：

```python
class CookieLease:
    async def succeed(self) -> None:
        await self._finish("success")

    async def disable(self) -> None:
        await self._finish("disabled")

    async def cool_down(self) -> None:
        await self._finish("cooldown")

    def __repr__(self) -> str:
        return f"CookieLease(platform={self.platform!r}, slot={self.slot!r})"
```

Cookie 明文保存在私有状态记录中，公开租约不提供普通 `secret` 属性；仅模块私有函数 `_lease_secret_for_worker(lease)` 可读取，并不得在其他模块记录或格式化。

模块级单例必须延迟创建并由线程锁保护，首次调用 `get_process_cookie_lease_manager()` 时读取当前 Settings。所有 workflow 共享该实例，禁止在每个 workflow 中各自创建管理器，否则无法实现跨账号报告互斥。

- [ ] **Step 5: 运行租约和旧 Cookie 池测试**

Run: `conda run -n starx pytest tests/test_mediaspider_cookie_leases.py tests/test_mediaspider_cookie_pool.py -q`

Expected: PASS。

- [ ] **Step 6: 提交租约管理器**

```bash
git add app/services/mediaspider/cookie_pool.py app/services/mediaspider/cookie_leases.py tests/test_mediaspider_cookie_pool.py tests/test_mediaspider_cookie_leases.py
git commit -m "feat: add global cookie lease manager"
```

---

### Task 4: 定义采集单元并实现重试调度器

**Files:**
- Create: `app/services/mediaspider/crawl_units.py`
- Create: `app/services/mediaspider/crawl_scheduler.py`
- Create: `tests/test_mediaspider_crawl_scheduler.py`

**Interfaces:**
- Consumes: `CookieLeaseManager`、`PartialResultAccumulator`。
- Produces: `CrawlUnit`、`CrawlUnitOutcome`、`CrawlUnitStatus`。
- Produces: `PlatformCrawlScheduler.run(unit, operation, on_progress=None) -> CrawlUnitOutcome`。
- Operation signature: `Callable[[CrawlUnit, CookieLease, ProgressCallback | None], Awaitable[CrawlResult]]`。

- [ ] **Step 1: 写并发、切换、退避和部分成功测试**

创建 `tests/test_mediaspider_crawl_scheduler.py`。使用假租约管理器和假 operation，覆盖：

```python
def test_retry_exhaustion_returns_partial_when_any_attempt_has_content():
    async def operation(unit, lease, _progress):
        raise CrawlerExecutionError(
            "xhs",
            RuntimeError("unsafe"),
            CrawlResult(
                platform="xhs",
                crawl_type="search",
                keywords=[unit.keyword],
                contents=[{"note_id": f"note-{lease.slot}"}],
                content_count=1,
            ),
            failure=public_crawler_failure("platform_blocked"),
        )

    outcome = asyncio.run(make_scheduler(rounds=1).run(
        CrawlUnit.keyword_unit("wf-1", "xhs", "防晒"), operation
    ))
    assert outcome.status == "partial"
    assert outcome.result.content_count == 2
    assert outcome.failure.code == "platform_blocked"


def test_comments_only_failure_is_failed_not_partial():
    async def operation(unit, lease, _progress):
        raise CrawlerExecutionError(
            "xhs",
            RuntimeError("unsafe"),
            CrawlResult(
                platform="xhs",
                crawl_type="search",
                comments=[{"comment_id": "orphan", "note_id": "missing"}],
            ),
            failure=public_crawler_failure("browser_timeout"),
        )
    outcome = asyncio.run(make_scheduler(rounds=1).run(
        CrawlUnit.keyword_unit("wf-1", "xhs", "防晒"), operation
    ))
    assert outcome.status == "failed"
    assert outcome.result.comments == []
```

再测试：每平台最多 3 个 operation 同时进入；`credentials_expired` 调用 `disable`；`platform_blocked/browser_timeout` 调用 `cool_down`；确定性错误不换 Cookie；每轮 Cookie 最多一次；失败任务回到队尾；三轮/900 秒终止；取消回收租约。

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n starx pytest tests/test_mediaspider_crawl_scheduler.py -q`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现采集单元和值对象**

```python
class CrawlUnitStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class CrawlUnit:
    id: str
    workflow_id: str
    platform: str
    crawl_type: Literal["search", "creator"]
    keyword: str = ""
    creator_url: str = field(default="", repr=False)

    @classmethod
    def keyword_unit(cls, workflow_id: str, platform: str, keyword: str) -> "CrawlUnit":
        return cls(uuid4().hex, workflow_id, platform, "search", keyword=keyword)


@dataclass(frozen=True)
class CrawlUnitOutcome:
    unit: CrawlUnit
    status: CrawlUnitStatus
    result: CrawlResult
    failure: CrawlerFailure | None = None
```

- [ ] **Step 4: 实现平台调度和失败处置**

`PlatformCrawlScheduler` 按平台缓存 `asyncio.Semaphore(max_concurrent)`。在 `asyncio.timeout(unit_timeout)` 内逐轮申请租约；每次异常先 `accumulator.add(exc.partial_result)`，再处置租约。

operation 正常返回时也必须先执行 `accumulator.add(result)`，再释放成功租约并返回 `status="completed"` 的合并结果，确保早期失败尝试取得的内容不会在后续成功时丢失。若租约池抛出 `AllCookiesDisabledError` 或总时限结束，则统一根据 `accumulator.has_usable_evidence` 返回 `partial` 或 `failed`。

失败规则必须写成显式表：

```python
_DISABLE_CODES = {"credentials_expired"}
_COOLDOWN_CODES = {"platform_blocked", "browser_timeout"}

if code in _DISABLE_CODES:
    await lease.disable()
elif code in _COOLDOWN_CODES:
    await lease.cool_down()
else:
    await lease.succeed()
    return failed_or_partial(accumulator, failure)
```

子进程启动失败由运行器包装成内部 `SubprocessUnavailableError`，调度器把它作为可冷却临时异常处理，但公开失败仍归一化为 `crawler_failed`。

- [ ] **Step 5: 运行调度器测试**

Run: `conda run -n starx pytest tests/test_mediaspider_crawl_scheduler.py -q`

Expected: PASS。

- [ ] **Step 6: 提交采集调度器**

```bash
git add app/services/mediaspider/crawl_units.py app/services/mediaspider/crawl_scheduler.py tests/test_mediaspider_crawl_scheduler.py
git commit -m "feat: schedule crawl units with cookie retries"
```

---

### Task 5: 实现安全子进程协议与独立运行器

**Files:**
- Create: `app/services/mediaspider/subprocess_protocol.py`
- Create: `app/services/mediaspider/subprocess_worker.py`
- Create: `app/services/mediaspider/subprocess_runner.py`
- Create: `tests/fixtures/fake_crawler_subprocess_worker.py`
- Create: `tests/test_mediaspider_subprocess_runner.py`

**Interfaces:**
- Consumes: `CrawlerRunConfig`、`CrawlerProgressEvent`、`CrawlResult`。
- Produces: `SubprocessCrawlerRunner.run(config, *, unit, cookie_lease, on_progress=None) -> CrawlResult`。
- Produces: `SubprocessUnavailableError`。
- Produces: 消息类型 `progress/result/error`，错误消息包含安全部分结果。

- [ ] **Step 1: 写协议安全和真实 spawn 生命周期测试**

测试必须实际使用 `multiprocessing.get_context("spawn")`，不能只 mock `Process`。fixture worker 根据关键词发送进度、成功、带部分结果失败、挂起或异常退出。

```python
def test_spawned_runner_returns_partial_result_on_worker_failure():
    async def scenario():
        events = []
        runner = SubprocessCrawlerRunner(worker_target=fake_worker_target)
        with pytest.raises(CrawlerExecutionError) as exc_info:
            await runner.run(
                make_config(keywords=["partial"]),
                unit=CrawlUnit.keyword_unit("wf-1", "xhs", "partial"),
                cookie_lease=FakeLease("xhs-1", "cookie-secret"),
                on_progress=events.append,
            )
        assert exc_info.value.partial_result.contents[0]["note_id"] == "n1"
        assert events[0].crawl_unit_id
        assert "cookie-secret" not in repr(exc_info.value)
    asyncio.run(scenario())
```

再覆盖：不同子进程配置互不污染；Cookie 不出现在 `ps` 风格命令参数、消息 `repr` 和日志；超时先终止再强制 kill；取消清理；损坏消息拒绝；worker 异常退出转换为 `SubprocessUnavailableError`。

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n starx pytest tests/test_mediaspider_subprocess_runner.py -q`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 定义白名单协议**

协议使用 Pydantic 判别联合，禁止额外字段：

```python
class WorkerProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["progress"] = "progress"
    event: CrawlerProgressEvent


class WorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["result"] = "result"
    result: CrawlResult


class WorkerError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["error"] = "error"
    failure: CrawlerFailure
    partial_result: CrawlResult = Field(alias="partialResult")
```

传入请求对象使用 `dataclass(repr=False)`，其中 `CrawlerRunConfig.cookies` 已设置 `exclude=True, repr=False`。不得把请求转成命令行 JSON 或环境变量。

- [ ] **Step 4: 实现可导入 worker 入口**

`subprocess_worker.py` 顶层函数：

```python
def run_worker(request: WorkerRequest, connection: Connection) -> None:
    async def emit(event: CrawlerProgressEvent) -> None:
        connection.send(WorkerProgress(event=event).model_dump(mode="python"))

    try:
        result = asyncio.run(run_crawler(request.config, on_progress=emit))
        connection.send(WorkerResult(result=result).model_dump(mode="python"))
    except CrawlerExecutionError as exc:
        connection.send(WorkerError(
            failure=exc.failure,
            partialResult=exc.partial_result,
        ).model_dump(mode="python", by_alias=True))
    finally:
        connection.close()
```

未知异常必须先经过 `classify_crawler_error` 和空安全结果归一化，不发送异常对象或字符串。

- [ ] **Step 5: 实现异步父进程运行器**

父进程通过私有双工管道发送请求，使用 `asyncio.to_thread(connection.recv)` 读取白名单消息；收到进度时补充采集单元字段并转发。收到结果或错误后 join 子进程。取消和超时统一调用 `_terminate_process_tree(process)`。

运行器必须只通过 Task 3 的模块私有桥接读取租约 Cookie，读取后立即构造请求，不保存到实例字段。

- [ ] **Step 6: 运行子进程测试和现有运行时测试**

Run: `conda run -n starx pytest tests/test_mediaspider_subprocess_runner.py tests/test_mediaspider_runtime.py -q`

Expected: PASS；现有进程内 `crawler_run_lock` 测试继续通过，因为锁仍保护单个子进程内部运行时。

- [ ] **Step 7: 提交子进程运行器**

```bash
git add app/services/mediaspider/subprocess_protocol.py app/services/mediaspider/subprocess_worker.py app/services/mediaspider/subprocess_runner.py tests/fixtures/fake_crawler_subprocess_worker.py tests/test_mediaspider_subprocess_runner.py
git commit -m "feat: isolate crawl units in subprocesses"
```

---

### Task 6: 扩展采集单元进度契约与聚合器

**Files:**
- Modify: `app/services/mediaspider/models.py`
- Modify: `app/services/account_report/crawl_progress_models.py`
- Modify: `app/services/account_report/crawl_progress.py`
- Modify: `tests/test_account_report_crawl_progress.py`

**Interfaces:**
- Produces: `CrawlerProgressEvent` 可选字段 `crawlUnitId/unitType/keyword/cookieSlot/unitStatus`。
- Produces: 单元计数 `unitContentCount/unitCreatorCount/unitCommentCount`。
- 保持: `contentCount/creatorCount/commentCount` 作为去重后的平台累计计数。

- [ ] **Step 1: 写单元隔离、合并键和部分成功进度测试**

在 `tests/test_account_report_crawl_progress.py` 增加：

```python
def test_tracker_does_not_attach_batch_comment_total_to_last_content():
    tracker, store = make_tracker("xhs")
    asyncio.run(tracker.record(unit_event(
        unit_id="unit-a", action="content_discovered", title="最后一条", unit_contents=10,
    )))
    asyncio.run(tracker.record(unit_event(
        unit_id="unit-a", action="comments_updated", unit_contents=10, unit_comments=182,
    )))
    activities = store.merged["crawlProgress"]["activities"]
    content_activity = next(item for item in activities if item["action"] == "content_discovered")
    comment_activity = next(item for item in activities if item["action"] == "comments_updated")
    assert content_activity["contentTitle"] == "最后一条"
    assert content_activity["unitCommentCount"] == 0
    assert comment_activity["keyword"] == "299元"
    assert comment_activity["unitCommentCount"] == 182


def test_partial_unit_keeps_counts_and_safe_message():
    tracker, store = make_tracker("xhs")
    tracker.complete_unit(
        "xhs", unit_id="unit-a", keyword="防晒", status="partial",
        result=CrawlResult(platform="xhs", crawl_type="search", content_count=6, comment_count=71),
        failure=public_crawler_failure("platform_blocked"),
    )
    current = store.merged["crawlProgress"]["current"]
    assert current["unitStatus"] == "partial"
    assert current["message"] == "已保留当前采集结果，报告将基于已有数据继续生成"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n starx pytest tests/test_account_report_crawl_progress.py -q`

Expected: FAIL，模型缺少单元字段或 tracker API。

- [ ] **Step 3: 扩展白名单模型**

所有新增字段设置长度和枚举边界：

```python
crawl_unit_id: str = Field(default="", alias="crawlUnitId", max_length=64)
unit_type: Literal["", "creator", "keyword"] = Field(default="", alias="unitType")
keyword: str = Field(default="", max_length=20)
cookie_slot: str = Field(default="", alias="cookieSlot", max_length=32)
unit_status: Literal["", "pending", "running", "completed", "partial", "failed"] = Field(default="", alias="unitStatus")
unit_content_count: int = Field(default=0, alias="unitContentCount", ge=0)
unit_creator_count: int = Field(default=0, alias="unitCreatorCount", ge=0)
unit_comment_count: int = Field(default=0, alias="unitCommentCount", ge=0)
```

- [ ] **Step 4: 将 tracker 改为按单元聚合**

`PlatformState` 新增 `units: dict[str, CrawlUnitProgressState]`。平台累计使用所有已结算单元结果的去重后总数，由 workflow/协调器在 `complete_unit` 时传入；活动中的单元计数直接来自事件。连续事件合并键增加 `crawl_unit_id`，不同关键词永不互相覆盖。

对于 `content_discovered`，活动不复制平台累计评论到内容上下文；平台累计仍只在平台摘要展示。

- [ ] **Step 5: 运行进度测试**

Run: `conda run -n starx pytest tests/test_account_report_crawl_progress.py -q`

Expected: PASS。

- [ ] **Step 6: 提交进度契约**

```bash
git add app/services/mediaspider/models.py app/services/account_report/crawl_progress.py app/services/account_report/crawl_progress_models.py tests/test_account_report_crawl_progress.py
git commit -m "feat: track account crawl units separately"
```

---

### Task 7: 实现账号报告并行采集协调器

**Files:**
- Create: `app/services/account_report/parallel_crawl.py`
- Create: `tests/test_account_report_parallel_crawl.py`
- Modify: `app/services/account_report/workflow.py`
- Modify: `tests/test_account_report_workflow.py`

**Interfaces:**
- Consumes: `PlatformCrawlScheduler`、`SubprocessCrawlerRunner`、`MediaCrawlerService`、tracker。
- Produces: `AccountReportCrawlOutcome`，包含 `current_results`、`industry_results`、`partial_crawls`、`failed_platforms` 和 `successful_units`。
- Produces: workflow context 注入点 `_crawl_scheduler` 和 `_crawler_runner`，便于无子进程单元测试。

- [ ] **Step 1: 写三个关键词并行、主页租约和部分结果测试**

创建 `tests/test_account_report_parallel_crawl.py`，用假 scheduler 记录同时进入数和 Cookie 槽位：

```python
def test_keywords_are_submitted_as_independent_units_and_merged():
    async def scenario():
        scheduler = RecordingScheduler(max_concurrent=3)
        outcome = await crawl_account_report_sources(
            workflow_id="wf-1",
            plans=[plan("xhs")],
            keywords=["防晒", "补水", "修护"],
            runtime_options_by_platform={"xhs": runtime_options()},
            scheduler=scheduler,
            crawler=FakeCrawler(),
            tracker=FakeTracker(),
        )
        assert scheduler.max_observed == 3
        assert {unit.keyword for unit in scheduler.units if unit.crawl_type == "search"} == {"防晒", "补水", "修护"}
        assert outcome.industry_results[0].content_count == 3
    asyncio.run(scenario())


def test_partial_keyword_result_keeps_workflow_usable():
    scheduler = SchedulerReturning([
        partial_outcome("xhs", "防晒", contents=[{"note_id": "n1"}]),
        failed_outcome("xhs", "补水"),
    ])
    outcome = asyncio.run(run_parallel_source_fixture(scheduler))
    assert outcome.has_usable_evidence is True
    assert outcome.partial_crawls[0].keyword == "防晒"
    assert outcome.failed_platforms == []
```

再覆盖：主页单元也经过 scheduler；多个平台分别限制并发；全部空或只有评论时 `has_usable_evidence=False`；取消传播；相同内容跨关键词去重。

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n starx pytest tests/test_account_report_parallel_crawl.py -q`

Expected: FAIL，协调器不存在。

- [ ] **Step 3: 实现协调器**

协调器先按平台执行主页单元，再一次性创建所有关键词任务并使用结构化并发：

```python
keyword_tasks = [
    asyncio.create_task(run_keyword_unit(plan, keyword))
    for plan in plans
    for keyword in keywords
    if credentials_available(plan.platform_code)
]
outcomes = await asyncio.gather(*keyword_tasks)
```

不得在 task 内直接写数据库；所有进度通过 tracker 的安全回调。平台最终结果使用 Task 2 合并器，`partial` 结果与成功结果同等进入证据集合，但另外生成 `PartialCrawlMeta`。

- [ ] **Step 4: 改造 workflow 使用协调器**

移除 workflow 内部两段串行 crawler 循环和 `run_with_cookie_candidates`。默认通过 `get_process_cookie_lease_manager()` 取得所有 workflow 共享的进程级租约管理器，再构造子进程运行器和平台调度器；测试可从 context 注入假实现。

成功门槛改为：

```python
if plans and not crawl_outcome.has_usable_evidence:
    raise ValueError(tracker.failure_summary())
```

`current_account_results`、`industry_results`、`failed_platforms` 从 outcome 取得。不得使用“完整成功单元数量大于零”作为报告生成条件。

- [ ] **Step 5: 运行协调器和 workflow 测试**

Run: `conda run -n starx pytest tests/test_account_report_parallel_crawl.py tests/test_account_report_workflow.py -q`

Expected: PASS；更新旧测试中“一组关键词一次调用”的断言为“每个关键词一次调用”。

- [ ] **Step 6: 提交账号报告采集协调器**

```bash
git add app/services/account_report/parallel_crawl.py app/services/account_report/workflow.py tests/test_account_report_parallel_crawl.py tests/test_account_report_workflow.py
git commit -m "feat: parallelize account report keyword crawls"
```

---

### Task 8: 增加部分采集来源元数据并修正平台失败语义

**Files:**
- Modify: `app/services/account_report/models.py`
- Modify: `app/services/account_report/workflow.py`
- Modify: `tests/test_account_report_models.py`（若不存在则创建）
- Modify: `tests/test_account_report_workflow.py`

**Interfaces:**
- Produces: `PartialCrawlMeta`。
- Produces: `SourceMeta.partial_crawls: list[PartialCrawlMeta]`，JSON 别名 `partialCrawls`。

- [ ] **Step 1: 写来源模型和失败平台测试**

```python
def test_source_meta_serializes_safe_partial_crawls():
    meta = SourceMeta.model_validate({
        "platforms": ["小红书"],
        "partialCrawls": [{
            "platform": "小红书",
            "mode": "keyword",
            "keyword": "防晒",
            "failureCode": "platform_blocked",
            "contentCount": 6,
            "creatorCount": 4,
            "commentCount": 71,
        }],
    })
    payload = meta.model_dump(mode="json", by_alias=True)
    assert payload["partialCrawls"][0]["contentCount"] == 6
    assert "cookieSlot" not in payload["partialCrawls"][0]


def test_partial_platform_is_not_listed_as_failed_platform():
    report = execute_with_outcomes([
        partial_outcome("xhs", "防晒", contents=[{"note_id": "n1"}]),
    ])
    assert report["sourceMeta"]["failedPlatforms"] == []
    assert report["sourceMeta"]["partialCrawls"][0]["keyword"] == "防晒"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n starx pytest tests/test_account_report_models.py tests/test_account_report_workflow.py -q`

Expected: FAIL，模型缺少 `partialCrawls`。

- [ ] **Step 3: 实现严格白名单模型**

```python
class PartialCrawlMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    platform: str = Field(max_length=20)
    mode: Literal["creator", "keyword"]
    keyword: str = Field(default="", max_length=20)
    failure_code: str = Field(alias="failureCode", max_length=40)
    content_count: int = Field(alias="contentCount", ge=0)
    creator_count: int = Field(alias="creatorCount", ge=0)
    comment_count: int = Field(alias="commentCount", ge=0)
```

`SourceMeta` 增加 `partial_crawls`，默认空数组并设置 `max_length=18`，对应最多 3 个支持平台乘以每平台 5 个关键词和 1 个主页单元。

- [ ] **Step 4: 接入 workflow 来源构造**

只从 `CrawlUnitOutcome(status="partial")` 构造 `PartialCrawlMeta`；完全失败且没有可用证据的平台才进入 `failedPlatforms`。报告 AI prompt 可读取计数和失败代码，但不得把 Cookie 槽位或底层异常传入。

- [ ] **Step 5: 运行模型与 workflow 测试**

Run: `conda run -n starx pytest tests/test_account_report_models.py tests/test_account_report_workflow.py -q`

Expected: PASS。

- [ ] **Step 6: 提交部分来源元数据**

```bash
git add app/services/account_report/models.py app/services/account_report/workflow.py tests/test_account_report_models.py tests/test_account_report_workflow.py
git commit -m "feat: report partial crawl provenance"
```

---

### Task 9: 前端区分单元进度、平台累计与部分成功

**Files（前端仓库 `../starx-frontend`）:**
- Modify: `src/utils/accountReport.js`
- Modify: `src/utils/accountReport.test.js`
- Modify: `src/pages/account-report/AccountReportWorkflowProgress.jsx`
- Modify: `src/pages/AccountReport.preview.test.js`

**Interfaces:**
- Consumes: Task 6 新增进度字段。
- Produces: 单元活动显示和部分成功固定文案。
- 保持: 旧 workflow 缺少新字段时沿用原累计展示。

- [ ] **Step 1: 写归一化和展示失败测试**

在 `src/utils/accountReport.test.js` 增加：

```javascript
test("keyword unit display uses unit counts instead of platform totals", () => {
  const display = createCrawlActivityDisplay({
    action: "comments_updated",
    platformName: "小红书",
    unitType: "keyword",
    keyword: "299元",
    unitContentCount: 10,
    unitCommentCount: 182,
    contentCount: 53,
    commentCount: 758,
  });
  assert.equal(display.context, "小红书 · 关键词「299元」");
  assert.deepEqual(display.counts, [
    { key: "unitContentCount", label: "本关键词内容", value: 10 },
    { key: "unitCommentCount", label: "本关键词评论", value: 182 },
  ]);
});


test("partial unit uses the safe retained-result message", () => {
  const display = createCrawlActivityDisplay({
    unitStatus: "partial",
    keyword: "防晒",
    message: "已保留当前采集结果，报告将基于已有数据继续生成",
    unitContentCount: 6,
  });
  assert.match(display.summary, /已有数据继续生成/);
});
```

预览测试断言组件分别渲染单元活动和平台摘要，不把 `commentCount` 放到带 `contentTitle` 的内容活动计数中。

- [ ] **Step 2: 运行前端测试确认失败**

Run（在 `starx-frontend`）: `npm test -- src/utils/accountReport.test.js src/pages/AccountReport.preview.test.js`

Expected: FAIL，归一化器忽略单元字段。

- [ ] **Step 3: 扩展前端白名单归一化**

增加文本字段 `crawlUnitId/unitType/keyword/cookieSlot/unitStatus` 和三个单元计数字段。显示规则：存在 `crawlUnitId` 时优先使用单元计数；平台累计只在 `PlatformSummaries` 展示。内容发现活动不显示平台累计评论。

```javascript
const UNIT_COUNT_LABELS = [
  ["unitContentCount", "本关键词内容"],
  ["unitCreatorCount", "本关键词账号"],
  ["unitCommentCount", "本关键词评论"],
];
```

`cookieSlot` 只用于可选内部状态文案，不在默认 UI 展示，避免用户把槽位误认为账号。

- [ ] **Step 4: 更新进度组件**

为 `partial` 活动增加中性提醒样式和固定文案；等待、切换、冷却继续使用后端安全消息。平台摘要保持去重累计计数。不得在 JSX 中自行推断失败分类。

- [ ] **Step 5: 运行前端定向和全量测试**

Run: `npm test`

Expected: PASS。

Run: `npm run build`

Expected: Vite 构建成功。

- [ ] **Step 6: 在前端仓库提交**

```bash
git add src/utils/accountReport.js src/utils/accountReport.test.js src/pages/account-report/AccountReportWorkflowProgress.jsx src/pages/AccountReport.preview.test.js
git commit -m "feat: show per-keyword crawl progress"
```

---

### Task 10: 集成、安全扫描与全量回归

**Files:**
- Modify: `tests/test_mediaspider_safe_logging.py`
- Modify: `tests/test_account_report_workflow.py`
- Modify: `README.md`（仅在已有 MediaSpider 配置章节补充新配置）

**Interfaces:**
- Consumes: Tasks 1～9 全部接口。
- Produces: 可验证的端到端并发、降级和安全保证。

- [ ] **Step 1: 写端到端假子进程场景**

增加集成测试：3 个 Cookie、5 个关键词，前三个并行；一个凭证失效、一个临时失败后成功、一个最终部分成功；断言同一 Cookie 不重叠、报告继续生成、`partialCrawls` 正确、`failedPlatforms` 为空。

```python
def test_parallel_cookie_failover_preserves_partial_report():
    result, audit = execute_parallel_fixture(
        cookies=["expired", "cooldown", "healthy"],
        keywords=["k1", "k2", "k3", "k4", "k5"],
    )
    assert audit.max_parallel == 3
    assert audit.overlapping_cookie_slots == set()
    assert result["reportVersion"] > 0
    assert result["sourceMeta"]["failedPlatforms"] == []
    assert any(item["keyword"] == "k4" for item in result["sourceMeta"]["partialCrawls"])
```

- [ ] **Step 2: 增加敏感信息扫描**

测试把唯一哨兵 Cookie 放入配置，遍历：异常字符串、日志记录、进度 payload、IPC 消息 `repr`、workflow `result_payload` 和最终报告 JSON，断言哨兵不存在。另断言操作系统子进程命令行不包含哨兵。

- [ ] **Step 3: 运行后端定向测试**

Run:

```bash
conda run -n starx pytest \
  tests/test_mediaspider_config.py \
  tests/test_mediaspider_cookie_pool.py \
  tests/test_mediaspider_cookie_leases.py \
  tests/test_mediaspider_result_merge.py \
  tests/test_mediaspider_crawl_scheduler.py \
  tests/test_mediaspider_subprocess_runner.py \
  tests/test_account_report_crawl_progress.py \
  tests/test_account_report_parallel_crawl.py \
  tests/test_account_report_models.py \
  tests/test_account_report_workflow.py \
  tests/test_mediaspider_safe_logging.py -q
```

Expected: PASS。

- [ ] **Step 4: 运行后端全量测试**

Run: `conda run -n starx pytest -q`

Expected: PASS；记录测试总数和耗时。

- [ ] **Step 5: 运行前端全量验证**

Run（在 `starx-frontend`）: `npm test && npm run build`

Expected: 全部测试通过且构建成功。

- [ ] **Step 6: 进行静态敏感词和差异检查**

Run（后端）:

```bash
rg -n "print\(.*cookie|logger\..*cookie|cookieSlot.*secret|cookies=.*repr" app tests
git diff --check
```

Expected: 没有新增凭证输出；`git diff --check` 无输出。

Run（前端）: `git diff --check`

Expected: 无输出。

- [ ] **Step 7: 更新运行说明并提交后端收尾**

在 README MediaSpider 配置章节说明：单进程全局租约、平台并发默认 3、凭证失效需更新 `cookies.json`、多 Worker 尚不共享租约。不得写入真实 Cookie 示例。

```bash
git add README.md tests/test_mediaspider_safe_logging.py tests/test_account_report_workflow.py
git commit -m "test: verify parallel crawler resilience"
```

- [ ] **Step 8: 记录验收证据**

在最终交付说明中记录：后端定向/全量测试结果、前端测试/构建结果、实际最大并发、Cookie 互斥断言、部分结果报告断言，以及后端和前端各自提交列表。不要记录 Cookie、配置文件内容或底层平台响应。
