# 账号报告采集进度与平台诊断实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 修复小红书 `xhshow 0.1.0` 签名兼容故障，并让账号报告页面通过现有轮询展示安全、可恢复的采集活动和平台级失败原因。

**架构：** MediaSpider 运行时通过白名单 `CrawlerProgressEvent` 回调上报锁等待、平台运行、内容/博主发现和计数；账号报告侧使用独立 Tracker 将事件聚合为有界 `crawlProgress` 快照并写入 workflow `resultPayload`。前端继续使用现有 1.5 秒轮询，通过纯函数归一化快照并由独立组件渲染当前活动、最近活动和平台摘要。

**技术栈：** Python 3.12、FastAPI、Pydantic 2、SQLAlchemy、pytest、Playwright、xhshow 0.1.0、React 18、Vite、Node test runner。

## 全局约束

- 所有设计与计划文档使用中文。
- 后端安装、运行和测试只能使用名为 `starx` 的 conda 环境。
- Cookie 只从后端环境变量读取，禁止进入 API、workflow payload、日志、测试快照和前端。
- 不引入 WebSocket、SSE、Redis Pub/Sub 或数据库迁移。
- 进度活动最多保存 30 条，前端最多展示最近 5 条。
- 评论只上报数量，不上报评论文本。
- 所有底层异常必须转换为稳定错误代码和安全中文提示，禁止持久化原始异常文本。
- 后端仓库为 `/Users/zhouzheng/Documents/code/fanxin/starx-backend`；前端仓库为 `/Users/zhouzheng/Documents/code/fanxin/starx-frontend`，分别提交。

## 文件结构

### 后端新增

- `app/services/mediaspider/error_classifier.py`：将底层异常转换为稳定、安全的平台失败信息。
- `app/services/mediaspider/runtime/auth.py`：Cookie 登录态失败时阻止进入交互式登录流程。
- `app/services/account_report/crawl_progress.py`：聚合活动、平台摘要和 workflow 持久化。
- `tests/test_xhs_playwright_sign.py`：小红书签名兼容回归测试。
- `tests/test_mediaspider_error_classifier.py`：错误分类与登录降级测试。
- `tests/test_account_report_crawl_progress.py`：快照边界、脱敏和合并测试。

### 后端修改

- `app/services/mediaspider/models.py`：增加进度事件、失败模型和认证异常。
- `app/services/mediaspider/service.py`：公开方法接收可选进度回调。
- `app/services/mediaspider/runtime/collector.py`：内容、博主和评论计数事件。
- `app/services/mediaspider/runtime/runner.py`：锁等待、开始、完成、失败事件和安全错误包装。
- `app/services/mediaspider/platforms/xhs/playwright_sign.py`：兼容新旧 `xhshow` 方法签名。
- `app/services/mediaspider/platforms/{xhs,douyin,kuaishou}/core.py`：Cookie 登录态失效时直接抛出认证错误。
- `app/services/account_report/workflow.py`：接入 Tracker、平台级错误和可操作最终错误。
- `tests/test_mediaspider_service.py`、`tests/test_mediaspider_runtime.py`：回调透传和安全事件测试。
- `tests/test_account_report_workflow.py`：进度集成、部分成功和全部失败测试。

### 前端新增

- `src/pages/account-report/AccountReportWorkflowProgress.jsx`：账号报告采集进度组件。

### 前端修改

- `src/utils/accountReport.js`：归一化 `crawlProgress`，兼容旧 workflow。
- `src/utils/accountReport.test.js`：进度纯函数测试。
- `src/pages/AccountReport.jsx`：接入独立进度组件并展示真实失败信息。
- `src/pages/AccountReport.preview.test.js`：组件接线与样式契约测试。
- `src/styles/pages.css`：活动列表、平台摘要和移动端样式。

---

### Task 1：修复小红书 `xhshow` 签名兼容

**文件：**
- 新建：`tests/test_xhs_playwright_sign.py`
- 修改：`app/services/mediaspider/platforms/xhs/playwright_sign.py`

**接口：**
- 输入：`CryptoProcessor.build_payload_array` 的旧版或含 `hex_md5_path` 的新版签名。
- 输出：`_patch_xhshow_a3_hash()` 幂等补丁；`sign_with_xhshow()` 的公开接口保持不变。

- [ ] **步骤 1：编写当前依赖调用约定的失败测试**

