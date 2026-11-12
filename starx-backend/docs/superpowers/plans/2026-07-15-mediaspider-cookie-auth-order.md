# MediaSpider Cookie 认证顺序修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复小红书、抖音和快手在配置 Cookie 注入前就误报凭证失效的问题，并证明只有注入后二次认证失败才返回 `credentials_expired`。

**Architecture:** 在 `runtime/auth.py` 中增加无敏感数据的共享异步认证编排函数，平台核心通过延迟登录、刷新客户端 Cookie 和登录态探测三个动作接入。首次探测失败只触发登录；Cookie 登录完成后进行二次探测，二次失败才抛 `CrawlerAuthenticationError`。

**Tech Stack:** Python 3.12、asyncio、pytest、Pydantic、Playwright；所有 Python 与测试命令必须使用 `conda run -n starx`。

## Global Constraints

- 后端 Python 环境必须使用名为 `starx` 的 conda 环境。
- 设计文档与实施计划使用中文。
- Cookie、请求头、原始异常文本不得进入日志、公开异常、进度快照或测试输出。
- 不修改账号报告 API、前端、数据库结构或 Cookie 配置来源。
- 不用 CDP、持久 Profile 或有头浏览器掩盖认证顺序问题。
- 保留工作树中与本计划无关的用户修改，不重置、不覆盖、不纳入本计划提交。

---

## 文件结构

- `app/services/mediaspider/runtime/auth.py`：唯一的认证状态机；不接收 Cookie 字符串或浏览器对象。
- `app/services/mediaspider/platforms/xhs/core.py`：把小红书探测、延迟登录和刷新动作接入共享状态机。
- `app/services/mediaspider/platforms/douyin/core.py`：把需要 `browser_context` 的抖音探测接入共享状态机。
- `app/services/mediaspider/platforms/kuaishou/core.py`：把快手探测、延迟登录和刷新动作接入共享状态机。
- `tests/test_mediaspider_auth.py`：共享认证状态机的纯异步单元测试。
- `tests/test_mediaspider_error_classifier.py`：三平台 fake Playwright 集成测试及既有安全分类回归。

---

### Task 1: 共享认证状态机

**Files:**
- Create: `tests/test_mediaspider_auth.py`
- Modify: `app/services/mediaspider/runtime/auth.py`

**Interfaces:**
- Consumes: 现有 `raise_for_cookie_auth_failure(platform: str, login_type: str) -> None`。
- Produces: `ensure_authenticated(*, platform: str, login_type: str, probe: AsyncProbe, login: AsyncAction, refresh: AsyncAction) -> None`。

- [ ] **Step 1: 写首次探测成功时不登录的失败测试**

```python
import asyncio

from app.services.mediaspider.runtime.auth import ensure_authenticated


def test_existing_login_state_skips_login_and_refresh():
    calls = []

    async def probe():
        calls.append("probe")
        return True

    async def login():
        calls.append("login")

    async def refresh():
        calls.append("refresh")

    asyncio.run(
        ensure_authenticated(
            platform="xhs",
            login_type="cookie",
            probe=probe,
            login=login,
            refresh=refresh,
        )
    )

    assert calls == ["probe"]
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `conda run -n starx pytest -q tests/test_mediaspider_auth.py::test_existing_login_state_skips_login_and_refresh`

Expected: 收集失败，提示 `cannot import name 'ensure_authenticated'`。

- [ ] **Step 3: 写 Cookie 登录成功与二次失败测试**

```python
import pytest

from app.services.mediaspider.models import CrawlerAuthenticationError


def test_cookie_login_refreshes_before_second_probe():
    calls = []
    probe_results = iter([False, True])

    async def probe():
        calls.append("probe")
        return next(probe_results)

    async def login():
        calls.append("login")

    async def refresh():
        calls.append("refresh")

    asyncio.run(
        ensure_authenticated(
            platform="xhs",
            login_type="cookie",
            probe=probe,
            login=login,
            refresh=refresh,
        )
    )

    assert calls == ["probe", "login", "refresh", "probe"]


def test_cookie_login_fails_only_after_second_probe():
    calls = []

    async def probe():
        calls.append("probe")
        return False

    async def login():
        calls.append("login")

    async def refresh():
        calls.append("refresh")

    with pytest.raises(CrawlerAuthenticationError) as exc_info:
        asyncio.run(
            ensure_authenticated(
                platform="dy",
                login_type="cookie",
                probe=probe,
                login=login,
                refresh=refresh,
            )
        )

    assert exc_info.value.platform == "dy"
    assert calls == ["probe", "login", "refresh", "probe"]
