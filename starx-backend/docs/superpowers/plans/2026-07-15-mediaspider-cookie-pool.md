# MediaSpider Cookie 池实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MediaSpider 平台 Cookie 从 `.env` 单值配置迁移为 workflow 启动时读取 `cookies/cookies.json` 的轮询池，并在认证失效时自动切换下一条 Cookie。

**Architecture:** 新增独立的 `cookie_pool.py` 负责磁盘加载、严格校验、调用入口局部快照、无敏感信息的进程级轮询游标及统一认证重试。账号报告 workflow 和直接爬取脚本各自在入口开始时加载一次快照；`Settings` 继续提供不含 Cookie 的浏览器和爬取参数。

**Tech Stack:** Python 3、Pydantic Settings、asyncio、pytest；所有后端 Python 命令使用 `starx` conda 环境。

## 全局约束

- 设计与实现说明使用中文。
- Cookie 唯一来源为 `starx-backend/cookies/cookies.json`，不再从 `.env` 读取。
- JSON 每个账号报告 workflow 启动时读取一次，不得将 Cookie 内容保存在模块级缓存、全局 Settings、日志、异常或持久化数据中。
- 进程级状态只允许保存每个平台的整数轮询游标。
- 只有 `credentials_expired` 触发换 Cookie；单次爬取每条 Cookie 最多尝试一次。
- 用户现有的 `cookies/cookies.json` 不得提交到 Git。
- `scripts/media_spider.py` 不得硬编码 Cookie，必须复用通用池轮换执行器。
- 后端 Python 环境必须使用名为 `starx` 的 conda 环境。

---

### Task 1: Cookie 池加载、校验与轮询

**Files:**
- Create: `app/services/mediaspider/cookie_pool.py`
- Create: `tests/test_mediaspider_cookie_pool.py`

**Interfaces:**
- Produces: `CookiePoolConfigurationError`
- Produces: `RoundRobinCursor.candidates(platform: str, cookies: tuple[str, ...]) -> tuple[str, ...]`
- Produces: `WorkflowCookiePool.has_cookies(platform: str) -> bool`
- Produces: `WorkflowCookiePool.candidates(platform: str) -> tuple[str, ...]`
- Produces: `load_cookie_pool(path: Path = COOKIE_POOL_PATH, cursor: RoundRobinCursor = PROCESS_COOKIE_CURSOR) -> WorkflowCookiePool`

- [ ] **Step 1: 编写加载、校验、重新读取和安全异常的失败测试**

```python
import json

import pytest

from app.services.mediaspider.cookie_pool import (
    CookiePoolConfigurationError,
    RoundRobinCursor,
    load_cookie_pool,
)


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_loads_platform_lists_filters_blanks_and_deduplicates(tmp_path):
    path = tmp_path / "cookies.json"
    _write(path, {"xhs": [" first ", "", "first", "second"], "dy": ["dy"], "ks": []})
    pool = load_cookie_pool(path, cursor=RoundRobinCursor())
    assert pool.candidates("xhs") == ("first", "second")
    assert pool.candidates("dy") == ("dy",)
    assert pool.has_cookies("ks") is False


def test_each_load_reads_current_file_contents(tmp_path):
    path = tmp_path / "cookies.json"
    _write(path, {"xhs": ["old"]})
    first = load_cookie_pool(path, cursor=RoundRobinCursor())
    _write(path, {"xhs": ["new"]})
    second = load_cookie_pool(path, cursor=RoundRobinCursor())
    assert first.candidates("xhs") == ("old",)
    assert second.candidates("xhs") == ("new",)


@pytest.mark.parametrize(
    "value",
    [[], {"xhs": "bad"}, {"xhs": [123]}, {"weibo": ["unexpected"]}],
)
def test_invalid_shapes_fail_without_leaking_values(tmp_path, value):
    path = tmp_path / "cookies.json"
    _write(path, value)
    with pytest.raises(CookiePoolConfigurationError) as exc_info:
        load_cookie_pool(path)
    assert "123" not in str(exc_info.value)
    assert "bad" not in str(exc_info.value)
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `conda run -n starx pytest tests/test_mediaspider_cookie_pool.py -q`

Expected: FAIL，提示 `app.services.mediaspider.cookie_pool` 不存在。

- [ ] **Step 3: 实现最小 Cookie 池模块**

```python
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from app.core.config import BASE_DIR