```python
import inspect

from app.services.mediaspider.platforms.xhs.playwright_sign import sign_with_xhshow
from xhshow.core.crypto import CryptoProcessor


def test_xhshow_010_post_signature_does_not_duplicate_sign_state():
    assert "hex_md5_path" in inspect.signature(CryptoProcessor.build_payload_array).parameters

    headers = sign_with_xhshow(
        "/api/sns/web/v1/search/notes",
        {"keyword": "探店", "page": 1},
        "a1=1234567890abcdef1234567890abcdef1234567890abcdef1234",
        method="POST",
    )

    assert {"x-s", "x-t", "x-s-common", "x-b3-traceid"} <= set(headers)
    assert headers["x-s"]


def test_xhshow_patch_is_idempotent():
    from app.services.mediaspider.platforms.xhs import playwright_sign

    before = CryptoProcessor.build_payload_array
    playwright_sign._patch_xhshow_a3_hash()
    assert CryptoProcessor.build_payload_array is before
```

- [ ] **步骤 2：运行测试并确认失败原因正确**

运行：

```bash
conda run -n starx pytest tests/test_xhs_playwright_sign.py -q
```

预期：第一个测试以 `got multiple values for argument 'sign_state'` 失败，幂等测试也失败。

- [ ] **步骤 3：实现新旧签名适配和幂等补丁**

在 `playwright_sign.py` 中把固定签名 wrapper 改为按参数表选择 wrapper。实现必须：

```python
def _repair_get_a3(payload, processor, string_param: str):
    if "{" in string_param:
        return payload
    correct_md5_hex = hashlib.md5(string_param.encode("utf-8")).hexdigest()
    correct_md5_bytes = [int(correct_md5_hex[index:index + 2], 16) for index in range(0, 32, 2)]
    seed_byte = payload[4]
    ts_bytes = payload[8:16]
    correct_a3_hash = processor._custom_hash_v2(list(ts_bytes) + correct_md5_bytes)
    for index in range(16):
        payload[128 + index] = correct_a3_hash[index] ^ seed_byte
    return payload


def _patch_xhshow_a3_hash():
    from xhshow.core.crypto import CryptoProcessor

    current = CryptoProcessor.build_payload_array
    if getattr(current, "__starx_xhshow_a3_patch__", False):
        return
    parameters = inspect.signature(current).parameters

    if "hex_md5_path" in parameters:
        def patched(self, hex_parameter, hex_md5_path, a1_value,
                    app_identifier="xhs-pc-web", string_param="",
                    timestamp=None, sign_state=None):
            payload = current(
                self, hex_parameter, hex_md5_path, a1_value,
                app_identifier, string_param, timestamp, sign_state,
            )
            return _repair_get_a3(payload, self, string_param)
    else:
        def patched(self, hex_parameter, a1_value,
                    app_identifier="xhs-pc-web", string_param="",
                    timestamp=None, sign_state=None):
            payload = current(
                self, hex_parameter, a1_value,
                app_identifier, string_param, timestamp, sign_state,
            )
            return _repair_get_a3(payload, self, string_param)

    patched.__starx_xhshow_a3_patch__ = True
    CryptoProcessor.build_payload_array = patched
```

同时新增 `import inspect`。未知签名不静默猜测；缺少 `a1_value` 或 `string_param` 时抛出 `RuntimeError("不支持的 xhshow build_payload_array 签名")`。

- [ ] **步骤 4：运行回归测试与 MediaSpider 现有测试**

```bash
conda run -n starx pytest tests/test_xhs_playwright_sign.py tests/test_mediaspider_runtime.py tests/test_mediaspider_platform_runtime.py -q
```

预期：全部通过，不再出现重复 `sign_state`。

- [ ] **步骤 5：提交后端修复**

```bash
git add app/services/mediaspider/platforms/xhs/playwright_sign.py tests/test_xhs_playwright_sign.py
git diff --cached --check
git commit -m "fix: support current xhshow signatures"
```

---

### Task 2：增加 MediaSpider 安全进度事件

**文件：**
- 修改：`app/services/mediaspider/models.py`
- 修改：`app/services/mediaspider/service.py`
- 修改：`app/services/mediaspider/runtime/collector.py`
- 修改：`app/services/mediaspider/runtime/runner.py`
- 修改：`tests/test_mediaspider_service.py`
- 修改：`tests/test_mediaspider_runtime.py`