```

- [ ] **Step 4: 写交互登录与异常传播测试**

```python
@pytest.mark.parametrize("login_type", ["phone", "qrcode"])
def test_interactive_login_keeps_single_pre_login_probe(login_type):
    calls = []

    async def probe():
        calls.append("probe")
        return False

    async def login():
        calls.append("login")

    async def refresh():
        calls.append("refresh")

    asyncio.run(
        ensure_authenticated(
            platform="dy",
            login_type=login_type,
            probe=probe,
            login=login,
            refresh=refresh,
        )
    )

    assert calls == ["probe", "login", "refresh"]


@pytest.mark.parametrize(
    "failing_action",
    ["initial_probe", "login", "refresh", "second_probe"],
)
def test_auth_action_exception_is_not_reclassified(failing_action):
    error = RuntimeError("auth action failed")
    probe_count = 0

    async def probe():
        nonlocal probe_count
        probe_count += 1
        if failing_action == "initial_probe" and probe_count == 1:
            raise error
        if failing_action == "second_probe" and probe_count == 2:
            raise error
        return False

    async def login():
        if failing_action == "login":
            raise error

    async def refresh():
        if failing_action == "refresh":
            raise error

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(
            ensure_authenticated(
                platform="ks",
                login_type="cookie",
                probe=probe,
                login=login,
                refresh=refresh,
            )
        )

    assert exc_info.value is error
```

- [ ] **Step 5: 实现最小共享状态机**

```python
from collections.abc import Awaitable, Callable

AsyncAction = Callable[[], Awaitable[None]]
AsyncProbe = Callable[[], Awaitable[bool]]


async def ensure_authenticated(
    *,
    platform: str,
    login_type: str,
    probe: AsyncProbe,
    login: AsyncAction,
    refresh: AsyncAction,
) -> None:
    if await probe():
        return
    await login()
    await refresh()
    if login_type == "cookie" and not await probe():
        raise_for_cookie_auth_failure(platform, login_type)
```

- [ ] **Step 6: 运行共享状态机测试并确认 GREEN**

Run: `conda run -n starx pytest -q tests/test_mediaspider_auth.py`

Expected: `9 passed`。

- [ ] **Step 7: 提交 Task 1**

```bash
git add app/services/mediaspider/runtime/auth.py tests/test_mediaspider_auth.py
git diff --cached --check
git commit -m "fix: orchestrate MediaSpider cookie authentication"
```

---

### Task 2: 三平台接入共享认证状态机

**Files:**
- Modify: `tests/test_mediaspider_error_classifier.py`
- Modify: `app/services/mediaspider/platforms/xhs/core.py`
- Modify: `app/services/mediaspider/platforms/douyin/core.py`
- Modify: `app/services/mediaspider/platforms/kuaishou/core.py`

**Interfaces:**
- Consumes: Task 1 的 `ensure_authenticated(...)`。
- Produces: 三个平台统一的 `probe → login → refresh → probe` Cookie 认证顺序。

- [ ] **Step 1: 用可记录调用顺序的 fake client 替换固化回归的测试夹具**

```python
class _SequencedClient:
    def __init__(self, probe_results, calls):
        self._probe_results = iter(probe_results)
        self._calls = calls

    async def pong(self, *args, **kwargs):
        self._calls.append("probe")
        return next(self._probe_results)

    async def update_cookies(self, *args, **kwargs):
        self._calls.append("refresh")
```

- [ ] **Step 2: 写三平台 Cookie 注入后认证成功的失败测试**

```python
@pytest.mark.parametrize(
    ("module_path", "crawler_name", "client_factory_name", "login_name"),
    [
        (
            "app.services.mediaspider.platforms.xhs.core",
            "XiaoHongShuCrawler",
            "create_xhs_client",
            "XiaoHongShuLogin",
        ),
        (
            "app.services.mediaspider.platforms.douyin.core",
            "DouYinCrawler",
            "create_douyin_client",
            "DouYinLogin",
        ),
        (
            "app.services.mediaspider.platforms.kuaishou.core",
            "KuaishouCrawler",
            "create_ks_client",
            "KuaishouLogin",
        ),
    ],
)
def test_platform_cookie_login_refreshes_before_second_probe(
    monkeypatch, module_path, crawler_name, client_factory_name, login_name
):
    module = __import__(module_path, fromlist=[crawler_name])
    crawler = getattr(module, crawler_name)()
    calls = []

    async def launch_browser(*args, **kwargs):
        return _FakeBrowserContext()

    async def create_client(*args, **kwargs):
        return _SequencedClient([False, True], calls)

    async def search():
        calls.append("search")

    class CookieLogin:
        def __init__(self, *args, **kwargs):
            calls.append("construct_login")

        async def begin(self):
            calls.append("login")

    monkeypatch.setattr(module, "async_playwright", lambda: _FakePlaywrightContext())
    monkeypatch.setattr(module.config, "ENABLE_IP_PROXY", False)
    monkeypatch.setattr(module.config, "ENABLE_CDP_MODE", True)
    monkeypatch.setattr(module.config, "LOGIN_TYPE", "cookie")
    monkeypatch.setattr(module.config, "CRAWLER_TYPE", "search")
    monkeypatch.setattr(crawler, "launch_browser_with_cdp", launch_browser)
    monkeypatch.setattr(crawler, client_factory_name, create_client)
    monkeypatch.setattr(crawler, "search", search)
    monkeypatch.setattr(module, login_name, CookieLogin)

    asyncio.run(crawler.start())

    assert calls == [
        "probe",
        "construct_login",
        "login",
        "refresh",
        "probe",
        "search",
    ]
