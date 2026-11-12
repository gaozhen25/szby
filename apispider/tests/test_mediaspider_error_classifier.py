import asyncio

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.services.mediaspider.error_classifier import classify_crawler_error
from app.services.mediaspider.failure_catalog import public_crawler_failure
from app.services.mediaspider.models import (
    CrawlResult,
    CrawlerAuthenticationError,
    CrawlerExecutionError,
    CrawlerFailure,
    CrawlerRunConfig,
)
from app.services.mediaspider.runtime.auth import raise_for_cookie_auth_failure
from app.services.mediaspider.runtime.runner import run_crawler


def test_cookie_auth_failure_stops_before_interactive_login():
    with pytest.raises(CrawlerAuthenticationError):
        raise_for_cookie_auth_failure("dy", "cookie")


@pytest.mark.parametrize("login_type", ["phone", "qrcode"])
def test_interactive_login_types_are_allowed(login_type):
    assert raise_for_cookie_auth_failure("dy", login_type) is None


def test_authentication_error_is_actionable_but_safe():
    failure = classify_crawler_error(
        "dy", CrawlerAuthenticationError("dy", "session=must-not-leak")
    )

    assert failure.code == "credentials_expired"
    assert failure.message == "登录凭证失效或未生效"
    assert "must-not-leak" not in failure.model_dump_json()


def test_plain_playwright_timeout_remains_browser_timeout():
    failure = classify_crawler_error(
        "xhs", PlaywrightTimeoutError("locator timeout session=must-not-leak")
    )

    assert failure.code == "browser_timeout"
    assert "must-not-leak" not in failure.model_dump_json()
    assert failure == public_crawler_failure("browser_timeout")


def test_known_signature_type_error_is_runtime_incompatible():
    failure = classify_crawler_error(
        "xhs",
        TypeError(
            "build_payload_array got multiple values for argument 'sign_state' "
            "session=must-not-leak"
        ),
    )

    assert failure.code == "runtime_incompatible"
    assert "must-not-leak" not in failure.model_dump_json()


def test_unknown_xhshow_signature_runtime_error_is_runtime_incompatible():
    failure = classify_crawler_error(
        "xhs",
        RuntimeError(
            "不支持的 xhshow build_payload_array 签名 "
            "raw-signature=must-not-leak"
        ),
    )

    assert failure.code == "runtime_incompatible"
    assert failure == public_crawler_failure("runtime_incompatible")
    assert "must-not-leak" not in failure.model_dump_json()
    assert "raw-signature" not in failure.model_dump_json()


def test_unknown_error_uses_safe_generic_failure():
    failure = classify_crawler_error(
        "ks", RuntimeError("https://secret.invalid?session=must-not-leak")
    )

    assert failure.code == "crawler_failed"
    assert "must-not-leak" not in failure.model_dump_json()
    assert "secret.invalid" not in failure.model_dump_json()


def test_platform_data_fetch_error_is_classified_as_blocked_without_details():
    DataFetchError = type(
        "DataFetchError",
        (RuntimeError,),
        {"__module__": "app.services.mediaspider.platforms.douyin.exception"},
    )

    failure = classify_crawler_error(
        "dy", DataFetchError("response token=must-not-leak")
    )

    assert failure == public_crawler_failure("platform_blocked")
    assert "must-not-leak" not in failure.model_dump_json()


def test_execjs_process_failure_is_runtime_incompatible_without_details():
    ProcessExitedWithNonZeroStatus = type(
        "ProcessExitedWithNonZeroStatus",
        (RuntimeError,),
        {"__module__": "execjs._exceptions"},
    )

    failure = classify_crawler_error(
        "dy", ProcessExitedWithNonZeroStatus("stderr=must-not-leak")
    )

    assert failure == public_crawler_failure("runtime_incompatible")
    assert "must-not-leak" not in failure.model_dump_json()


def test_execution_error_normalizes_caller_failure_through_public_catalog():
    error = CrawlerExecutionError(
        "xhs",
        RuntimeError("Cookie=execution-error-sentinel"),
        CrawlResult(platform="xhs", crawl_type="search"),
        failure=CrawlerFailure.model_construct(
            code="browser_timeout",
            message="malicious execution message sentinel",
            suggestion="malicious execution suggestion sentinel",
        ),
    )

    assert error.failure == public_crawler_failure("browser_timeout")
    assert "sentinel" not in error.failure.model_dump_json()


