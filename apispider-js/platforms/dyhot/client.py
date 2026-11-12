# -*- coding: utf-8 -*-
"""
抖音热点宝 Client

对齐 MediaCrawler media_platform/dyhot：
POST https://douhot.douyin.com/douhot/v1/dashboard/hot_search/query_list
body: {page_num, page_size, date_window, sub_type}
无需 a_bogus；依赖 douhot.douyin.com 登录 Cookie。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

from .help import cookie_header_pair
from .normalize import normalize_board_payload, normalize_search_list

DOUHOT_HOST = "https://douhot.douyin.com"
HOT_SEARCH_QUERY_PATH = "/douhot/v1/dashboard/hot_search/query_list"

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# 与 MediaCrawler config/dyhot_config.py 一致
DEFAULT_SUB_TYPE = 3001
DEFAULT_DATE_WINDOW = 24
DEFAULT_PAGE_SIZE = 10
DEFAULT_MAX_COUNT = 20  # 默认只取搜索热点总榜前 20 条


class DyHotClient:
    def __init__(
        self,
        cookie: Optional[str] = None,
        timeout: int = 60,
        user_agent: str = DEFAULT_UA,
        *,
        account_name: str = "",
    ):
        if cookie is None:
            from platforms.common.cookies import load_primary_account

            cookie = load_primary_account("dyhot", account_name=account_name).cookie
        self.cookie, self.cookie_dict = cookie_header_pair(cookie)
        self.timeout = timeout
        self.user_agent = user_agent
        self.session = requests.Session()
        self.account_name = account_name or ""
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": DOUHOT_HOST,
            "Referer": f"{DOUHOT_HOST}/",
            "Cookie": self.cookie,
        }

    def get_search_hot_board(
        self,
        page_num: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        sub_type: int = DEFAULT_SUB_TYPE,
        date_window: int = DEFAULT_DATE_WINDOW,
    ) -> Dict[str, Any]:
        """搜索热点总榜单页。"""
        payload = {
            "page_num": int(page_num),
            "page_size": int(page_size),
            "sub_type": int(sub_type),
            "date_window": int(date_window),
        }
        url = f"{DOUHOT_HOST}{HOT_SEARCH_QUERY_PATH}"
        resp = self.session.post(
            url,
            headers=self.headers,
            json=payload,
            timeout=self.timeout,
        )
        text = resp.text or ""
        lower = text[:200].lower()
        if "<!doctype html>" in lower or "<html" in lower:
            raise RuntimeError(
                "热点宝接口返回了 HTML 而不是 JSON。"
                f" status={resp.status_code} url={resp.url}\n"
                "请确认 Cookie 来自已登录的 https://douhot.douyin.com"
            )
        try:
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"热点宝响应非 JSON: status={resp.status_code} body={text[:200]}"
            ) from exc

        code = data.get("code")
        if code == 8 or data.get("data") == "用户未登录":
            raise RuntimeError("热点宝用户未登录，请更新 cookies/cookies.json 的 dyhot/dy")
        body = data.get("data")
        if code not in (0, None) and not (
            isinstance(body, dict) and body.get("search_list") is not None
        ):
            raise RuntimeError(
                f"热点宝搜索榜失败: code={code} data={str(data)[:300]}"
            )
        return data

    def crawl_search_hot_board(
        self,
        *,
        max_count: int = DEFAULT_MAX_COUNT,
        page_size: int = DEFAULT_PAGE_SIZE,
        sub_type: int = DEFAULT_SUB_TYPE,
        date_window: int = DEFAULT_DATE_WINDOW,
        page_interval: float = 1.0,
    ) -> Dict[str, Any]:
        """翻页抓取搜索热点总榜，结构对齐 MediaCrawler save_search_hot_board。"""
        collected: List[Dict[str, Any]] = []
        page_num = 1
        total_count = None

        while len(collected) < max_count:
            resp = self.get_search_hot_board(
                page_num=page_num,
                page_size=page_size,
                sub_type=sub_type,
                date_window=date_window,
            )
            data = resp.get("data") or {}
            if total_count is None:
                total_count = data.get("total_count")
            search_list = data.get("search_list") or []
            if not search_list:
                break

            page_items = normalize_search_list(
                search_list,
                start_rank=len(collected) + 1,
                sub_type=sub_type,
                date_window=date_window,
                limit=max_count - len(collected),
            )
            collected.extend(page_items)
            if len(collected) >= max_count or len(search_list) < page_size:
                break
            page_num += 1
            if page_interval > 0:
                time.sleep(page_interval)

        meta = {
            "sub_type": sub_type,
            "date_window": date_window,
            "page_size": page_size,
            "total_count": total_count,
            "fetched_count": len(collected),
        }
        return normalize_board_payload(collected, meta=meta)