PLATFORMS = ("xhs", "dy", "ks")
COOKIE_POOL_PATH = BASE_DIR / "cookies" / "cookies.json"


class CookiePoolConfigurationError(Exception):
    def __init__(self):
        super().__init__("Cookie 池配置不可用")


class RoundRobinCursor:
    def __init__(self):
        self._next_by_platform: dict[str, int] = {}
        self._lock = Lock()

    def candidates(self, platform: str, cookies: tuple[str, ...]) -> tuple[str, ...]:
        if not cookies:
            return ()
        with self._lock:
            start = self._next_by_platform.get(platform, 0) % len(cookies)
            self._next_by_platform[platform] = (start + 1) % len(cookies)
        return cookies[start:] + cookies[:start]


PROCESS_COOKIE_CURSOR = RoundRobinCursor()


class WorkflowCookiePool:
    __slots__ = ("_cookies", "_cursor")

    def __init__(self, cookies: dict[str, tuple[str, ...]], cursor: RoundRobinCursor):
        self._cookies = cookies
        self._cursor = cursor

    def __repr__(self) -> str:
        return "WorkflowCookiePool(<redacted>)"

    def has_cookies(self, platform: str) -> bool:
        return bool(self._platform_cookies(platform))

    def candidates(self, platform: str) -> tuple[str, ...]:
        return self._cursor.candidates(platform, self._platform_cookies(platform))

    def _platform_cookies(self, platform: str) -> tuple[str, ...]:
        if platform not in PLATFORMS:
            raise ValueError(f"unsupported MediaSpider platform: {platform}")
        return self._cookies[platform]


def load_cookie_pool(
    path: Path = COOKIE_POOL_PATH,
    *,
    cursor: RoundRobinCursor = PROCESS_COOKIE_CURSOR,
) -> WorkflowCookiePool:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CookiePoolConfigurationError() from None
    if not isinstance(raw, dict):
        raise CookiePoolConfigurationError()
    if set(raw) - set(PLATFORMS):
        raise CookiePoolConfigurationError()
    parsed: dict[str, tuple[str, ...]] = {}
    for platform in PLATFORMS:
        values = raw.get(platform, [])
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise CookiePoolConfigurationError()
        parsed[platform] = tuple(dict.fromkeys(item.strip() for item in values if item.strip()))
    return WorkflowCookiePool(parsed, cursor)
```

- [ ] **Step 4: 增加轮询隔离与 repr 脱敏测试**

```python
def test_round_robin_is_platform_scoped(tmp_path):
    path = tmp_path / "cookies.json"
    _write(path, {"xhs": ["x1", "x2"], "dy": ["d1", "d2"], "ks": []})
    cursor = RoundRobinCursor()
    assert load_cookie_pool(path, cursor=cursor).candidates("xhs") == ("x1", "x2")
    assert load_cookie_pool(path, cursor=cursor).candidates("xhs") == ("x2", "x1")
    assert load_cookie_pool(path, cursor=cursor).candidates("dy") == ("d1", "d2")


def test_repr_never_contains_cookie(tmp_path):
    path = tmp_path / "cookies.json"
    _write(path, {"xhs": ["must-not-leak"]})
    assert "must-not-leak" not in repr(load_cookie_pool(path))
```

- [ ] **Step 5: 运行 Cookie 池测试并确认通过**

Run: `conda run -n starx pytest tests/test_mediaspider_cookie_pool.py -q`

Expected: PASS，0 failures。

- [ ] **Step 6: 提交 Cookie 池模块**

```bash
git add app/services/mediaspider/cookie_pool.py tests/test_mediaspider_cookie_pool.py
git commit -m "feat: add mediaspider cookie pool"
```

---

### Task 2: 从 Settings 和环境文档移除 Cookie

**Files:**
- Modify: `app/core/config.py`
- Modify: `tests/test_mediaspider_config.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `Settings.mediaspider_runtime_options(platform: str) -> dict[str, object]`，返回值不含 `cookies`。
- Consumes: Task 1 确立的 `cookies/cookies.json` 配置契约。