```

- [ ] **Step 3: 运行三平台成功测试并确认 RED**

Run: `conda run -n starx pytest -q tests/test_mediaspider_error_classifier.py::test_platform_cookie_login_refreshes_before_second_probe`

Expected: 三个平台均在第一次 `probe` 后抛 `CrawlerAuthenticationError`，未出现 `login` 和 `refresh`。

- [ ] **Step 4: 写三平台二次探测失败测试**

```python
@pytest.mark.parametrize(
    ("module_path", "crawler_name", "client_factory_name", "login_name", "platform"),
    [
        (
            "app.services.mediaspider.platforms.xhs.core",
            "XiaoHongShuCrawler",
            "create_xhs_client",
            "XiaoHongShuLogin",
            "xhs",
        ),
        (
            "app.services.mediaspider.platforms.douyin.core",
            "DouYinCrawler",
            "create_douyin_client",
            "DouYinLogin",
            "dy",
        ),
        (
            "app.services.mediaspider.platforms.kuaishou.core",
            "KuaishouCrawler",
            "create_ks_client",
            "KuaishouLogin",
            "ks",
        ),
    ],
)
def test_platform_cookie_auth_failure_happens_after_login_and_refresh(
    monkeypatch, module_path, crawler_name, client_factory_name, login_name, platform
):
    module = __import__(module_path, fromlist=[crawler_name])
    crawler = getattr(module, crawler_name)()
    calls = []

    async def launch_browser(*args, **kwargs):
        return _FakeBrowserContext()

    async def create_client(*args, **kwargs):
        return _SequencedClient([False, False], calls)

    class CookieLogin:
        def __init__(self, *args, **kwargs):
            calls.append("construct_login")

        async def begin(self):
            calls.append("login")

    monkeypatch.setattr(module, "async_playwright", lambda: _FakePlaywrightContext())
    monkeypatch.setattr(module.config, "ENABLE_IP_PROXY", False)
    monkeypatch.setattr(module.config, "ENABLE_CDP_MODE", True)
    monkeypatch.setattr(module.config, "LOGIN_TYPE", "cookie")
    monkeypatch.setattr(crawler, "launch_browser_with_cdp", launch_browser)
    monkeypatch.setattr(crawler, client_factory_name, create_client)
    monkeypatch.setattr(module, login_name, CookieLogin)

    with pytest.raises(CrawlerAuthenticationError) as exc_info:
        asyncio.run(crawler.start())

    assert exc_info.value.platform == platform
    assert calls == [
        "probe",
        "construct_login",
        "login",
        "refresh",
        "probe",
    ]
```

- [ ] **Step 5: 接入小红书共享认证**

```python
from ...runtime.auth import ensure_authenticated

async def login() -> None:
    login_obj = XiaoHongShuLogin(
        login_type=config.LOGIN_TYPE,
        login_phone="",
        browser_context=self.browser_context,
        context_page=self.context_page,
        cookie_str=config.COOKIES,
    )
    await login_obj.begin()

async def refresh() -> None:
    await self.xhs_client.update_cookies(
        browser_context=self.browser_context,
        urls=self.cookie_urls,
    )

await ensure_authenticated(
    platform="xhs",
    login_type=config.LOGIN_TYPE,
    probe=self.xhs_client.pong,
    login=login,
    refresh=refresh,
)
```

- [ ] **Step 6: 接入抖音共享认证**

```python
from ...runtime.auth import ensure_authenticated

async def probe() -> bool:
    return await self.dy_client.pong(browser_context=self.browser_context)

async def login() -> None:
    login_obj = DouYinLogin(
        login_type=config.LOGIN_TYPE,
        login_phone="",
        browser_context=self.browser_context,
        context_page=self.context_page,
        cookie_str=config.COOKIES,
    )
    await login_obj.begin()

async def refresh() -> None:
    await self.dy_client.update_cookies(
        browser_context=self.browser_context,
        urls=self.cookie_urls,
    )

await ensure_authenticated(
    platform="dy",
    login_type=config.LOGIN_TYPE,
    probe=probe,
    login=login,
    refresh=refresh,
)
```

- [ ] **Step 7: 接入快手共享认证**

```python
from ...runtime.auth import ensure_authenticated