**接口：**
- 生成：`CrawlerProgressEvent`、`ProgressCallback`。
- 修改：`crawl_by_keyword(*, keywords: str | Sequence[str], platform: str, on_progress: ProgressCallback | None = None, **runtime_options) -> CrawlResult`。
- 修改：`crawl_by_creator(*, creator_url: str, on_progress: ProgressCallback | None = None, **runtime_options) -> CrawlResult`。
- 修改：`run_crawler(config, *, on_progress=None, factory=CrawlerFactory)`。

- [ ] **步骤 1：编写回调透传和事件安全性的失败测试**

在 `tests/test_mediaspider_service.py` 增加：

```python
def test_service_passes_progress_callback_to_runner():
    events = []

    async def runner(config, on_progress=None):
        await on_progress(CrawlerProgressEvent(
            platform=config.platform,
            crawlType=config.crawl_type,
            action="run_started",
            status="running",
            message="开始采集小红书",
        ))
        return CrawlResult(platform=config.platform, crawl_type=config.crawl_type)

    async def execute():
        await MediaCrawlerService(runner=runner).crawl_by_keyword(
            keywords=["探店"], platform="xhs", cookies="cookie=value",
            on_progress=lambda event: events.append(event),
        )

    asyncio.run(execute())
    assert [event.action for event in events] == ["run_started"]
```

在 `tests/test_mediaspider_runtime.py` 增加：

```python
def test_runner_emits_safe_bounded_record_events_without_comment_text():
    events = []

    async def collect(event):
        events.append(event.model_dump(mode="json", by_alias=True))

    async def execute():
        await run_crawler(make_config(), on_progress=collect, factory=FakeFactory(FakeCrawler()))

    asyncio.run(execute())
    serialized = json.dumps(events, ensure_ascii=False)
    assert [item["action"] for item in events][0] == "waiting_for_slot"
    assert "content_discovered" in [item["action"] for item in events]
    assert "cookie=value" not in serialized
    assert "commentText" not in serialized
```

- [ ] **步骤 2：运行测试并确认因接口缺失而失败**

```bash
conda run -n starx pytest tests/test_mediaspider_service.py tests/test_mediaspider_runtime.py -q
```

预期：`CrawlerProgressEvent` 或 `on_progress` 不存在导致失败。

- [ ] **步骤 3：增加白名单事件模型和回调类型**

在 `models.py` 增加：

```python
from collections.abc import Awaitable, Callable


class CrawlerProgressEvent(BaseModel):
    platform: str
    crawl_type: Literal["search", "creator"] = Field(alias="crawlType")
    action: Literal[
        "waiting_for_slot", "run_started", "keyword_started",
        "creator_started", "content_discovered", "creator_discovered",
        "comments_updated", "run_completed", "run_failed",
    ]
    status: Literal["pending", "running", "completed", "failed"]
    message: str
    subject: str = ""
    content_title: str = Field(default="", alias="contentTitle", max_length=60)
    content_count: int = Field(default=0, alias="contentCount", ge=0)
    creator_count: int = Field(default=0, alias="creatorCount", ge=0)
    comment_count: int = Field(default=0, alias="commentCount", ge=0)


ProgressCallback = Callable[[CrawlerProgressEvent], Awaitable[None] | None]
```

模型只允许上述字段；禁止增加 Cookie、URL、原始 ID 或评论文本。

- [ ] **步骤 4：让 Collector 生成去重后的内容、博主和评论计数事件**

修改 `_OrderedRecords.upsert()` 返回是否新增；`MemoryStore` 在写入后调用 Collector 的异步 `emit_record_event()`：

```python
async def emit_record_event(self, kind: str, item: dict[str, Any], inserted: bool) -> None:
    if not inserted or self.on_progress is None:
        return
    result = self.to_result()
    action = {
        "content": "content_discovered",
        "creator": "creator_discovered",
        "comment": "comments_updated",
    }[kind]
    event = CrawlerProgressEvent(
        platform=self.platform,
        crawlType=self.crawl_type,
        action=action,
        status="running",
        message={
            "content": "发现公开内容",
            "creator": "发现公开博主",
            "comment": "更新评论计数",
        }[kind],
        subject=_safe_subject(item) if kind == "creator" else "",
        contentTitle=_safe_title(item) if kind == "content" else "",
        contentCount=result.content_count,
        creatorCount=result.creator_count,
        commentCount=result.comment_count,
    )
    await _call_progress(self.on_progress, event)
```

