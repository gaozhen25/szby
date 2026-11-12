"""Managed, persistent Google Chrome profiles for platform accounts."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, AsyncIterator

from message_adapter.process_lock import SingleInstanceLock


def chrome_executable() -> Path:
    """Return the installed Google Chrome binary, not Playwright's Chromium."""
    system = platform.system()
    candidates: list[Path] = []
    if system == "Darwin":
        candidates.extend(
            [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            ]
        )
    elif system == "Windows":
        roots = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        candidates.extend(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe" for root in roots if root)
    else:
        for name in ("google-chrome", "google-chrome-stable", "chrome"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError("无法启动本机 Google Chrome。请确认已安装 Google Chrome。")


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_cdp(port: int, process: subprocess.Popen[Any], timeout_s: float = 20) -> str:
    endpoint = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{endpoint}/json/version", timeout=0.5) as response:
                if getattr(response, "status", 200) == 200:
                    return endpoint
        except (OSError, urllib.error.URLError):
            if process.poll() is not None:
                raise RuntimeError("本机 Google Chrome 已退出，无法通过 CDP 连接")
        time.sleep(0.1)
    raise RuntimeError("本机 Google Chrome 的 CDP 端口没有就绪")


def _chrome_command(executable: Path, port: int, profile_dir: Path, start_url: str) -> list[str]:
    return [
        str(executable),
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        str(start_url or "about:blank"),
    ]


def _stop_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def legacy_profile_issues(profile: "BrowserProfile") -> list[str]:
    platform_dir = profile.root.expanduser().resolve() / profile.platform_key
    if not platform_dir.exists():
        return []
    legacy = [path for path in platform_dir.iterdir() if path.is_dir() and path.name != "device"]
    if len(legacy) > 1 or (legacy and profile.path.exists()):
        return ["multiple browser profile slots require explicit reset: " + ", ".join(map(str, legacy))]
    return []


def migrate_legacy_browser_profile(profile: "BrowserProfile") -> bool:
    """Move one unambiguous legacy profile into the fixed device slot."""
    issues = legacy_profile_issues(profile)
    if issues:
        raise RuntimeError("; ".join(issues))
    platform_dir = profile.root.expanduser().resolve() / profile.platform_key
    if not platform_dir.exists() or profile.path.exists():
        return False
    legacy = [path for path in platform_dir.iterdir() if path.is_dir() and path.name != "device"]
    if not legacy:
        return False
    profile.lock_path.parent.mkdir(parents=True, exist_ok=True)
    with SingleInstanceLock(profile.lock_path):
        if profile.path.exists():
            return False
        shutil.move(str(legacy[0]), str(profile.path))
        for directory in (profile.root.expanduser().resolve(), platform_dir, profile.path, profile.lock_path.parent):
            try:
                os.chmod(directory, 0o700)
            except OSError:
                pass
    return True


@dataclass(frozen=True, slots=True)
class BrowserProfile:
    """The one persistent Chrome user-data directory assigned to a platform."""

    root: Path
    platform: str

    @property
    def platform_key(self) -> str:
        value = str(self.platform or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value):
            raise ValueError(f"invalid browser-profile platform: {self.platform!r}")
        return value

    @property
    def path(self) -> Path:
        return self.root.expanduser().resolve() / self.platform_key / "device"

    @property
    def lock_path(self) -> Path:
        return self.root.expanduser().resolve() / ".locks" / f"{self.platform_key}-device.lock"

    def prepare(self) -> Path:
        """Create private profile directories without touching any user Chrome profile."""
        root = self.root.expanduser().resolve()
        platform_dir = root / self.platform_key
        profile_dir = self.path
        lock_dir = root / ".locks"
        for directory in (root, platform_dir, profile_dir, lock_dir):
            directory.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(directory, 0o700)
            except OSError:
                pass
        return profile_dir

    def clear(self) -> bool:
        """Delete the managed Chrome profile so the next login starts without leftover cookies."""
        lock_dir = self.root.expanduser().resolve() / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(lock_dir, 0o700)
        except OSError:
            pass
        with SingleInstanceLock(self.lock_path):
            path = self.path
            if not path.exists():
                return False
            shutil.rmtree(path)
            return True

    @asynccontextmanager
    async def launch(self, *, headless: bool = False) -> AsyncIterator[Any]:
        """Launch the installed Google Chrome with this platform's profile."""
        if headless:
            raise ValueError("managed platform profiles must use visible Google Chrome")
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright 未安装。请执行: uv sync --extra browser") from exc

        profile_dir = self.prepare()
        with SingleInstanceLock(self.lock_path):
            playwright = await async_playwright().start()
            context = None
            try:
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    channel="chrome",
                    headless=False,
                    locale="zh-CN",
                    viewport=None,
                )
                yield context
            except Exception as exc:
                if context is None:
                    raise RuntimeError(
                        "无法启动本机 Google Chrome。请确认已安装 Google Chrome；"
                        "若使用源码运行请执行 uv sync --extra browser"
                    ) from exc
                raise
            finally:
                try:
                    if context is not None:
                        await context.close()
                finally:
                    await playwright.stop()

    @asynccontextmanager
    async def open_chrome(self, *, start_url: str = "about:blank") -> AsyncIterator[str]:
        """Start installed Google Chrome and yield its CDP endpoint.

        The endpoint is not attached to the page. BOSS closes the login tab when
        a page debugger such as Playwright is connected.
        """
        profile_dir = self.prepare()
        executable = chrome_executable()
        port = _free_local_port()
        with SingleInstanceLock(self.lock_path):
            process = subprocess.Popen(
                _chrome_command(executable, port, profile_dir, start_url),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                yield await asyncio.to_thread(_wait_for_cdp, port, process)
            finally:
                _stop_process(process)

    @asynccontextmanager
    async def launch_over_cdp(self, *, start_url: str = "about:blank") -> AsyncIterator[Any]:
        """Start installed Google Chrome and attach through its DevTools port.

        Playwright's own launcher adds ``--enable-automation``. BOSS treats that
        session as an automated browser and keeps redirecting the login page.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright 未安装。请执行: uv sync --extra browser") from exc

        async with self.open_chrome(start_url=start_url) as endpoint:
            playwright = await async_playwright().start()
            browser = None
            try:
                browser = await playwright.chromium.connect_over_cdp(endpoint)
                contexts = list(browser.contexts)
                context = contexts[0] if contexts else await browser.new_context()
                yield context
            except Exception as exc:
                if browser is None:
                    raise RuntimeError(
                        "无法通过 CDP 连接本机 Google Chrome。请确认已安装 Google Chrome。"
                    ) from exc
                raise
            finally:
                try:
                    if browser is not None:
                        await browser.close()
                finally:
                    await playwright.stop()
