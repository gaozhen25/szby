# -*- coding: utf-8 -*-
"""
爬虫侧 SDK —— 实时爬取，需要浏览器。

``keyword_ex`` / ``creator_ex`` 返回标准 API dict::

    {
        "code": 0,
        "message": "ok",
        "data": { "notes": [...], "summary": {...}, ... }
    }

后端同事请使用 ``XhsBackendClient``（无浏览器）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from services.crawler_runner import run_creator_crawl, run_keyword_search

from .exceptions import SdkError


class MediaCrawlerSDK:
    """
    爬虫侧 SDK —— 本机执行爬取（需浏览器 / CDP）。

    Example::

        from sdk import MediaCrawlerSDK

        sdk = MediaCrawlerSDK()
        result = sdk.keyword_ex("xhs", "火星生活")
        print(result["data"]["summary"]["note_count"])
    """

    async def keyword_ex_async(
        self,
        platform: str,
        keyword: str,
        *,
        login_type: str = "qrcode",
        max_notes_count: Optional[int] = None,
        enable_comments: bool = False,
        enable_sub_comments: bool = False,
        headless: Optional[bool] = None,
        cookies: str = "",
        start_page: int = 1,
    ) -> dict[str, Any]:
        try:
            return await run_keyword_search(
                platform,
                keyword,
                login_type=login_type,
                max_notes_count=max_notes_count,
                enable_comments=enable_comments,
                enable_sub_comments=enable_sub_comments,
                headless=headless,
                cookies=cookies,
                start_page=start_page,
            )
        except ValueError as exc:
            raise SdkError(str(exc)) from exc

    def keyword_ex(
        self,
        platform: str,
        keyword: str,
        *,
        login_type: str = "qrcode",
        max_notes_count: Optional[int] = None,
        enable_comments: bool = False,
        enable_sub_comments: bool = False,
        headless: Optional[bool] = None,
        cookies: str = "",
        start_page: int = 1,
    ) -> dict[str, Any]:
        """``keyword_ex(platform, keyword) -> dict``"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.keyword_ex_async(
                    platform,
                    keyword,
                    login_type=login_type,
                    max_notes_count=max_notes_count,
                    enable_comments=enable_comments,
                    enable_sub_comments=enable_sub_comments,
                    headless=headless,
                    cookies=cookies,
                    start_page=start_page,
                )
            )
        raise SdkError(
            "keyword_ex() 不能在 async 上下文中调用，请改用 await keyword_ex_async(...)"
        )

    async def creator_ex_async(
        self,
        platform: str,
        creator_id: str,
        *,
        login_type: str = "qrcode",
        max_notes_count: Optional[int] = None,
        enable_comments: bool = False,
        enable_sub_comments: bool = False,
        headless: Optional[bool] = None,
        cookies: str = "",
    ) -> dict[str, Any]:
        try:
            return await run_creator_crawl(
                platform,
                creator_id,
                login_type=login_type,
                max_notes_count=max_notes_count,
                enable_comments=enable_comments,
                enable_sub_comments=enable_sub_comments,
                headless=headless,
                cookies=cookies,
            )
        except ValueError as exc:
            raise SdkError(str(exc)) from exc

    def creator_ex(
        self,
        platform: str,
        creator_id: str,
        *,
        login_type: str = "qrcode",
        max_notes_count: Optional[int] = None,
        enable_comments: bool = False,
        enable_sub_comments: bool = False,
        headless: Optional[bool] = None,
        cookies: str = "",
    ) -> dict[str, Any]:
        """``creator_ex(platform, creator_id, ...) -> dict``"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.creator_ex_async(
                    platform,
                    creator_id,
                    login_type=login_type,
                    max_notes_count=max_notes_count,
                    enable_comments=enable_comments,
                    enable_sub_comments=enable_sub_comments,
                    headless=headless,
                    cookies=cookies,
                )
            )
        raise SdkError(
            "creator_ex() 不能在 async 上下文中调用，请改用 await creator_ex_async(...)"
        )


def keyword_ex(
    platform: str,
    keyword: str,
    *,
    login_type: str = "qrcode",
    max_notes_count: Optional[int] = None,
    enable_comments: bool = False,
    enable_sub_comments: bool = False,
    headless: Optional[bool] = None,
    cookies: str = "",
    start_page: int = 1,
) -> dict[str, Any]:
    """关键词搜索：``keyword_ex(platform, keyword) -> dict``"""
    return MediaCrawlerSDK().keyword_ex(
        platform,
        keyword,
        login_type=login_type,
        max_notes_count=max_notes_count,
        enable_comments=enable_comments,
        enable_sub_comments=enable_sub_comments,
        headless=headless,
        cookies=cookies,
        start_page=start_page,
    )


async def keyword_ex_async(
    platform: str,
    keyword: str,
    *,
    login_type: str = "qrcode",
    max_notes_count: Optional[int] = None,
    enable_comments: bool = False,
    enable_sub_comments: bool = False,
    headless: Optional[bool] = None,
    cookies: str = "",
    start_page: int = 1,
) -> dict[str, Any]:
    return await MediaCrawlerSDK().keyword_ex_async(
        platform,
        keyword,
        login_type=login_type,
        max_notes_count=max_notes_count,
        enable_comments=enable_comments,
        enable_sub_comments=enable_sub_comments,
        headless=headless,
        cookies=cookies,
        start_page=start_page,
    )


def creator_ex(
    platform: str,
    creator_id: str,
    *,
    login_type: str = "qrcode",
    max_notes_count: Optional[int] = None,
    enable_comments: bool = False,
    enable_sub_comments: bool = False,
    headless: Optional[bool] = None,
    cookies: str = "",
) -> dict[str, Any]:
    """博主爬取：``creator_ex(platform, creator_id, ...) -> dict``"""
    return MediaCrawlerSDK().creator_ex(
        platform,
        creator_id,
        login_type=login_type,
        max_notes_count=max_notes_count,
        enable_comments=enable_comments,
        enable_sub_comments=enable_sub_comments,
        headless=headless,
        cookies=cookies,
    )


async def creator_ex_async(
    platform: str,
    creator_id: str,
    *,
    login_type: str = "qrcode",
    max_notes_count: Optional[int] = None,
    enable_comments: bool = False,
    enable_sub_comments: bool = False,
    headless: Optional[bool] = None,
    cookies: str = "",
) -> dict[str, Any]:
    return await MediaCrawlerSDK().creator_ex_async(
        platform,
        creator_id,
        login_type=login_type,
        max_notes_count=max_notes_count,
        enable_comments=enable_comments,
        enable_sub_comments=enable_sub_comments,
        headless=headless,
        cookies=cookies,
    )