`_safe_title()` 只读取 `title`、`desc`、`caption`，移除 URL、联系方式和凭证形态文本后截断 60 字；`_safe_subject()` 只读取已经脱敏的 `nickname` 或 `name`。评论事件只包含计数。

- [ ] **步骤 5：让 runner 与 service 发出生命周期事件并吞掉回调异常**

runner 在获取锁前发 `waiting_for_slot`，进入锁后发 `run_started` 和模式开始事件，成功后发 `run_completed`，失败包装前发 `run_failed`。统一调用：

```python
async def emit_progress(callback, event):
    if callback is None:
        return
    try:
        result = callback(event)
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.warning(
            "mediaspider progress callback failed platform=%s action=%s",
            event.platform,
            event.action,
        )
```

日志只记录平台和动作。`MediaCrawlerService` 把 `on_progress` 作为 runner 的第二个参数传递，绝不放进 `CrawlerRunConfig`。

- [ ] **步骤 6：运行测试并提交**

```bash
conda run -n starx pytest tests/test_mediaspider_service.py tests/test_mediaspider_runtime.py tests/test_mediaspider_safe_logging.py -q
git add app/services/mediaspider/models.py app/services/mediaspider/service.py app/services/mediaspider/runtime/collector.py app/services/mediaspider/runtime/runner.py tests/test_mediaspider_service.py tests/test_mediaspider_runtime.py
git diff --cached --check
git commit -m "feat: emit safe mediaspider progress events"
```

预期：测试通过，安全日志测试未发现 Cookie 或动态原始异常输出。

---

### Task 3：阻止 Cookie 失效后进入交互登录并分类平台错误

**文件：**
- 新建：`app/services/mediaspider/runtime/auth.py`
- 新建：`app/services/mediaspider/error_classifier.py`
- 新建：`tests/test_mediaspider_error_classifier.py`
- 修改：`app/services/mediaspider/models.py`
- 修改：`app/services/mediaspider/runtime/runner.py`
- 修改：`app/services/mediaspider/platforms/xhs/core.py`
- 修改：`app/services/mediaspider/platforms/douyin/core.py`
- 修改：`app/services/mediaspider/platforms/kuaishou/core.py`

**接口：**
- 生成：`CrawlerAuthenticationError(platform)`。
- 生成：`CrawlerFailure(code, message, suggestion)`。
- 生成：`raise_for_cookie_auth_failure(platform, login_type)`。
- 生成：`classify_crawler_error(platform, cause)`。
- 修改：`CrawlerExecutionError.failure`。

- [ ] **步骤 1：编写认证与错误分类失败测试**

```python
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.services.mediaspider.error_classifier import classify_crawler_error
from app.services.mediaspider.models import CrawlerAuthenticationError
from app.services.mediaspider.runtime.auth import raise_for_cookie_auth_failure


def test_cookie_auth_failure_stops_before_interactive_login():
    with pytest.raises(CrawlerAuthenticationError):
        raise_for_cookie_auth_failure("dy", "cookie")
    assert raise_for_cookie_auth_failure("dy", "qrcode") is None


def test_authentication_error_is_actionable_but_safe():
    failure = classify_crawler_error(
        "dy", CrawlerAuthenticationError("dy", "session=must-not-leak")
    )
    assert failure.code == "credentials_expired"
    assert failure.message == "登录凭证失效或未生效"
    assert "must-not-leak" not in failure.model_dump_json()


def test_plain_playwright_timeout_remains_browser_timeout():
    failure = classify_crawler_error("xhs", PlaywrightTimeoutError("locator timeout"))
    assert failure.code == "browser_timeout"


def test_known_signature_type_error_is_runtime_incompatible():
    failure = classify_crawler_error(
        "xhs", TypeError("build_payload_array got multiple values for argument 'sign_state'")
    )
    assert failure.code == "runtime_incompatible"
```

- [ ] **步骤 2：运行测试确认模块不存在**

```bash
conda run -n starx pytest tests/test_mediaspider_error_classifier.py -q
```

预期：导入新模块失败。

- [ ] **步骤 3：实现稳定失败模型和分类器**