- [ ] **Step 1: 将 Settings 测试改为要求环境 Cookie 被忽略**

```python
def test_mediaspider_runtime_options_do_not_load_cookie_environment(monkeypatch):
    monkeypatch.setenv("STARX_MEDIASPIDER_XHS_COOKIES", "must-not-load")
    options = Settings(_env_file=None).mediaspider_runtime_options("xhs")
    assert "cookies" not in options
    assert "must-not-load" not in repr(options)
```

并将运行参数完整字典断言中的 `"cookies": ""` 删除。

- [ ] **Step 2: 运行 Settings 测试并确认旧实现导致失败**

Run: `conda run -n starx pytest tests/test_mediaspider_config.py -q`

Expected: FAIL，返回值仍包含 `cookies`。

- [ ] **Step 3: 删除 Settings Cookie 字段与映射**

从 `app/core/config.py` 删除 `SecretStr` 导入、`_MEDIASPIDER_COOKIE_FIELDS`、三个 `MEDIASPIDER_*_COOKIES` 字段，以及 `mediaspider_runtime_options()` 中的 Cookie 字段查找和返回项。保留显式平台白名单校验：

```python
_MEDIASPIDER_PLATFORMS = frozenset({"xhs", "dy", "ks"})

def mediaspider_runtime_options(self, platform: str) -> dict[str, object]:
    if platform not in _MEDIASPIDER_PLATFORMS:
        raise ValueError(f"unsupported MediaSpider platform: {platform}")
    return {
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

- [ ] **Step 4: 更新部署说明并忽略真实 Cookie 文件**

从 `.env.example` 删除三个 Cookie 变量。将 README 的 Cookie 小节改为：

```markdown
### 2.1 三个平台 Cookie 池

Cookie 不写入 `.env`。后端在每次账号报告 workflow 启动时读取 `cookies/cookies.json`：

```json
{"xhs":["cookie-a"],"dy":["cookie-b"],"ks":[]}
```

每个平台对应一个 Cookie 字符串数组。真实文件只保存在部署环境，不提交到 Git；认证失效时后端会轮询池内下一条 Cookie。
```

向 `.gitignore` 添加：

```gitignore
# Runtime crawler credentials
cookies/cookies.json
```

- [ ] **Step 5: 运行 Settings 测试和敏感配置搜索**

Run: `conda run -n starx pytest tests/test_mediaspider_config.py -q`

Expected: PASS，0 failures。

Run: `rg -n "STARX_MEDIASPIDER_(XHS|DOUYIN|KUAISHOU)_COOKIES|MEDIASPIDER_(XHS|DOUYIN|KUAISHOU)_COOKIES" app tests README.md .env.example`

Expected: 只允许出现“旧环境变量被忽略”的测试输入；生产代码和部署文档中无匹配。

- [ ] **Step 6: 提交 Settings 与文档迁移**

```bash
git add app/core/config.py tests/test_mediaspider_config.py .env.example README.md .gitignore
git commit -m "refactor: remove mediaspider cookie env settings"
```

---

### Task 3: 账号报告 workflow 接入 Cookie 池与认证轮换

**Files:**
- Modify: `app/services/account_report/workflow.py`
- Modify: `tests/test_account_report_workflow.py`

**Interfaces:**
- Consumes: `load_cookie_pool() -> WorkflowCookiePool`
- Consumes: `WorkflowCookiePool.has_cookies(platform)` 和 `WorkflowCookiePool.candidates(platform)`
- Produces: `_crawl_with_cookie_candidates(cookie_pool, platform, operation) -> CrawlResult`

- [ ] **Step 1: 调整测试桩，让每个 workflow 注入局部 Cookie 池加载器**

```python
class StubCookiePool:
    def __init__(self, cookies=None):
        self.cookies = (
            {"xhs": ("xhs-secret",), "dy": ("dy-secret",), "ks": ("ks-secret",)}
            if cookies is None
            else cookies
        )

    def has_cookies(self, platform):
        return bool(self.cookies.get(platform, ()))

    def candidates(self, platform):
        return tuple(self.cookies.get(platform, ()))


