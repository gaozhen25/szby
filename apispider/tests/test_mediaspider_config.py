import pytest

from app.core.config import Settings


def test_mediaspider_runtime_options_do_not_load_cookie_environment(monkeypatch):
    monkeypatch.setenv("STARX_MEDIASPIDER_XHS_COOKIES", "must-not-load")

    configured = Settings(_env_file=None)
    options = configured.mediaspider_runtime_options("xhs")

    assert options["headless"] is True
    assert options["max_notes_count"] == 30
    assert options["max_comments_count"] == 20
    assert options["max_concurrency"] == 3
    assert configured.ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD == 10
    assert options["enable_sub_comments"] is False
    assert "cookies" not in options
    assert "must-not-load" not in repr(configured)
    assert "must-not-load" not in configured.model_dump_json()


def test_mediaspider_runtime_options_map_configured_values(monkeypatch):
    monkeypatch.setenv("STARX_MEDIASPIDER_HEADLESS", "false")
    monkeypatch.setenv("STARX_MEDIASPIDER_ENABLE_CDP_MODE", "true")
    monkeypatch.setenv("STARX_MEDIASPIDER_CDP_CONNECT_EXISTING", "true")
    monkeypatch.setenv("STARX_MEDIASPIDER_CDP_DEBUG_PORT", "9333")
    monkeypatch.setenv("STARX_MEDIASPIDER_CUSTOM_BROWSER_PATH", "/browser")
    monkeypatch.setenv("STARX_MEDIASPIDER_MAX_NOTES_COUNT", "12")
    monkeypatch.setenv("STARX_MEDIASPIDER_MAX_COMMENTS_COUNT", "7")
    monkeypatch.setenv("STARX_MEDIASPIDER_MAX_CONCURRENCY", "2")
    monkeypatch.setenv("STARX_MEDIASPIDER_ENABLE_COMMENTS", "false")
    monkeypatch.setenv("STARX_MEDIASPIDER_ENABLE_SUB_COMMENTS", "true")
    monkeypatch.setenv("STARX_MEDIASPIDER_ENABLE_IP_PROXY", "true")
    monkeypatch.setenv("STARX_MEDIASPIDER_IP_PROXY_PROVIDER", "static")
    monkeypatch.setenv("STARX_MEDIASPIDER_STATIC_PROXY_URL", "http://proxy.example")

    options = Settings(_env_file=None).mediaspider_runtime_options("dy")

    assert options == {
        "headless": False,
        "max_notes_count": 12,
        "max_comments_count": 7,
        "max_concurrency": 2,
        "enable_comments": False,
        "enable_sub_comments": True,
        "enable_cdp_mode": True,
        "cdp_connect_existing": True,
        "cdp_debug_port": 9333,
        "custom_browser_path": "/browser",
        "enable_ip_proxy": True,
        "ip_proxy_provider": "static",
        "static_proxy_url": "http://proxy.example",
    }


def test_mediaspider_runtime_options_reject_unknown_platform():
    with pytest.raises(ValueError, match="unsupported MediaSpider platform"):
        Settings(_env_file=None).mediaspider_runtime_options("bili")


def test_account_report_max_notes_per_keyword_must_be_positive(monkeypatch):
    monkeypatch.setenv("STARX_ACCOUNT_REPORT_MAX_NOTES_PER_KEYWORD", "0")

    with pytest.raises(ValueError):
        Settings(_env_file=None)