```python
class CrawlerFailure(BaseModel):
    code: Literal[
        "credentials_missing", "credentials_expired", "creator_url_invalid",
        "platform_blocked", "browser_timeout", "runtime_incompatible", "crawler_failed",
    ]
    message: str
    suggestion: str


class CrawlerAuthenticationError(CrawlerServiceError):
    def __init__(self, platform: str, _unsafe_detail: str = ""):
        super().__init__(f"平台 {platform} 登录凭证失效")
        self.platform = platform
```

`classify_crawler_error()` 只检查明确异常类和上述已知签名冲突片段，返回固定文案；默认返回 `crawler_failed`。`CrawlerExecutionError` 保存 `failure` 和 `cause_type`，仍不保存 cause 或 cause 文本。

- [ ] **步骤 4：修改三平台登录分支**

在每个平台 `pong()` 返回 false 后、构造 Login 对象前执行：

```python
raise_for_cookie_auth_failure("dy", config.LOGIN_TYPE)
```

小红书传 `xhs`，快手传 `ks`。Cookie 模式直接失败；二维码或手机模式保留原上游交互登录逻辑。

- [ ] **步骤 5：runner 使用安全分类结果包装异常**

```python
except Exception as exc:
    failure = classify_crawler_error(run_config.platform, exc)
    primary_error = CrawlerExecutionError(
        run_config.platform,
        exc,
        collector.to_result(),
        failure=failure,
    )
    await emit_progress(on_progress, failed_event(run_config, failure))
    raise primary_error from None
```

失败事件只放 `failure.message`，不放 `str(exc)`。

- [ ] **步骤 6：运行平台与安全测试并提交**

```bash
conda run -n starx pytest tests/test_mediaspider_error_classifier.py tests/test_mediaspider_platform_runtime.py tests/test_mediaspider_runtime.py tests/test_mediaspider_safe_logging.py -q
git add app/services/mediaspider/models.py app/services/mediaspider/error_classifier.py app/services/mediaspider/runtime/auth.py app/services/mediaspider/runtime/runner.py app/services/mediaspider/platforms/xhs/core.py app/services/mediaspider/platforms/douyin/core.py app/services/mediaspider/platforms/kuaishou/core.py tests/test_mediaspider_error_classifier.py
git diff --cached --check
git commit -m "fix: classify crawler authentication failures"
```

---

### Task 4：聚合并持久化账号报告采集进度

**文件：**
- 新建：`app/services/account_report/crawl_progress.py`
- 新建：`tests/test_account_report_crawl_progress.py`
- 修改：`app/services/account_report/workflow.py`
- 修改：`tests/test_account_report_workflow.py`

**接口：**
- 生成：`CrawlTarget(platform_name: str, platform_code: str)`。
- 生成：`AccountReportCrawlProgressTracker(workflow_id: str, store: WorkflowStore, targets: list[CrawlTarget])`。
- 生成：`tracker.callback(platform_name: str, mode: str) -> ProgressCallback`。
- 生成：`tracker.fail(platform_code: str, *, mode: str, failure: CrawlerFailure) -> None`。
- 生成：`tracker.complete(platform_code: str, *, content_count: int, creator_count: int, comment_count: int) -> None`。
- 生成：`tracker.failure_summary() -> str`。

- [ ] **步骤 1：编写快照边界和脱敏失败测试**

```python
def test_tracker_keeps_last_thirty_events_and_never_persists_credentials():
    store = FakeProgressStore()
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("小红书", "xhs")]
    )

    for index in range(35):
        asyncio.run(tracker.record(CrawlerProgressEvent(
            platform="xhs",
            crawlType="search",
            action="content_discovered",
            status="running",
            message="发现公开内容",
            contentTitle=f"内容 {index} cookie=secret",
            contentCount=index + 1,
        )))

    snapshot = store.payloads[-1]["crawlProgress"]
    assert len(snapshot["activities"]) == 30
    assert snapshot["activities"][-1]["sequence"] == 35
    assert "secret" not in json.dumps(snapshot, ensure_ascii=False).lower()


def test_tracker_merges_platform_failure_and_preserves_existing_result_payload():
    store = FakeProgressStore(existing={"reportVersion": 2})
    tracker = AccountReportCrawlProgressTracker(
        "wf-1", store, [CrawlTarget("抖音", "dy")]
    )
    tracker.fail(
        "dy", mode="keyword",
        failure=CrawlerFailure(
            code="credentials_expired",
            message="登录凭证失效或未生效",
            suggestion="更新该平台 Cookie 并重启服务",
        ),
    )
    assert store.merged["reportVersion"] == 2
    assert store.merged["crawlProgress"]["platformSummaries"][0]["failureCode"] == "credentials_expired"
```