async def _execute(*, store, crawler, ai, settings=None, cookie_pool_loader=None):
    workflow = workflow_class(
        "wf-1",
        {
            "_crawler_service": crawler,
            "_settings": settings or StubSettings(),
            "_cookie_pool_loader": cookie_pool_loader or (lambda: StubCookiePool()),
        },
    )
```

同时将 `StubSettings.mediaspider_runtime_options()` 改为只返回 `{"headless": True}`。

- [ ] **Step 2: 编写 workflow 只加载一次和认证失效换 Cookie 的失败测试**

```python
def test_workflow_loads_cookie_file_once_and_rotates_expired_cookie():
    loads = 0

    def loader():
        nonlocal loads
        loads += 1
        return StubCookiePool({"xhs": ("expired", "valid")})

    class RetryCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            self.calls.append(("creator", "xhs", options))
            if options["cookies"] == "expired":
                raise CrawlerExecutionError(
                    "xhs",
                    RuntimeError("unsafe"),
                    CrawlResult(platform="xhs", crawl_type="creator"),
                    failure=CrawlerFailure(code="credentials_expired", message="凭证失效", suggestion="更新凭证"),
                )
            return CrawlResult(platform="xhs", crawl_type="creator", creators=[{"id": "owner"}], creator_count=1)

    store = StubStore(platforms=["小红书"])
    crawler = RetryCrawler()
    asyncio.run(_execute(store=store, crawler=crawler, ai=StubAI(report=_report_payload(platforms=["小红书"])), cookie_pool_loader=loader))
    assert loads == 1
    assert [call[2]["cookies"] for call in crawler.calls[:2]] == ["expired", "valid"]
```

- [ ] **Step 3: 编写非认证错误不切换和空池不调用爬虫的失败测试**

```python
def test_non_authentication_failure_does_not_rotate_cookie():
    class NonAuthenticationCrawler(StubCrawler):
        async def crawl_by_creator(self, *, creator_url, **options):
            self.calls.append(("creator", "xhs", options))
            raise CrawlerExecutionError(
                "xhs",
                RuntimeError("unsafe"),
                CrawlResult(platform="xhs", crawl_type="creator"),
                failure=CrawlerFailure(
                    code="browser_timeout",
                    message="浏览器操作超时",
                    suggestion="稍后重试",
                ),
            )

    store = StubStore(platforms=["小红书"])
    crawler = NonAuthenticationCrawler()
    asyncio.run(
        _execute(
            store=store,
            crawler=crawler,
            ai=StubAI(report=_report_payload(platforms=["小红书"])),
            cookie_pool_loader=lambda: StubCookiePool({"xhs": ("first", "second")}),
        )
    )
    creator_cookies = [
        options["cookies"]
        for mode, _platform, options in crawler.calls
        if mode == "creator"
    ]
    assert creator_cookies == ["first"]


def test_empty_cookie_pool_never_calls_crawler():
    store = StubStore()
    crawler = StubCrawler()
    with pytest.raises(ValueError, match="采集失败"):
        asyncio.run(
            _execute(
                store=store,
                crawler=crawler,
                ai=StubAI(),
                cookie_pool_loader=lambda: StubCookiePool(
                    {"xhs": (), "dy": (), "ks": ()}
                ),
            )
        )
    assert crawler.calls == []
    assert {
        item["failureCode"]
        for item in store.result_payloads[-1]["crawlProgress"]["platformSummaries"]
    } == {"credentials_missing"}
```

- [ ] **Step 4: 运行目标测试并确认失败原因是 workflow 尚未使用 Cookie 池**

Run: `conda run -n starx pytest tests/test_account_report_workflow.py -k "cookie or rotate or authentication" -q`

Expected: FAIL，加载器未调用或爬虫参数缺少 `cookies`。

- [ ] **Step 5: 实现统一认证轮换辅助函数**

```python
from collections.abc import Awaitable, Callable