class _FakePage:
    async def goto(self, _url):
        return None


class _FakeBrowserContext:
    async def new_page(self):
        return _FakePage()


class _FakePlaywrightContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, traceback):
        return None


class _SequencedClient:
    def __init__(self, probe_results, calls):
        self._probe_results = iter(probe_results)
        self._calls = calls

    async def pong(self, *args, **kwargs):
        self._calls.append("probe")
        return next(self._probe_results)

    async def update_cookies(self, *args, **kwargs):
        self._calls.append("refresh")


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
    monkeypatch,
    module_path,
    crawler_name,
    client_factory_name,
    login_name,
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
            raise AssertionError("Cookie 登录不得调用 begin()")

        async def login_by_cookies(self):
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
    monkeypatch,
    module_path,
    crawler_name,
    client_factory_name,
    login_name,
    platform,
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
            raise AssertionError("Cookie 登录不得调用 begin()")

        async def login_by_cookies(self):
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


class _AuthenticationFailureCrawler:
    cdp_manager = None
    browser_context = None

    async def start(self):
        raise CrawlerAuthenticationError("xhs", "session=must-not-leak")


class _AuthenticationFailureFactory:
    def create_crawler(self, platform):
        assert platform == "xhs"
        return _AuthenticationFailureCrawler()


class _RuntimeFailureCrawler:
    cdp_manager = None
    browser_context = None

    async def start(self):
        raise RuntimeError(
            "cookie=MAIN_SECRET https://secret.invalid authorization=Bearer-main"
        )


class _CleanupFailureResource:
    async def cleanup(self, *, force):
        assert force is True
        raise RuntimeError(
            "cookie=CLEANUP_SECRET https://secret.invalid authorization=Bearer-cleanup"
        )


class _CleanupFailureCrawler:
    browser_context = None

    def __init__(self):
        self.cdp_manager = _CleanupFailureResource()

    async def start(self):
        return None


class _CrawlerFactory:
    def __init__(self, crawler):
        self.crawler = crawler

    def create_crawler(self, platform):
        assert platform == "xhs"
        return self.crawler


def _make_run_config():
    return CrawlerRunConfig(
        platform="xhs",
        crawl_type="search",
        keywords=["安全"],
        cookies="session=input-secret",
    )


def _assert_sensitive_cause_is_unreachable(error, secret):
    assert error.__cause__ is None
    assert error.__context__ is None
    assert secret not in str(error)
    assert secret not in repr(error.__dict__)


def test_runner_main_failure_drops_original_exception_context():
    with pytest.raises(CrawlerExecutionError) as exc_info:
        asyncio.run(
            run_crawler(
                _make_run_config(),
                factory=_CrawlerFactory(_RuntimeFailureCrawler()),
            )
        )

    _assert_sensitive_cause_is_unreachable(exc_info.value, "MAIN_SECRET")


def test_runner_cleanup_failure_drops_original_exception_context():
    with pytest.raises(CrawlerExecutionError) as exc_info:
        asyncio.run(
            run_crawler(
                _make_run_config(),
                factory=_CrawlerFactory(_CleanupFailureCrawler()),
            )
        )

    _assert_sensitive_cause_is_unreachable(exc_info.value, "CLEANUP_SECRET")


def test_runner_exposes_classified_failure_without_retaining_raw_cause():
    events = []

    with pytest.raises(CrawlerExecutionError) as exc_info:
        asyncio.run(
            run_crawler(
                _make_run_config(),
                on_progress=lambda event: events.append(event),
                factory=_AuthenticationFailureFactory(),
            )
        )

    error = exc_info.value
    assert error.failure.code == "credentials_expired"
    assert error.cause_type == "CrawlerAuthenticationError"
    assert events[-1].message == error.failure.message
    assert "must-not-leak" not in repr(error.__dict__)
    assert "must-not-leak" not in events[-1].model_dump_json()