- [ ] **步骤 2：运行测试确认 Tracker 不存在**

```bash
conda run -n starx pytest tests/test_account_report_crawl_progress.py -q
```

预期：导入 `crawl_progress` 失败。

- [ ] **步骤 3：实现独立 Tracker**

Tracker 内部维护 `sequence`、最多 30 条活动和每平台摘要。每次变更调用：

```python
self.store.update_progress(
    self.workflow_id,
    progress=self.progress,
    current_stage=self.current_stage,
    result_payload={"crawlProgress": self.snapshot()},
)
```

连续相同 `platform + action + status + subject` 事件更新最后一项计数，不追加。标题和主体再次经过凭证、URL、手机号、邮箱和联系方式清洗；活动时间使用 UTC ISO 8601。

- [ ] **步骤 4：编写 workflow 集成失败测试**

修改 `StubStore.update_progress()` 保存 `result_payload`，StubCrawler 接收并调用 `on_progress`。增加：

```python
def test_workflow_persists_platform_progress_and_actionable_failures():
    store = StubStore(platforms=["小红书", "抖音"])
    crawler = ClassifiedCrawler(
        failures={
            ("keyword", "dy"): CrawlerFailure(
                code="credentials_expired",
                message="登录凭证失效或未生效",
                suggestion="更新抖音 Cookie 并重启服务",
            )
        }
    )

    asyncio.run(_execute(store=store, crawler=crawler, ai=StubAI()))

    snapshot = store.result_payloads[-1]["crawlProgress"]
    douyin = next(item for item in snapshot["platformSummaries"] if item["platform"] == "dy")
    assert douyin["status"] == "partial"
    assert douyin["failureCode"] == "credentials_expired"
    assert any(item["contentTitle"] == "样本" for item in snapshot["activities"])


def test_all_failed_error_lists_safe_platform_reasons():
    store = StubStore()
    crawler = ClassifiedCrawler(fail_all=True)

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(_execute(store=store, crawler=crawler, ai=StubAI()))

    message = str(exc_info.value)
    assert "小红书：登录凭证失效或未生效" in message
    assert "抖音：登录凭证失效或未生效" in message
    assert "Cookie" not in message
```

- [ ] **步骤 5：接入 workflow 的博主与关键词阶段**

实现规则：

1. 初始化 Tracker 后立即持久化三个支持平台的摘要。
2. 缺失 Cookie：`credentials_missing`。
3. 主页域名或正式路径不匹配：`creator_url_invalid`，关键词采集继续。
4. 博主采集返回内容数和博主数都为零：标记 `creator_url_invalid`，不把该次计入成功采集。
5. 捕获 `CrawlerExecutionError` 时使用 `exc.failure`；其他异常统一使用 `crawler_failed`。
6. 关键词采集成功即使返回零条内容，也表明平台访问成功，可计入 `successful_crawls`，摘要显示完成且计数为零。
7. 同一平台一个步骤成功、另一步失败时状态为 `partial`。
8. 所有采集失败时使用 `tracker.failure_summary()` 生成安全最终错误。
9. `sourceMeta.failedPlatforms` 继续使用安全中文原因，保持报告接口兼容。

调用示例：

```python
creator_result = await crawler.crawl_by_creator(
    creator_url=plan.creator_url,
    on_progress=tracker.callback(plan.platform_name, "creator"),
    **runtime_options,
)
```

- [ ] **步骤 6：运行账号报告测试并提交**

```bash
conda run -n starx pytest tests/test_account_report_crawl_progress.py tests/test_account_report_workflow.py tests/test_account_report_api.py -q
git add app/services/account_report/crawl_progress.py app/services/account_report/workflow.py tests/test_account_report_crawl_progress.py tests/test_account_report_workflow.py
git diff --cached --check
git commit -m "feat: persist account report crawl progress"
```

---

### Task 5：在账号报告页展示采集活动和平台摘要

