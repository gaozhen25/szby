# -*- coding: utf-8 -*-
"""实时爬取 API —— 触发爬虫并直接返回封装数据，供后端实时调用。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from sdk import MediaCrawlerSDK

router = APIRouter(prefix="/data", tags=["live-crawl"])


class SearchCrawlRequest(BaseModel):
    keyword: str = Field(..., description="搜索关键词")
    platform: str = Field(default="xhs", description="平台标识")
    max_notes_count: Optional[int] = Field(default=20, description="最多爬取笔记数")
    enable_comments: bool = Field(default=False, description="是否爬评论")
    login_type: str = Field(default="qrcode", description="登录方式")
    cookies: str = Field(default="", description="cookie 登录时使用")


class CreatorCrawlRequest(BaseModel):
    creator_id: str = Field(..., description="博主 user_id 或主页 URL")
    platform: str = Field(default="xhs", description="平台标识")
    max_notes_count: Optional[int] = Field(default=20, description="最多爬取笔记数")
    enable_comments: bool = Field(default=False, description="是否爬评论")
    login_type: str = Field(default="qrcode", description="登录方式")
    cookies: str = Field(default="", description="cookie 登录时使用")


@router.post("/crawl/search")
async def crawl_search_live(body: SearchCrawlRequest):
    """
    实时关键词搜索：触发爬虫 → 内存封装 → 直接返回 API 响应体。

    后端 ``XhsBackendClient.live()`` 调用此接口，**不读 JSON 文件**。
    """
    sdk = MediaCrawlerSDK()
    try:
        return await sdk.keyword_ex_async(
            body.platform,
            body.keyword,
            login_type=body.login_type,
            max_notes_count=body.max_notes_count,
            enable_comments=body.enable_comments,
            cookies=body.cookies,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/crawl/creator")
async def crawl_creator_live(body: CreatorCrawlRequest):
    """
    实时博主爬取：触发爬虫 → 内存封装 → 直接返回 API 响应体。
    """
    sdk = MediaCrawlerSDK()
    try:
        return await sdk.creator_ex_async(
            body.platform,
            body.creator_id,
            login_type=body.login_type,
            max_notes_count=body.max_notes_count,
            enable_comments=body.enable_comments,
            cookies=body.cookies,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
