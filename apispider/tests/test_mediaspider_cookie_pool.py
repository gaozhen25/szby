import asyncio
import json

import pytest

from app.services.mediaspider.cookie_pool import (
    CookiePoolConfigurationError,
    RoundRobinCursor,
    load_cookie_pool,
    run_with_cookie_candidates,
)
from app.services.mediaspider.models import (
    CrawlResult,
    CrawlerExecutionError,
    CrawlerFailure,
)


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_loads_platform_lists_filters_blanks_and_deduplicates(tmp_path):
    path = tmp_path / "cookies.json"
    _write(
        path,
        {
            "xhs": [" first ", "", "first", "second"],
            "dy": ["dy"],
            "ks": [],
        },
    )

    pool = load_cookie_pool(path, cursor=RoundRobinCursor())

    assert pool.candidates("xhs") == ("first", "second")
    assert pool.candidates("dy") == ("dy",)
    assert pool.has_cookies("ks") is False


def test_missing_platforms_are_empty_pools(tmp_path):
    path = tmp_path / "cookies.json"
    _write(path, {"xhs": ["xhs"]})

    pool = load_cookie_pool(path, cursor=RoundRobinCursor())

    assert pool.has_cookies("xhs") is True
    assert pool.has_cookies("dy") is False
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
    [
        [],
        {"xhs": "bad"},
        {"xhs": [123]},
        {"weibo": ["unexpected"]},
    ],
)
def test_invalid_shapes_fail_without_leaking_values(tmp_path, value):
    path = tmp_path / "cookies.json"
    _write(path, value)

    with pytest.raises(CookiePoolConfigurationError) as exc_info:
        load_cookie_pool(path)

    error = str(exc_info.value)
    assert "123" not in error
    assert "bad" not in error
    assert "unexpected" not in error


@pytest.mark.parametrize("contents", ["not-json", "{\"xhs\": [\"secret\"]"])
def test_invalid_json_fails_without_leaking_contents(tmp_path, contents):
    path = tmp_path / "cookies.json"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(CookiePoolConfigurationError) as exc_info:
        load_cookie_pool(path)

    assert contents not in str(exc_info.value)


def test_missing_file_has_safe_error(tmp_path):
    path = tmp_path / "missing.json"

    with pytest.raises(CookiePoolConfigurationError) as exc_info:
        load_cookie_pool(path)

    assert str(path) not in str(exc_info.value)


def test_round_robin_is_platform_scoped(tmp_path):
    path = tmp_path / "cookies.json"
    _write(
        path,
        {
            "xhs": ["x1", "x2"],
            "dy": ["d1", "d2"],
            "ks": [],
        },
    )
    cursor = RoundRobinCursor()

    assert load_cookie_pool(path, cursor=cursor).candidates("xhs") == ("x1", "x2")
    assert load_cookie_pool(path, cursor=cursor).candidates("xhs") == ("x2", "x1")
    assert load_cookie_pool(path, cursor=cursor).candidates("dy") == ("d1", "d2")


def test_one_candidate_sequence_contains_each_cookie_once(tmp_path):
    path = tmp_path / "cookies.json"
    _write(path, {"xhs": ["x1", "x2", "x3"]})

    candidates = load_cookie_pool(
        path,
        cursor=RoundRobinCursor(),
    ).candidates("xhs")

    assert candidates == ("x1", "x2", "x3")
    assert len(candidates) == len(set(candidates))


def test_repr_never_contains_cookie(tmp_path):
    path = tmp_path / "cookies.json"
    _write(path, {"xhs": ["must-not-leak"]})

    pool = load_cookie_pool(path)

    assert "must-not-leak" not in repr(pool)


def test_rejects_unknown_runtime_platform(tmp_path):
    path = tmp_path / "cookies.json"
    _write(path, {})
    pool = load_cookie_pool(path)

    with pytest.raises(ValueError, match="unsupported MediaSpider platform"):
        pool.candidates("bili")


def test_run_with_cookie_candidates_rotates_only_after_authentication_failure(
    tmp_path,
):
    path = tmp_path / "cookies.json"
    _write(path, {"xhs": ["expired", "valid"]})
    pool = load_cookie_pool(path, cursor=RoundRobinCursor())
    attempts = []

    async def operation(cookie):
        attempts.append(cookie)
        if cookie == "expired":
            raise CrawlerExecutionError(
                "xhs",
                RuntimeError("unsafe"),
                CrawlResult(platform="xhs", crawl_type="search"),
                failure=CrawlerFailure(
                    code="credentials_expired",
                    message="凭证失效",
                    suggestion="更新凭证",
                ),
            )
        return CrawlResult(platform="xhs", crawl_type="search")

    result = asyncio.run(run_with_cookie_candidates(pool, "xhs", operation))

    assert result.platform == "xhs"
    assert attempts == ["expired", "valid"]


def test_run_with_cookie_candidates_does_not_rotate_after_other_failure(tmp_path):
    path = tmp_path / "cookies.json"
    _write(path, {"xhs": ["first", "second"]})
    pool = load_cookie_pool(path, cursor=RoundRobinCursor())
    attempts = []

    async def operation(cookie):
        attempts.append(cookie)
        raise CrawlerExecutionError(
            "xhs",
            RuntimeError("unsafe"),
            CrawlResult(platform="xhs", crawl_type="search"),
            failure=CrawlerFailure(
                code="browser_timeout",
                message="浏览器操作超时",
                suggestion="稍后重试",
            ),
        )

    with pytest.raises(CrawlerExecutionError) as exc_info:
        asyncio.run(run_with_cookie_candidates(pool, "xhs", operation))

    assert exc_info.value.failure.code == "browser_timeout"
    assert attempts == ["first"]