**文件：**
- 新建：`src/pages/account-report/AccountReportWorkflowProgress.jsx`
- 修改：`src/utils/accountReport.js`
- 修改：`src/utils/accountReport.test.js`
- 修改：`src/pages/AccountReport.jsx`
- 修改：`src/pages/AccountReport.preview.test.js`
- 修改：`src/styles/pages.css`

**接口：**
- 生成：`normalizeCrawlProgress(workflow)`。
- 生成：`AccountReportWorkflowProgress({ workflow, reportView })`。

- [ ] **步骤 1：编写前端归一化失败测试**

```javascript
test("crawl progress normalization is bounded and backward compatible", () => {
  assert.deepEqual(normalizeCrawlProgress({ resultPayload: {} }), {
    current: null,
    activities: [],
    platformSummaries: [],
  });

  const workflow = {
    resultPayload: {
      crawlProgress: {
        current: { message: "正在搜索", platformName: "小红书" },
        activities: Array.from({ length: 8 }, (_, index) => ({
          sequence: index + 1,
          message: `活动 ${index + 1}`,
          contentTitle: "x".repeat(80),
        })),
        platformSummaries: [{
          platform: "dy",
          platformName: "抖音",
          status: "failed",
          failureCode: "credentials_expired",
          failureMessage: "登录凭证失效或未生效",
          suggestion: "更新抖音 Cookie 并重启服务",
        }],
      },
    },
  };

  const result = normalizeCrawlProgress(workflow);
  assert.equal(result.activities.length, 5);
  assert.equal(result.activities[0].message, "活动 8");
  assert.equal(result.activities[0].contentTitle.length, 60);
  assert.equal(result.platformSummaries[0].failureCode, "credentials_expired");
});
```

- [ ] **步骤 2：运行测试确认函数不存在**

```bash
npm test -- src/utils/accountReport.test.js
```

预期：`normalizeCrawlProgress` 未导出导致失败。

- [ ] **步骤 3：实现纯函数归一化**

`normalizeCrawlProgress()` 只接受对象和白名单字段，活动按 sequence 倒序并截取 5 条；标题截断 60 字；无新字段时返回空集合。将结果加入 `createAccountReportViewModel()` 的 `crawlProgress` 字段。

```javascript
export function normalizeCrawlProgress(workflow) {
  const raw = workflow?.resultPayload?.crawlProgress;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { current: null, activities: [], platformSummaries: [] };
  }
  const activities = asArray(raw.activities)
    .filter((item) => item && typeof item === "object")
    .sort((left, right) => Number(right.sequence || 0) - Number(left.sequence || 0))
    .slice(0, 5)
    .map((item) => ({ ...item, contentTitle: String(item.contentTitle || "").slice(0, 60) }));
  return {
    current: raw.current && typeof raw.current === "object" ? raw.current : null,
    activities,
    platformSummaries: asArray(raw.platformSummaries).filter(
      (item) => item && typeof item === "object"
    ),
  };
}
```

- [ ] **步骤 4：编写组件接线失败测试**

在 `AccountReport.preview.test.js` 增加源码契约断言：

```javascript
test("account report renders current crawl activity and platform diagnostics", () => {
  const progressSource = readFileSync(
    new URL("./account-report/AccountReportWorkflowProgress.jsx", import.meta.url),
    "utf8"
  );
  assert.match(source, /AccountReportWorkflowProgress/);
  assert.match(progressSource, /crawlProgress\.current/);
  assert.match(progressSource, /platformSummaries/);
  assert.match(progressSource, /failureMessage/);
  assert.match(styles, /\.report-crawl-activities/);
  assert.match(styles, /\.report-platform-summary/);
});
```

- [ ] **步骤 5：实现独立进度组件并接入报告页**

组件渲染：

```jsx
export default function AccountReportWorkflowProgress({ workflow, reportView }) {
  if (!workflow) return null;
  const { crawlProgress, isActive, isFailed, progress, stageLabel } = reportView;
  const currentMessage = crawlProgress.current?.message;
  return (
    <section className={`report-workflow-status ${isFailed ? "failed" : isActive ? "active" : "completed"}`} aria-live="polite">
      <div className="report-workflow-main">
        <div className="report-workflow-copy">
          <b>{isFailed ? "生成失败" : stageLabel}</b>
          <span>{currentMessage || (isActive ? `正在更新报告 · ${progress}%` : workflow.error || "报告已生成")}</span>
        </div>
        <div className="report-progress" aria-label={`报告生成进度 ${progress}%`}><i style={{ width: `${progress}%` }} /></div>
      </div>
      {crawlProgress.activities.length > 0 ? <ActivityList items={crawlProgress.activities} /> : null}
      {crawlProgress.platformSummaries.length > 0 ? <PlatformSummaries items={crawlProgress.platformSummaries} /> : null}
      {isFailed && workflow.error ? <p className="report-workflow-error">{workflow.error}</p> : null}
    </section>
  );
}
```

