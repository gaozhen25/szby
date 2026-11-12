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


def test_http_verify_check_is_platform_blocked():
    failure = classify_crawler_error(
        "dy",
        RuntimeError("搜索被抖音风控拦截（search_nil_type=verify_check）"),
    )
    assert failure.code == "platform_blocked"


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


def test_execution_error_keeps_only_safe_process_exit_diagnostics():
    ProcessExitedWithNonZeroStatus = type(
        "ProcessExitedWithNonZeroStatus",
        (RuntimeError,),
        {"__module__": "execjs._exceptions"},
    )
    cause = ProcessExitedWithNonZeroStatus("unsafe")
    cause.status = 1
    cause.stderr = "FATAL ERROR: Reached heap limit token=must-not-leak"

    error = CrawlerExecutionError(
        "dy",
        cause,
        CrawlResult(platform="dy", crawl_type="creator"),
        failure=public_crawler_failure("runtime_incompatible"),
    )

    assert error.cause_exit_status == 1
    assert error.cause_diagnostic == "node_heap_exhausted"
    assert "must-not-leak" not in str(error)


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


def test_runner_main_failure_drops_original_exception_context(monkeypatch):
    def boom(run_config, collector, proxies=None):  # noqa: ARG001
        raise RuntimeError(
            "cookie=MAIN_SECRET https://secret.invalid authorization=Bearer-main"
        )

    monkeypatch.setattr(
        "app.services.mediaspider.runtime.runner.crawl_http_sync",
        boom,
    )
    with pytest.raises(CrawlerExecutionError) as exc_info:
        asyncio.run(run_crawler(_make_run_config()))

    _assert_sensitive_cause_is_unreachable(exc_info.value, "MAIN_SECRET")


def test_runner_exposes_classified_failure_without_retaining_raw_cause(monkeypatch):
    events = []

    def boom(run_config, collector, proxies=None):  # noqa: ARG001
        raise CrawlerAuthenticationError("xhs", "session=must-not-leak")

    monkeypatch.setattr(
        "app.services.mediaspider.runtime.runner.crawl_http_sync",
        boom,
    )
    with pytest.raises(CrawlerExecutionError) as exc_info:
        asyncio.run(
            run_crawler(
                _make_run_config(),
                on_progress=lambda event: events.append(event),
            )
        )

    error = exc_info.value
    assert error.failure.code == "credentials_expired"
    assert error.cause_type == "CrawlerAuthenticationError"
    assert events[-1].message == error.failure.message
    assert "must-not-leak" not in repr(error.__dict__)
    assert "must-not-leak" not in events[-1].model_dump_json()
