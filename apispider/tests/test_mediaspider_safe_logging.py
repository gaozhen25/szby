import ast
import logging
from pathlib import Path

import pytest

from app.services.mediaspider.models import CrawlerExecutionError, CrawlResult
from app.services.mediaspider.platform_resolver import resolve_creator_platform
from app.services.mediaspider.platforms.xhs.help import parse_creator_info_from_url
from app.services.mediaspider.vendor import tools


MEDIASPIDER_ROOT = Path(__file__).parents[1] / "app" / "services" / "mediaspider"
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}


def _attribute_path(node):
    values = []
    while isinstance(node, ast.Attribute):
        values.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        values.append(node.id)
    return list(reversed(values))


def test_all_mediaspider_log_calls_flow_through_the_safe_logger_boundary():
    unsafe = []
    for path in MEDIASPIDER_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in LOG_METHODS:
                continue
            attribute_path = _attribute_path(node.func)
            if "logger" in attribute_path and attribute_path[:2] != ["utils", "logger"]:
                unsafe.append(f"{path.relative_to(MEDIASPIDER_ROOT)}:{node.lineno}")
    assert unsafe == []


def test_mediaspider_public_raise_messages_are_fixed_literals():
    dynamic = []
    for path in MEDIASPIDER_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            call = node.exc if isinstance(node.exc, ast.Call) else None
            structured_wrapper = (
                call
                and isinstance(call.func, ast.Name)
                and call.func.id == "CrawlerExecutionError"
            )
            if call and call.args and not isinstance(call.args[0], ast.Constant) and not structured_wrapper:
                dynamic.append(f"{path.relative_to(MEDIASPIDER_ROOT)}:{node.lineno}")
    assert dynamic == []


def test_safe_logger_drops_dynamic_url_body_token_and_raw_exception(caplog):
    sentinel = "SENTINEL_TOKEN"
    with caplog.at_level(logging.DEBUG, logger="starx.mediaspider"):
        tools.logger.error(
            f"[Crawler.fetch] https://secret.example/path?token={sentinel} "
            f"body={{'authorization':'Bearer {sentinel}'}} SecretTokenError",
            RuntimeError(sentinel),
        )
    output = caplog.text
    assert "mediaspider.Crawler.fetch" in output
    assert "RuntimeError" in output
    assert "SecretTokenError" not in output
    assert sentinel not in output
    assert "secret.example" not in output
    assert "authorization" not in output.lower()


@pytest.mark.parametrize(
    "operation",
    [
        lambda secret: resolve_creator_platform(f"https://unknown.invalid/user?token={secret}"),
        lambda secret: parse_creator_info_from_url(f"https://invalid.local/profile?token={secret}"),
    ],
)
def test_public_parse_errors_do_not_echo_raw_urls(operation):
    secret = "SENTINEL_TOKEN"
    with pytest.raises(Exception) as exc_info:
        operation(secret)
    assert secret not in str(exc_info.value)
    assert "invalid.local" not in str(exc_info.value)


def test_crawler_execution_error_keeps_only_cause_type_not_raw_exception():
    secret = "SENTINEL_TOKEN"
    error = CrawlerExecutionError(
        "xhs",
        RuntimeError(f"https://secret.invalid?token={secret}"),
        CrawlResult(
            platform="xhs",
            crawl_type="search",
            creator_url=f"https://secret.invalid/profile?token={secret}",
            keywords=[secret],
            contents=[{"user_id": secret, "url": f"https://secret.invalid?token={secret}"}],
            comments=[{"content": secret}],
            creators=[{"id": secret}],
            content_count=1,
            comment_count=1,
            creator_count=1,
        ),
    )
    assert not hasattr(error, "cause")
    assert error.cause_type == "RuntimeError"
    assert secret not in repr(error.__dict__)
    assert error.partial_result.content_count == 1
    assert error.partial_result.contents == []