`AccountReport.jsx` 删除旧的内联状态 section，改用该组件。失败时不再把 `workflow.error` 替换成统一文案。

- [ ] **步骤 6：补充响应式样式**

将 `.report-workflow-status` 改为单列容器；新增 `.report-workflow-main` 的原两列布局、活动时间线、平台徽标、失败/部分成功状态色和移动端单列平台卡片。不得使用内联动态 HTML或 `dangerouslySetInnerHTML`。

- [ ] **步骤 7：运行前端测试、构建并提交**

```bash
npm test
npm run build
git add src/utils/accountReport.js src/utils/accountReport.test.js src/pages/AccountReport.jsx src/pages/AccountReport.preview.test.js src/pages/account-report/AccountReportWorkflowProgress.jsx src/styles/pages.css
git diff --cached --check
git commit -m "feat: show account report crawl progress"
```

预期：全部 Node 测试通过，Vite 构建成功。

---

### Task 6：全量验证与安全实测

**文件：**
- 不新增生产文件。
- 如全量测试揭示回归，只修改引起回归的任务内文件并补对应测试。

**接口：**
- 消费前五个任务的最终实现。
- 产出可复核的全量测试与真实最小探测证据。

- [ ] **步骤 1：运行后端全量测试**

```bash
conda run -n starx pytest -q
```

预期：全部通过；不得出现 Cookie、Authorization 或 session 值。

- [ ] **步骤 2：运行前端全量测试和生产构建**

```bash
npm test
npm run build
```

工作目录：`/Users/zhouzheng/Documents/code/fanxin/starx-frontend`。

预期：全部测试通过，Vite 生产构建成功。

- [ ] **步骤 3：执行小红书最小真实探测**

仅输出平台、成功状态、计数或稳定错误代码，不输出 Cookie：

```bash
conda run -n starx python -c "exec('import asyncio,json\nfrom app.core.config import settings\nfrom app.services.mediaspider.models import CrawlerExecutionError\nfrom app.services.mediaspider.service import MediaCrawlerService\nasync def main():\n    opts=settings.mediaspider_runtime_options(\"xhs\")\n    opts.update({\"max_notes_count\":1,\"enable_comments\":False,\"enable_sub_comments\":False})\n    try:\n        result=await MediaCrawlerService().crawl_by_keyword(keywords=[\"探店\"],platform=\"xhs\",**opts)\n        print(json.dumps({\"platform\":\"xhs\",\"ok\":True,\"contents\":result.content_count},ensure_ascii=False))\n    except CrawlerExecutionError as exc:\n        print(json.dumps({\"platform\":\"xhs\",\"ok\":False,\"failureCode\":exc.failure.code},ensure_ascii=False))\nasyncio.run(main())')"
```

预期：不再出现 `got multiple values for argument 'sign_state'`。若 Cookie 或平台验证导致失败，只允许输出稳定 `failureCode`。

- [ ] **步骤 4：检查工作区与敏感信息**

```bash
git -C /Users/zhouzheng/Documents/code/fanxin/starx-backend status --short
git -C /Users/zhouzheng/Documents/code/fanxin/starx-frontend status --short
rg -n "cookie=value|must-not-leak|super-secret" app --glob '*.py'
rg -n "cookie=value|must-not-leak|super-secret" src --glob '!*.test.*'
```

前两条命令在各自仓库执行；第三条在后端仓库执行，第四条在前端仓库执行。预期：两个仓库只有计划内变更或完全干净；生产文件不包含测试凭证字面量。

- [ ] **步骤 5：确认验证未产生未提交改动**

若步骤 1–4 暴露回归，停止本任务并返回造成回归的任务，先补失败测试、完成 Red-Green-Refactor、使用该任务列出的精确文件清单提交，再从步骤 1 重新执行全量验证。最终两个仓库的 `git status --short` 均应为空。
