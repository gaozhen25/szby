"""通过 HTTP MediaSpider 精确定位公开平台账号。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .error_classifier import classify_crawler_error
from .http_platforms.douyin import DouyinClient
from .http_platforms.xhs import XhsClient, parse_creator_url
from .http_platforms.xhs.normalize import normalize_creator as normalize_xhs_creator
from .models import (
    CrawlResult,
    CrawlerExecutionError,
    InvalidCrawlRequestError,
)
from .platform_resolver import normalize_platform, resolve_creator_platform


ClientFactory = Callable[..., Any]


def _canonical_profile_url(value: Any) -> str:
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    return urlunsplit(
        ("https", parsed.hostname.lower(), parsed.path.rstrip("/"), "", "")
    )


class MediaSpiderAccountLookup:
    """解析账号号值或主页链接，只返回精确匹配的公开账号。"""

    def __init__(
        self,
        *,
        douyin_client_factory: ClientFactory = DouyinClient,
        xhs_client_factory: ClientFactory = XhsClient,
    ) -> None:
        self.douyin_client_factory = douyin_client_factory
        self.xhs_client_factory = xhs_client_factory

    async def resolve(
        self,
        *,
        platform: str,
        target: str,
        cookies: str,
    ) -> dict[str, Any]:
        platform_code = normalize_platform(platform)
        if platform_code not in {"dy", "xhs"}:
            raise InvalidCrawlRequestError("MediaSpider 账号解析仅支持抖音和小红书")
        try:
            return await asyncio.to_thread(
                self._resolve_sync,
                platform_code,
                str(target or "").strip(),
                cookies,
            )
        except InvalidCrawlRequestError:
            raise
        except CrawlerExecutionError:
            raise
        except Exception as exc:
            raise CrawlerExecutionError(
                platform_code,
                exc,
                CrawlResult(platform=platform_code, crawl_type="creator"),
                failure=classify_crawler_error(platform_code, exc),
            ) from exc

    def _resolve_sync(
        self,
        platform: str,
        target: str,
        cookies: str,
    ) -> dict[str, Any]:
        if not target:
            raise InvalidCrawlRequestError("账号号值或主页链接不能为空")
        is_url = target.startswith(("https://", "http://"))
        if is_url:
            detected = resolve_creator_platform(target)
            if detected != platform:
                raise InvalidCrawlRequestError("platform 与主页链接平台不一致")

        if platform == "dy":
            client = self.douyin_client_factory(cookie=cookies)
            payload = (
                client.get_creator_bundle(target, max_notes=1, with_posts=False)
                if is_url
                else client.get_profile_bundle(target)
            )
        else:
            client = self.xhs_client_factory(cookie=cookies)
            if is_url:
                info = parse_creator_url(target)
                raw_profile = client.get_creator_info(
                    info["user_id"],
                    xsec_token=info["xsec_token"],
                    xsec_source=info["xsec_source"] or "pc_feed",
                )
                creator = normalize_xhs_creator(info["user_id"], raw_profile)
                payload = {"creators": [creator] if creator else []}
            else:
                payload = client.get_profile_bundle(target)

        if not is_url and payload.get("exact_match") is not True:
            raise InvalidCrawlRequestError("未找到与账号号值精确匹配的平台账号")
        creators = [item for item in payload.get("creators") or [] if item]
        if not creators:
            raise InvalidCrawlRequestError("未识别到公开账号资料")

        creator = dict(creators[0])
        profile_url = _canonical_profile_url(creator.get("profile_url"))
        if not profile_url:
            raise InvalidCrawlRequestError("未识别到公开账号主页")
        if resolve_creator_platform(profile_url) != platform:
            raise InvalidCrawlRequestError("账号主页与目标平台不一致")
        creator["profile_url"] = profile_url
        creator["source_provider"] = "mediaspider"
        creator["source_operations"] = ["get_account"]
        return creator
