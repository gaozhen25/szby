from __future__ import annotations

import http.cookiejar
import json
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.cookie_sync.extractor import cookie_header, discover_sources
from scripts.cookie_sync.storage import atomic_write_pool, build_pool, upload_pool


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def make_cookie(name: str, value: str, domain: str, *, expires: int | None = None):
    return http.cookiejar.Cookie(
        0,
        name,
        value,
        None,
        False,
        domain,
        True,
        domain.startswith("."),
        "/",
        True,
        True,
        expires,
        False,
        None,
        None,
        {},
    )


def test_cookie_header_filters_domains_expiry_and_duplicate_names():
    header = cookie_header(
        [
            make_cookie("a", "old", ".xiaohongshu.com"),
            make_cookie("a", "new", "edith.xiaohongshu.com"),
            make_cookie("expired", "secret", ".xiaohongshu.com", expires=int(time.time()) - 1),
            make_cookie("foreign", "secret", ".example.com"),
        ],
        ("xiaohongshu.com",),
    )

    assert header == "a=new"
    assert "secret" not in header


@pytest.mark.parametrize(
    ("cwd", "script"),
    [
        (BACKEND_ROOT, Path("scripts/sync_browser_cookies.py")),
        (BACKEND_ROOT / "scripts", Path("sync_browser_cookies.py")),
    ],
)
def test_sync_browser_cookies_supports_direct_execution(cwd: Path, script: Path):
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--no-upload" in result.stdout


def test_discover_sources_finds_chrome_network_cookie_and_douyin_app(tmp_path: Path):
    chrome = tmp_path / "Library/Application Support/Google/Chrome/Default/Network/Cookies"
    douyin = tmp_path / "Library/Application Support/抖音/Cookies"
    chrome.parent.mkdir(parents=True)
    douyin.parent.mkdir(parents=True)
    chrome.touch()
    douyin.touch()

    sources = discover_sources(tmp_path)

    assert {(item.name, item.profile) for item in sources} == {
        ("Chrome", "Default"),
        ("抖音客户端", "Default"),
    }


def test_build_pool_requires_both_platforms_by_default(tmp_path: Path):
    with pytest.raises(ValueError, match="dy"):
        build_pool({"xhs": ["x=1"], "dy": []}, tmp_path / "cookies.json", allow_partial=False)


def test_partial_update_preserves_missing_platform_and_ks(tmp_path: Path):
    output = tmp_path / "cookies.json"
    output.write_text(
        json.dumps({"xhs": ["old-x"], "dy": ["old-d"], "ks": ["old-k"]}),
        encoding="utf-8",
    )

    pool = build_pool({"xhs": ["new-x"], "dy": []}, output, allow_partial=True)

    assert pool == {"xhs": ["new-x"], "dy": ["old-d"], "ks": ["old-k"]}


def test_atomic_write_uses_private_permissions(tmp_path: Path):
    output = tmp_path / "cookies/cookies.json"
    atomic_write_pool(output, {"xhs": ["x=1"], "dy": ["d=1"], "ks": []})

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text(encoding="utf-8"))["dy"] == ["d=1"]


@pytest.mark.parametrize("host", ["bad host", "starx;touch-pwned"])
def test_upload_rejects_unsafe_host_before_running_commands(tmp_path: Path, host: str):
    with pytest.raises(ValueError, match="主机名"):
        upload_pool(tmp_path / "cookies.json", host, "~/projects/cookies.json")


def test_upload_rejects_parent_traversal(tmp_path: Path):
    with pytest.raises(ValueError, match="远程路径"):
        upload_pool(tmp_path / "cookies.json", "starx", "~/projects/../cookies.json")
