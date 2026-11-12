"""从本机浏览器配置中提取抖音和小红书 Cookie。"""

from __future__ import annotations

import http.cookiejar
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import browser_cookie3


PLATFORM_DOMAINS = {
    "xhs": ("xiaohongshu.com", "rednote.com", "xhslink.com"),
    "dy": ("douyin.com",),
}


@dataclass(frozen=True)
class CookieSource:
    name: str
    profile: str
    loader: Callable[..., http.cookiejar.CookieJar]
    cookie_file: Path | None = None
    platforms: tuple[str, ...] = ("xhs", "dy")


@dataclass(frozen=True)
class ExtractionResult:
    cookies: dict[str, list[str]]
    source_counts: dict[str, int]
    warnings: tuple[str, ...]


def _profile_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for profile in (root / "Default", *sorted(root.glob("Profile *"))):
        for relative in (Path("Network/Cookies"), Path("Cookies")):
            candidate = profile / relative
            if candidate.is_file():
                files.append(candidate)
                break
    return files


def discover_sources(home: Path | None = None) -> list[CookieSource]:
    """发现支持的浏览器配置；每个 profile 独立生成一个池候选。"""

    home = home or Path.home()
    application_support = home / "Library/Application Support"
    chromium_browsers = (
        ("Chrome", application_support / "Google/Chrome", browser_cookie3.chrome),
        ("Edge", application_support / "Microsoft Edge", browser_cookie3.edge),
        ("Brave", application_support / "BraveSoftware/Brave-Browser", browser_cookie3.brave),
        ("Arc", application_support / "Arc/User Data", browser_cookie3.arc),
        ("Chromium", application_support / "Chromium", browser_cookie3.chromium),
    )

    sources: list[CookieSource] = []
    for browser_name, root, loader in chromium_browsers:
        for cookie_file in _profile_files(root):
            profile = (
                cookie_file.parent.parent.name
                if cookie_file.parent.name == "Network"
                else cookie_file.parent.name
            )
            sources.append(
                CookieSource(browser_name, profile, loader, cookie_file)
            )

    firefox_root = application_support / "Firefox/Profiles"
    for cookie_file in sorted(firefox_root.glob("*/cookies.sqlite")):
        sources.append(
            CookieSource("Firefox", cookie_file.parent.name, browser_cookie3.firefox, cookie_file)
        )

    safari_file = home / "Library/Cookies/Cookies.binarycookies"
    if safari_file.is_file():
        sources.append(CookieSource("Safari", "Default", browser_cookie3.safari, safari_file))

    # 抖音 macOS 客户端是 Chromium/Electron 应用，其 Cookie 文件可直接按域读取。
    douyin_file = application_support / "抖音/Cookies"
    if douyin_file.is_file():
        sources.append(
            CookieSource(
                "抖音客户端", "Default", _load_douyin_app, douyin_file, ("dy",)
            )
        )
    return sources


def _load_douyin_app(*, cookie_file: str, domain_name: str):
    errors: list[Exception] = []
    for service, user in (
        ("抖音 Safe Storage", "抖音"),
        ("Douyin Safe Storage", "Douyin"),
        ("douyin Safe Storage", "douyin"),
    ):
        try:
            reader = browser_cookie3.ChromiumBased(
                browser="抖音",
                cookie_file=cookie_file,
                domain_name=domain_name,
                os_crypt_name="chromium",
                osx_key_service=service,
                osx_key_user=user,
            )
            return reader.load()
        except Exception as exc:  # 库对钥匙串失败使用多种异常类型
            errors.append(exc)
    raise browser_cookie3.BrowserCookieError("无法解密抖音客户端 Cookie") from errors[-1]


def _is_domain_match(cookie_domain: str, allowed_domains: Iterable[str]) -> bool:
    normalized = cookie_domain.lstrip(".").lower()
    return any(
        normalized == domain or normalized.endswith(f".{domain}")
        for domain in allowed_domains
    )


def cookie_header(
    cookies: Iterable[http.cookiejar.Cookie], allowed_domains: Iterable[str]
) -> str:
    """生成 MediaSpider 接受的 Cookie 请求头，过滤过期项并按名称去重。"""

    now = time.time()
    by_name: dict[str, str] = {}
    ordered = sorted(cookies, key=lambda item: (len(item.path or "/"), item.domain))
    for cookie in ordered:
        if not _is_domain_match(cookie.domain, allowed_domains):
            continue
        if cookie.expires is not None and cookie.expires <= now:
            continue
        if cookie.name and cookie.value:
            by_name[cookie.name] = cookie.value
    return "; ".join(f"{name}={value}" for name, value in by_name.items())


def extract_cookies(sources: Iterable[CookieSource]) -> ExtractionResult:
    candidates = {"xhs": [], "dy": []}
    source_counts: dict[str, int] = {}
    warnings: list[str] = []

    for source in sources:
        found_for_source = 0
        for platform, domains in PLATFORM_DOMAINS.items():
            if platform not in source.platforms:
                continue
            cookies: list[http.cookiejar.Cookie] = []
            for domain in domains:
                try:
                    jar = source.loader(
                        cookie_file=str(source.cookie_file) if source.cookie_file else None,
                        domain_name=domain,
                    )
                    cookies.extend(jar)
                except Exception as exc:
                    detail = (
                        "数据库无权读取，请授予终端完全磁盘访问权限"
                        if "Unable to read database" in str(exc)
                        else type(exc).__name__
                    )
                    warnings.append(
                        f"{source.name}/{source.profile} 无法读取 {platform}: {detail}"
                    )
                    break
            header = cookie_header(cookies, domains)
            if header and header not in candidates[platform]:
                candidates[platform].append(header)
                found_for_source += 1
        if found_for_source:
            source_counts[f"{source.name}/{source.profile}"] = found_for_source

    return ExtractionResult(candidates, source_counts, tuple(dict.fromkeys(warnings)))