from app.services.mediaspider.cookie_pool import WorkflowCookiePool, load_cookie_pool


async def _crawl_with_cookie_candidates(
    cookie_pool: WorkflowCookiePool,
    platform: str,
    operation: Callable[[str], Awaitable[CrawlResult]],
) -> CrawlResult:
    last_authentication_error: CrawlerExecutionError | None = None
    for cookie in cookie_pool.candidates(platform):
        try:
            return await operation(cookie)
        except CrawlerExecutionError as exc:
            if exc.failure.code != "credentials_expired":
                raise
            last_authentication_error = exc
    if last_authentication_error is not None:
        raise last_authentication_error
    raise ValueError("平台 Cookie 池为空")
```

- [ ] **Step 6: 在 workflow 开始读取一次并接入两种爬取**

在解析 `plans` 后获取加载器并创建局部快照：

```python
cookie_pool_loader = self.context.get("_cookie_pool_loader") or load_cookie_pool
cookie_pool = cookie_pool_loader()
```

生成不含 Cookie 的 `runtime_options_by_platform`。空池判断改为 `cookie_pool.has_cookies(plan.platform_code)`。博主和关键词调用分别包装为：

```python
creator_result = await _crawl_with_cookie_candidates(
    cookie_pool,
    plan.platform_code,
    lambda cookie: crawler.crawl_by_creator(
        creator_url=plan.creator_url,
        on_progress=tracker.callback(plan.platform_name, "creator"),
        cookies=cookie,
        **runtime_options,
    ),
)
```

关键词调用采用相同结构，并传入 `keywords`、`platform` 和对应 progress callback。

- [ ] **Step 7: 运行账号报告 workflow 测试并修复兼容测试桩**

Run: `conda run -n starx pytest tests/test_account_report_workflow.py -q`

Expected: PASS，0 failures。

- [ ] **Step 8: 提交 workflow 集成**

```bash
git add app/services/account_report/workflow.py tests/test_account_report_workflow.py
git commit -m "feat: rotate mediaspider cookies in account workflow"
```

---

### Task 4: 回归验证与安全审计

**Files:**
- Verify: `app/services/mediaspider/cookie_pool.py`
- Verify: `app/core/config.py`
- Verify: `app/services/account_report/workflow.py`
- Verify: `.gitignore`
- Verify: `README.md`

**Interfaces:**
- Consumes: Tasks 1–3 的全部接口与行为。
- Produces: 可交付的完整回归证据。

- [ ] **Step 1: 运行聚焦测试**

Run: `conda run -n starx pytest tests/test_mediaspider_cookie_pool.py tests/test_mediaspider_config.py tests/test_account_report_workflow.py -q`

Expected: PASS，0 failures。

- [ ] **Step 2: 运行 MediaSpider 与账号报告完整回归**

Run: `conda run -n starx pytest tests/test_mediaspider_*.py tests/test_account_report_*.py -q`

Expected: PASS，0 failures。

- [ ] **Step 3: 运行静态安全检查**

Run: `git check-ignore cookies/cookies.json`

Expected: 输出 `cookies/cookies.json`。

Run: `git status --short`

Expected: 不出现 `cookies/cookies.json`，且不存在意外修改。

Run: `git diff --check HEAD~3..HEAD`

Expected: 无输出，退出码 0。

- [ ] **Step 4: 对照设计逐项审计**

确认：JSON 仅在 workflow 局部加载；全局仅保存整数游标；三个环境变量已删除；认证失效轮换；非认证错误不轮换；空池安全降级；真实 Cookie 未被提交或输出。

## 执行审查补充

最终范围审查发现 `scripts/media_spider.py` 是独立的后端直接爬取入口，原文件仍含硬编码 Cookie。实施时将认证轮换辅助函数下沉为 `cookie_pool.run_with_cookie_candidates()`，由账号报告 workflow 和该脚本共同调用；新增 `tests/test_media_spider_script.py` 通过 AST 检查硬编码凭证，并验证脚本实际从注入的池中取 Cookie。