async def login() -> None:
    login_obj = KuaishouLogin(
        login_type=config.LOGIN_TYPE,
        login_phone=httpx_proxy_format,
        browser_context=self.browser_context,
        context_page=self.context_page,
        cookie_str=config.COOKIES,
    )
    await login_obj.begin()

async def refresh() -> None:
    await self.ks_client.update_cookies(
        browser_context=self.browser_context,
        urls=self.cookie_urls,
    )

await ensure_authenticated(
    platform="ks",
    login_type=config.LOGIN_TYPE,
    probe=self.ks_client.pong,
    login=login,
    refresh=refresh,
)
```

- [ ] **Step 8: 运行三平台测试并确认 GREEN**

Run: `conda run -n starx pytest -q tests/test_mediaspider_error_classifier.py -k 'platform_cookie'`

Expected: 三个平台成功路径和二次失败路径全部通过。

- [ ] **Step 9: 提交 Task 2**

```bash
git add app/services/mediaspider/platforms/xhs/core.py app/services/mediaspider/platforms/douyin/core.py app/services/mediaspider/platforms/kuaishou/core.py tests/test_mediaspider_error_classifier.py
git diff --cached --check
git commit -m "fix: apply cookies before MediaSpider auth failure"
```

---

### Task 3: 安全边界与回归验证

**Files:**
- Modify only if a regression exposes a defect in scope: `app/services/mediaspider/runtime/auth.py`, the three platform `core.py` files, or their tests.
- Do not modify: `app/services/mediaspider/platforms/xhs/playwright_sign.py`, `app/services/extract_service/reference_service.py`, `scripts/media_spider.py`。

**Interfaces:**
- Consumes: Tasks 1–2 的共享认证顺序。
- Produces: 可复查的完整测试证据和无敏感数据的真实探测结果。

- [ ] **Step 1: 运行 MediaSpider 定向回归**

Run:

```bash
conda run -n starx pytest -q \
  tests/test_mediaspider_auth.py \
  tests/test_mediaspider_error_classifier.py \
  tests/test_mediaspider_service.py \
  tests/test_mediaspider_runtime.py \
  tests/test_mediaspider_platform_runtime.py \
  tests/test_mediaspider_config.py \
  tests/test_mediaspider_safe_logging.py
```

Expected: 所列测试全部通过，无 warning、traceback 或敏感哨兵泄漏。

- [ ] **Step 2: 运行账号报告回归**

Run:

```bash
conda run -n starx pytest -q \
  tests/test_account_report_workflow.py \
  tests/test_account_report_crawl_progress.py \
  tests/test_account_report_api.py
```

Expected: 所列测试全部通过。

- [ ] **Step 3: 运行完整后端测试**

Run: `conda run -n starx pytest -q`

Expected: 退出码为 0，失败数为 0。

- [ ] **Step 4: 执行最小真实小红书探测**

在一次性 `starx` 进程中读取后端 `Settings`，调用内嵌 `MediaCrawlerService.crawl_by_keyword()`，设置：

```python
platform="xhs"
keywords=["美女"]
headless=True
enable_cdp_mode=False
max_notes_count=1
enable_comments=False
max_concurrency=1
```

输出仅允许包含：公开进度动作、最终内容/博主/评论计数、公开失败代码。不得输出 Cookie、请求头、异常原文或完整记录。若网络沙箱阻止访问，申请网络执行权限后重试同一命令。

Expected: 不再在首次空上下文探测后立即产生 `credentials_expired`；事件序列至少证明登录和刷新路径已执行。平台实时风控或 Cookie 真实失效可以产生后续安全失败，但必须发生在配置 Cookie 应用之后。

- [ ] **Step 5: 检查最终差异和工作树边界**

Run:

```bash
git diff --check
git status --short
git diff -- app/services/mediaspider/runtime/auth.py app/services/mediaspider/platforms/xhs/core.py app/services/mediaspider/platforms/douyin/core.py app/services/mediaspider/platforms/kuaishou/core.py tests/test_mediaspider_auth.py tests/test_mediaspider_error_classifier.py
```

Expected: 无空白错误；本计划差异仅包含认证实现和测试；用户原有无关修改仍保留。

- [ ] **Step 6: 提交验证中产生的必要修正**

若 Step 1–4 暴露本计划范围内的缺陷，先增加能复现的失败测试并确认 RED，再修复并重新执行 Step 1–5。仅在确有额外修正时提交：

```bash
git add app/services/mediaspider/runtime/auth.py app/services/mediaspider/platforms/xhs/core.py app/services/mediaspider/platforms/douyin/core.py app/services/mediaspider/platforms/kuaishou/core.py tests/test_mediaspider_auth.py tests/test_mediaspider_error_classifier.py
git diff --cached --check
git commit -m "test: harden MediaSpider cookie auth regression"
```
