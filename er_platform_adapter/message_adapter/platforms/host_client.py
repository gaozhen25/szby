"""Detect a local WeChat or WeCom host client after the documented startup.

The connector does not open a QR window for these platforms. Login succeeds
only after the desktop ``qkzd`` client has printed ``启动成功``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

HOST_PLATFORMS = ("wechat", "wecom")
_SUCCESS = "启动成功"
_USER_ID = re.compile(r'"user_id"\s*:\s*"(\d+)"')
_USERNAME = re.compile(r'"username"\s*:\s*"([^"\\]*)"')
_READ_LIMIT = 256 * 1024


def discover_host_account(platform: str, *, roots: list[Path] | None = None) -> dict[str, str] | None:
    """Return the newest logged-in account from qkzd logs, if startup succeeded."""
    selected = str(platform or "").strip().lower()
    if selected not in HOST_PLATFORMS:
        raise ValueError("unsupported host platform")
    found: dict[str, str] | None = None
    newest = -1.0
    for path in _log_files(roots if roots is not None else default_qkzd_roots()):
        try:
            modified = path.stat().st_mtime
            text = _tail(path)
        except OSError:
            continue
        account = _account_from_log(selected, text)
        if account is None or modified < newest:
            continue
        newest = modified
        found = account
    return found


def default_qkzd_roots() -> list[Path]:
    configured = os.environ.get("QKZD_DIR", "").strip()
    if configured:
        return [Path(configured).expanduser()]
    home = Path.home()
    return [
        home / "Desktop" / "qkzd",
        home / "桌面" / "qkzd",
        home / "OneDrive" / "Desktop" / "qkzd",
        home / "OneDrive" / "桌面" / "qkzd",
    ]


def _log_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name.lower() == "config.ini":
                continue
            if path.suffix.lower() in {".log", ".txt", ".out"} or "log" in path.parts:
                files.append(path)
    return files


def _tail(path: Path) -> str:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - _READ_LIMIT))
        return handle.read().decode("utf-8", errors="ignore")


def _account_from_log(platform: str, text: str) -> dict[str, str] | None:
    if _SUCCESS not in text:
        return None
    if platform == "wecom" and not any(token in text for token in ("企业微信", "WeCom", "corp_id")):
        return None
    if platform == "wechat" and ("企业微信" in text or "corp_id" in text or "WeCom" in text):
        return None
    if platform == "wechat" and "微信" not in text:
        return None
    user_ids = _USER_ID.findall(text)
    if not user_ids:
        return None
    names = _USERNAME.findall(text)
    return {"platform_actor_id": user_ids[-1], "nickname": names[-1] if names else ""}
