"""Small, shared browser identity for non-browser platform transports."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess


_VERSION_PATTERN = re.compile(r"(?P<version>\d+(?:\.\d+){0,3})")
_UA_CHROME_PATTERN = re.compile(r"(?:Chrome|Chromium)/(?P<major>\d+)")
_FALLBACK_CHROME_VERSION = "145.0.0.0"


@dataclass(frozen=True, slots=True)
class BrowserIdentity:
    chrome_version: str
    chrome_major: int
    user_agent: str
    sec_ch_ua: str
    sec_ch_ua_platform: str


def _normalized_version(value: str) -> str:
    match = _VERSION_PATTERN.search(str(value or ""))
    if not match:
        return ""
    parts = match.group("version").split(".")[:4]
    parts.extend("0" for _ in range(4 - len(parts)))
    return ".".join(parts)


def _macos_chrome_version() -> str:
    bundles = (
        Path("/Applications/Google Chrome.app/Contents/Info.plist"),
        Path.home() / "Applications/Google Chrome.app/Contents/Info.plist",
    )
    for path in bundles:
        try:
            with path.open("rb") as file:
                return _normalized_version(str(plistlib.load(file).get("CFBundleShortVersionString") or ""))
        except (OSError, plistlib.InvalidFileException):
            continue
    return ""


def _executable_chrome_version() -> str:
    names = ("google-chrome", "google-chrome-stable", "chrome", "chromium")
    for name in names:
        executable = shutil.which(name)
        if not executable:
            continue
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                check=False,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        version = _normalized_version(f"{result.stdout} {result.stderr}")
        if version:
            return version
    return ""


def detect_chrome_version() -> str:
    """Return the installed Chrome version without launching a browser window."""
    override = _normalized_version(os.environ.get("ADAPTER_CHROME_VERSION", ""))
    if override:
        return override
    if platform.system() == "Darwin":
        version = _macos_chrome_version()
        if version:
            return version
    return _executable_chrome_version() or _FALLBACK_CHROME_VERSION


def chrome_major_from_user_agent(user_agent: str, *, fallback: int | None = None) -> int:
    match = _UA_CHROME_PATTERN.search(str(user_agent or ""))
    if match:
        return int(match.group("major"))
    return fallback if fallback is not None else current_browser_identity().chrome_major


def sec_ch_ua_for_user_agent(user_agent: str) -> str:
    major = chrome_major_from_user_agent(user_agent)
    return f'"Chromium";v="{major}", "Not_A Brand";v="99", "Google Chrome";v="{major}"'


def _identity_for(version: str, system: str) -> BrowserIdentity:
    normalized = _normalized_version(version) or _FALLBACK_CHROME_VERSION
    major = int(normalized.split(".", 1)[0])
    if system == "Darwin":
        os_token = "Macintosh; Intel Mac OS X 10_15_7"
        hint_platform = '"macOS"'
    elif system == "Windows":
        os_token = "Windows NT 10.0; Win64; x64"
        hint_platform = '"Windows"'
    else:
        os_token = "X11; Linux x86_64"
        hint_platform = '"Linux"'
    reduced_version = f"{major}.0.0.0"
    user_agent = (
        f"Mozilla/5.0 ({os_token}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{reduced_version} Safari/537.36"
    )
    return BrowserIdentity(
        chrome_version=normalized,
        chrome_major=major,
        user_agent=user_agent,
        sec_ch_ua=sec_ch_ua_for_user_agent(user_agent),
        sec_ch_ua_platform=hint_platform,
    )


@lru_cache(maxsize=1)
def current_browser_identity() -> BrowserIdentity:
    return _identity_for(detect_chrome_version(), platform.system())

