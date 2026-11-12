# -*- coding: utf-8 -*-
"""
抖音客户端：对齐 apispider/mediaspider（MediaCrawler 同源）逻辑

- GET /aweme/v1/web/general/search/single/  → 不加 a_bogus
- 其它接口 → execjs 签 a_bogus（libs/douyin.js）
- 公共参数 / Referer / Header 字段与 mediaspider DouYinClient 一致
"""

from __future__ import annotations

import copy
import json
import time
import urllib.parse
from enum import Enum
from typing import Any, Dict, List, Optional

import requests

from .normalize import (
    crawl_result,
    normalize_aweme,
    normalize_comment,
    normalize_creator,
    normalize_search_items,
)
from .help import (
    get_a_bogus,
    get_web_id,
    parse_cookie_str,
    parse_sec_user_id,
    parse_video_info_from_url,
)

HOST = "https://www.douyin.com"
# 与 mediaspider common_params.browser_version=125.0.0.0 对齐
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class SearchChannelType(str, Enum):
    GENERAL = "aweme_general"
    VIDEO = "aweme_video_web"
    USER = "aweme_user_web"
    LIVE = "aweme_live"


class SearchSortType(int, Enum):
    GENERAL = 0
    MOST_LIKE = 1
    LATEST = 2


class SearchContentType(int, Enum):
    ALL = 0
    VIDEO = 1
    IMAGE = 2
    ARTICLE = 3


class PublishTimeType(int, Enum):
    UNLIMITED = 0
    ONE_DAY = 1
    ONE_WEEK = 7
    SIX_MONTH = 180


class DouyinClient:
    def __init__(
        self,
        cookie: Optional[str] = None,
        ms_token: str = "",
        timeout: int = 60,
        user_agent: str = DEFAULT_UA,
        *,
        account_name: str = "",
    ):
        if cookie is None:
            from platforms.common.cookies import load_primary_account

            acc = load_primary_account("dy", account_name=account_name)
            cookie = acc.cookie
            ms_token = ms_token or acc.ms_token
            if not account_name:
                account_name = acc.name
        self.timeout = timeout
        self.user_agent = user_agent
        self.session = requests.Session()
        self.webid = get_web_id()
        self.account_name = account_name or ""
        self.cookie = ""
        self.cookie_dict: Dict[str, str] = {}
        self.ms_token = ""
        self.headers: Dict[str, str] = {
            "User-Agent": self.user_agent,
            "Cookie": "",
            "Host": "www.douyin.com",
            "Origin": "https://www.douyin.com/",
            "Referer": "https://www.douyin.com/",
            "Content-Type": "application/json;charset=UTF-8",
        }
        self._cookie_pool: List[Any] = []
        self._cookie_idx = 0
        self._apply_cookie(cookie, ms_token=ms_token, name=self.account_name)

    def _apply_cookie(
        self,
        cookie: str,
        *,
        ms_token: str = "",
        name: str = "",
        refresh_webid: bool = False,
    ) -> None:
        self.cookie = cookie or ""
        self.cookie_dict = parse_cookie_str(self.cookie)
        self.ms_token = ms_token or ""
        if not self.ms_token:
            for part in self.cookie.split(";"):
                part = part.strip()
                if part.lower().startswith("mstoken="):
                    self.ms_token = part.split("=", 1)[1].strip()
                    break
        if name:
            self.account_name = name
        if refresh_webid:
            self.webid = get_web_id()
        self.headers["Cookie"] = self.cookie
        self.session = requests.Session()

    def set_cookie_pool(
        self,
        accounts: List[Any],
        *,
        start_name: str = "",
    ) -> None:
        """设置可轮换 cookie 池；连续风控时自动切号。"""
        self._cookie_pool = [a for a in (accounts or []) if getattr(a, "cookie", "")]
        if not self._cookie_pool:
            return
        self._cookie_idx = 0
        wanted = (start_name or self.account_name or "").strip()
        if wanted:
            for i, acc in enumerate(self._cookie_pool):
                name = str(getattr(acc, "name", "") or "")
                if name == wanted or wanted in (name, name.replace("dy_", "")):
                    self._cookie_idx = i
                    break
            else:
                try:
                    idx = int(wanted)
                    if 1 <= idx <= len(self._cookie_pool):
                        self._cookie_idx = idx - 1
                except ValueError:
                    pass
        acc = self._cookie_pool[self._cookie_idx]
        self._apply_cookie(
            acc.cookie,
            ms_token=getattr(acc, "ms_token", "") or "",
            name=str(getattr(acc, "name", "") or ""),
            refresh_webid=False,
        )

    def _rotate_cookie(self) -> bool:
        if len(self._cookie_pool) <= 1:
            return False
        import sys

        n = len(self._cookie_pool)
        for step in range(1, n):
            idx = (self._cookie_idx + step) % n
            acc = self._cookie_pool[idx]
            self._cookie_idx = idx
            self._apply_cookie(
                acc.cookie,
                ms_token=getattr(acc, "ms_token", "") or "",
                name=str(getattr(acc, "name", "") or ""),
                refresh_webid=True,
            )
            print(
                f"[dy] 风控切换 cookie → {self.account_name or f'dy_{idx+1}'}",
                file=sys.stderr,
                flush=True,
            )
            return True
        return False

    def _common_params(self) -> Dict[str, Any]:
        """对齐 mediaspider DouYinClient.__process_req_params common_params。"""
        params: Dict[str, Any] = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "version_code": "190600",
            "version_name": "19.6.0",
            "update_version_code": "170400",
            "pc_client_type": "1",
            "cookie_enabled": "true",
            "browser_language": "zh-CN",
            "browser_platform": "MacIntel",
            "browser_name": "Chrome",
            "browser_version": "125.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "os_name": "Mac OS",
            "os_version": "10.15.7",
            "cpu_core_num": "8",
            "device_memory": "8",
            "engine_version": "109.0",
            "platform": "PC",
            "screen_width": "2560",
            "screen_height": "1440",
            "effective_type": "4g",
            "round_trip_time": "50",
            "webid": self.webid,
        }
        # mediaspider 从 localStorage.xmst 取；这里用文件/环境变量兜底
        if self.ms_token:
            params["msToken"] = self.ms_token
        return params

    def _process_req_params(self, uri: str, params: Dict[str, Any]) -> None:
        params.update(self._common_params())
        query_string = urllib.parse.urlencode(params)
        # mediaspider：general/search 不加 a_bogus
        if "/v1/web/general/search" not in uri:
            params["a_bogus"] = get_a_bogus(
                query_string, self.user_agent, uri=uri
            )

    def _request(
        self,
        uri: str,
        params: Dict[str, Any],
        *,
        headers: Optional[Dict[str, str]] = None,
        retries: int = 2,
        _rotates_left: Optional[int] = None,
    ) -> Dict[str, Any]:
        import random
        import sys

        if _rotates_left is None:
            _rotates_left = max(0, len(self._cookie_pool) - 1)

        last_err: Optional[Exception] = None
        for attempt in range(max(1, retries + 1)):
            merged = dict(params)
            self._process_req_params(uri, merged)
            req_headers = dict(headers or self.headers)
            req_headers["Cookie"] = self.cookie
            resp = self.session.get(
                f"{HOST}{uri}",
                params=merged,
                headers=req_headers,
                timeout=self.timeout,
            )
            if resp.text in ("", "blocked"):
                last_err = RuntimeError("账号可能被风控（响应 blocked/空）")
            elif resp.status_code == 403 or "ArgusSecurityPlugin" in (
                resp.text or ""
            ):
                last_err = RuntimeError(
                    "请求被抖音 Argus 风控拦截（HTTP 403）。"
                    "可加大 --interval、换 cookie，或稍后再试。"
                )
            else:
                try:
                    data = resp.json()
                except Exception as exc:
                    raise RuntimeError(
                        f"非 JSON HTTP {resp.status_code}: {resp.text[:300]}"
                    ) from exc
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"HTTP {resp.status_code}: "
                        f"{json.dumps(data, ensure_ascii=False)[:400]}"
                    )
                status = data.get("status_code")
                if status in (0, None, "0"):
                    return data
                if str(status) == "2484":
                    # 搜索频率过高限流（"你搜得太多啦"）：不直接抛错，
                    # 进入长退避重试，退避耗尽后由下方 cookie 池轮换兜底。
                    last_err = RuntimeError(
                        f"接口错误 status_code=2484（搜索频率过高限流）: "
                        f"{json.dumps(data, ensure_ascii=False)[:300]}"
                    )
                    if attempt >= retries:
                        break
                    wait = min(300.0, 30.0 * (2**attempt)) + random.uniform(1.0, 5.0)
                    print(
                        f"[dy] 2484 搜索限流，等待 {wait:.0f}s 后重试 "
                        f"({attempt + 1}/{retries}) "
                        f"[{self.account_name or '?'}]",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(wait)
                    continue
                raise RuntimeError(
                    f"接口错误 status_code={status}: "
                    f"{json.dumps(data, ensure_ascii=False)[:400]}"
                )

            if attempt >= retries:
                break
            wait = min(45.0, 3.0 * (2**attempt)) + random.uniform(0.5, 1.5)
            print(
                f"[dy] 风控/空响应，{wait:.1f}s 后重试 "
                f"({attempt + 1}/{retries}) "
                f"[{self.account_name or '?'}] {uri}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(wait)

        if _rotates_left > 0 and self._rotate_cookie():
            time.sleep(2.0)
            return self._request(
                uri,
                params,
                headers=headers,
                retries=retries,
                _rotates_left=_rotates_left - 1,
            )
        assert last_err is not None
        raise last_err

    def search(
        self,
        keyword: str,
        offset: int = 0,
        count: int = 10,
        sort_type: SearchSortType = SearchSortType.GENERAL,
        publish_time: PublishTimeType = PublishTimeType.UNLIMITED,
        content_type: SearchContentType = SearchContentType.ALL,
        search_id: str = "",
        search_channel: SearchChannelType = SearchChannelType.GENERAL,
        _verify_rotates_left: Optional[int] = None,
    ) -> Dict[str, Any]:
        if _verify_rotates_left is None:
            _verify_rotates_left = max(0, len(self._cookie_pool) - 1)
        params: Dict[str, Any] = {
            "search_channel": search_channel.value,
            "enable_history": "1",
            "keyword": keyword,
            "search_source": "tab_search",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": "7378810571505847586",
            "offset": offset,
            "count": str(count),
            "need_filter_settings": "1",
            "list_type": "multi",
            "search_id": search_id,
        }
        if (
            sort_type != SearchSortType.GENERAL
            or publish_time != PublishTimeType.UNLIMITED
            or content_type != SearchContentType.ALL
        ):
            params["filter_selected"] = json.dumps(
                {
                    "sort_type": str(int(sort_type)),
                    "publish_time": str(int(publish_time)),
                    "content_type": str(int(content_type)),
                }
            )
            params["is_filter_search"] = 1
            params["search_source"] = "tab_search"

        referer_url = (
            f"https://www.douyin.com/search/{keyword}"
            f"?aid=f594bbd9-a0e2-4651-9319-ebe3cb6298c1&type=general"
        )
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(referer_url, safe=":/")

        raw = self._request(
            "/aweme/v1/web/general/search/single/",
            params,
            headers=headers,
        )
        nil = raw.get("search_nil_info") or {}
        nil_type = nil.get("search_nil_type") or nil.get("search_nil_item") or ""
        if nil_type == "verify_check" and not (raw.get("data") or []):
            import sys

            if _verify_rotates_left > 0 and self._rotate_cookie():
                print(
                    f"[dy] 搜索 verify_check，已切 cookie → "
                    f"{self.account_name or '?'}",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(2.0)
                return self.search(
                    keyword,
                    offset=offset,
                    count=count,
                    sort_type=sort_type,
                    publish_time=publish_time,
                    content_type=content_type,
                    search_id=search_id,
                    search_channel=search_channel,
                    _verify_rotates_left=_verify_rotates_left - 1,
                )
            raise RuntimeError(
                "搜索被抖音风控拦截（search_nil_type=verify_check）。\n"
                "mediaspider 同路径依赖 Playwright 浏览器环境通过验证；"
                "纯 cookie 请求仍会被拦。请在浏览器完成搜索页验证后重导 cookie，"
                "或改用 creator/detail 接口验证 a_bogus。"
            )
        contents = normalize_search_items(raw, source_keyword=keyword)
        return {
            "contents": contents,
            "has_more": bool(raw.get("has_more")),
            "cursor": raw.get("cursor"),
            "search_id": (raw.get("extra") or {}).get("logid") or search_id,
            "search_nil": nil,
        }

    def search_pages(
        self,
        keyword: str,
        *,
        max_pages: int = 1,
        page_size: int = 10,
        sort_type: SearchSortType = SearchSortType.GENERAL,
        publish_time: PublishTimeType = PublishTimeType.UNLIMITED,
        content_type: SearchContentType = SearchContentType.ALL,
        page_interval: float = 1.5,
        min_images: int = 0,
        min_posts: int = 0,
        images_only: bool = False,
    ) -> Dict[str, Any]:
        from platforms.douyin.excel_export import count_content_images_estimate

        all_contents: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        search_id = ""
        offset = 0
        pages = 0
        has_more = True
        while pages < max_pages and has_more:
            page = self.search(
                keyword,
                offset=offset,
                count=page_size,
                sort_type=sort_type,
                publish_time=publish_time,
                content_type=content_type,
                search_id=search_id,
            )
            contents = page.get("contents") or []
            if not contents:
                break
            for item in contents:
                if images_only and item.get("type") != "image":
                    continue
                aid = str(item.get("aweme_id") or "")
                if aid and aid in seen_ids:
                    continue
                if aid:
                    seen_ids.add(aid)
                all_contents.append(item)
            pages += 1
            search_id = page.get("search_id") or search_id
            has_more = bool(page.get("has_more"))
            offset = int(page.get("cursor") or (offset + page_size))
            if min_posts > 0 and len(all_contents) >= min_posts:
                break
            if min_images > 0 and count_content_images_estimate(all_contents) >= min_images:
                break
            if pages < max_pages and has_more and page_interval > 0:
                # 随机抖动翻页间隔，模拟真人节奏，降低触发 2484 搜索限流概率
                import random

                time.sleep(page_interval + random.uniform(0.2, 0.8))
        return crawl_result(
            crawl_type="search",
            keywords=[keyword],
            contents=all_contents,
            pages_fetched=pages,
            has_more=has_more,
            search_id=search_id,
        )

    def get_user_info(self, sec_user_id: str) -> Dict[str, Any]:
        params = {
            "sec_user_id": sec_user_id,
            "publish_video_strategy_type": 2,
            "personal_center_strategy": 1,
        }
        return self._request("/aweme/v1/web/user/profile/other/", params)

    def get_user_posts(
        self,
        sec_user_id: str,
        max_cursor: str = "",
        count: int = 10,
    ) -> Dict[str, Any]:
        params = {
            "sec_user_id": sec_user_id,
            "count": count,
            "max_cursor": max_cursor,
            "locate_query": "false",
            "publish_video_strategy_type": 2,
        }
        return self._request("/aweme/v1/web/aweme/post/", params)

    def get_aweme_detail(self, aweme_id: str) -> Dict[str, Any]:
        params = {"aweme_id": aweme_id}
        headers = copy.copy(self.headers)
        headers.pop("Origin", None)
        res = self._request("/aweme/v1/web/aweme/detail/", params, headers=headers)
        return res.get("aweme_detail") or {}

    def get_aweme_comments(
        self,
        aweme_id: str,
        *,
        cursor: int = 0,
        count: int = 20,
    ) -> Dict[str, Any]:
        """一级评论：GET /aweme/v1/web/comment/list/。"""
        params = {
            "aweme_id": aweme_id,
            "cursor": cursor,
            "count": count,
            "item_type": 0,
        }
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(
            f"https://www.douyin.com/video/{aweme_id}",
            safe=":/",
        )
        return self._request("/aweme/v1/web/comment/list/", params, headers=headers)

    def get_sub_comments(
        self,
        aweme_id: str,
        comment_id: str,
        *,
        cursor: int = 0,
        count: int = 20,
    ) -> Dict[str, Any]:
        """二级评论：GET /aweme/v1/web/comment/list/reply/。"""
        params = {
            "comment_id": comment_id,
            "cursor": cursor,
            "count": count,
            "item_type": 0,
            "item_id": aweme_id,
        }
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(
            f"https://www.douyin.com/video/{aweme_id}",
            safe=":/",
        )
        return self._request(
            "/aweme/v1/web/comment/list/reply/",
            params,
            headers=headers,
        )

    def get_aweme_all_comments(
        self,
        aweme_id: str,
        *,
        creator_sec_uid: str = "",
        max_comments: int = 0,
        interval: float = 0.8,
        progress: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """拉某作品全部一级评论 + 二级回复，挂成树（replies）。

        max_comments<=0 表示不限制条数（一级+二级合计）。
        """
        import sys

        unlimited = max_comments <= 0
        out: List[Dict[str, Any]] = []
        total = 0
        cursor = 0
        has_more = 1
        page_i = 0
        max_pages = 500  # 防死循环
        while has_more and (unlimited or total < max_comments) and page_i < max_pages:
            page_i += 1
            prev_cursor = cursor
            page = self.get_aweme_comments(aweme_id, cursor=cursor, count=20)
            raw_list = page.get("comments") or []
            new_top = 0
            for raw in raw_list:
                if not unlimited and total >= max_comments:
                    break
                item = normalize_comment(
                    raw,
                    aweme_id=aweme_id,
                    creator_sec_uid=creator_sec_uid,
                )
                if not item:
                    continue
                total += 1
                new_top += 1
                # 已内嵌的少量二级
                embedded = raw.get("reply_comment") or raw.get("reply_comments") or []
                parent_id = item["comment_id"]
                parent_text = item["text"]
                parent_name = item["display_name"]
                for sub in embedded:
                    if not unlimited and total >= max_comments:
                        break
                    reply = normalize_comment(
                        sub,
                        aweme_id=aweme_id,
                        creator_sec_uid=creator_sec_uid,
                        parent_comment_id=parent_id,
                        reply_to_comment_id=parent_id,
                        reply_to_text=parent_text,
                        reply_to_display_name=parent_name,
                    )
                    if reply:
                        rid = str(
                            sub.get("reply_id") or sub.get("reply_to_reply_id") or ""
                        )
                        if rid and rid not in ("0", parent_id):
                            reply["reply_to_comment_id"] = rid
                        item["replies"].append(reply)
                        total += 1

                need_reply = int(item.get("reply_count") or 0) > len(item["replies"])
                if need_reply and (unlimited or total < max_comments):
                    try:
                        more = self._fetch_all_replies(
                            aweme_id,
                            parent_id,
                            creator_sec_uid=creator_sec_uid,
                            parent_text=parent_text,
                            parent_name=parent_name,
                            already={r["comment_id"] for r in item["replies"]},
                            max_comments=(
                                0 if unlimited else max(0, max_comments - total)
                            ),
                            interval=interval,
                        )
                        item["replies"].extend(more)
                        total += len(more)
                    except Exception as exc:
                        item["replies_error"] = str(exc)[:200]

                out.append(item)
                if callable(progress):
                    progress(total, item["comment_id"])

            has_more = int(page.get("has_more") or 0)
            cursor = int(page.get("cursor") or 0)
            if page_i == 1 or page_i % 5 == 0 or not has_more:
                print(
                    f"[dy]   …一级页 {page_i} 累计评论 {total} "
                    f"(本页+{new_top})",
                    file=sys.stderr,
                    flush=True,
                )
            if not raw_list or new_top == 0:
                break
            if cursor == prev_cursor and has_more:
                break
            if has_more and (unlimited or total < max_comments) and interval > 0:
                time.sleep(interval)
        return out

    def _fetch_all_replies(
        self,
        aweme_id: str,
        comment_id: str,
        *,
        creator_sec_uid: str,
        parent_text: str,
        parent_name: str,
        already: Optional[set] = None,
        max_comments: int = 0,
        interval: float = 0.5,
    ) -> List[Dict[str, Any]]:
        unlimited = max_comments <= 0
        seen = set(already or set())
        out: List[Dict[str, Any]] = []
        cursor = 0
        has_more = 1
        page_i = 0
        max_pages = 200
        while has_more and (unlimited or len(out) < max_comments) and page_i < max_pages:
            page_i += 1
            prev_cursor = cursor
            page = self.get_sub_comments(
                aweme_id, comment_id, cursor=cursor, count=20
            )
            raw_list = page.get("comments") or page.get("reply_list") or []
            new_n = 0
            for raw in raw_list:
                if not unlimited and len(out) >= max_comments:
                    break
                cid = str(raw.get("cid") or raw.get("comment_id") or "")
                if not cid or cid in seen:
                    continue
                reply_to_id = str(
                    raw.get("reply_id")
                    or raw.get("reply_to_reply_id")
                    or comment_id
                )
                if reply_to_id in ("0", ""):
                    reply_to_id = comment_id
                reply_to_text = parent_text
                reply_to_name = parent_name
                if reply_to_id != comment_id:
                    for prev in out:
                        if prev["comment_id"] == reply_to_id:
                            reply_to_text = prev.get("text") or reply_to_text
                            reply_to_name = prev.get("display_name") or reply_to_name
                            break
                reply = normalize_comment(
                    raw,
                    aweme_id=aweme_id,
                    creator_sec_uid=creator_sec_uid,
                    parent_comment_id=comment_id,
                    reply_to_comment_id=reply_to_id,
                    reply_to_text=reply_to_text,
                    reply_to_display_name=reply_to_name,
                )
                if reply:
                    seen.add(cid)
                    out.append(reply)
                    new_n += 1
            has_more = int(page.get("has_more") or 0)
            cursor = int(page.get("cursor") or 0)
            # 本页无新数据 / cursor 不动 → 防死循环
            if not raw_list or new_n == 0:
                break
            if cursor == prev_cursor and has_more:
                break
            if has_more and (unlimited or len(out) < max_comments) and interval > 0:
                time.sleep(interval)
        return out

    def resolve_creator_sec_uid(self, target: str) -> str:
        """主页 URL / sec_uid / 抖音号 / 昵称 → sec_user_id。"""
        text = (target or "").strip()
        if not text:
            raise ValueError("空的博主目标")
        if text.startswith("MS4wLjABAAAA"):
            return text.split("?")[0]
        if text.startswith("http") or "douyin.com" in text:
            return parse_sec_user_id(text)
        try:
            bundle = self.get_profile_bundle(text)
        except Exception as exc:
            hint = (
                f"无法通过「{text}」解析博主（用户搜索常被风控）。\n"
                "请改用主页链接，例如：\n"
                "  python main.py dy creator "
                "'https://www.douyin.com/user/MS4wLjABAAAA...'\n"
                "可先打开抖音网页复制地址栏 /user/ 后的链接。"
            )
            raise RuntimeError(f"{hint}\n原始错误: {exc}") from exc
        creators = bundle.get("creators") or []
        if not creators:
            raise RuntimeError(
                f"未找到抖音号/用户: {text}。"
                "请改用主页 URL（/user/MS4wLjABAAAA...）。"
            )
        sec = str(creators[0].get("sec_uid") or "").strip()
        if not sec:
            url = str(creators[0].get("profile_url") or "")
            if "/user/" in url:
                sec = parse_sec_user_id(url)
        if not sec:
            raise RuntimeError(f"无法解析博主 sec_uid: {text}")
        return sec

    def get_self_profile(self) -> Dict[str, Any]:
        """当前登录用户资料（含抖音号 / sec_uid）。"""
        headers = copy.copy(self.headers)
        headers.pop("Origin", None)
        res = self._request(
            "/aweme/v1/web/user/profile/self/",
            {},
            headers=headers,
        )
        return res.get("user") or {}

    def search_users(
        self,
        keyword: str,
        *,
        offset: int = 0,
        count: int = 10,
        search_id: str = "",
    ) -> Dict[str, Any]:
        """用户搜索（含抖音号精确匹配），search_channel=aweme_user_web。"""
        params: Dict[str, Any] = {
            "search_channel": SearchChannelType.USER.value,
            "enable_history": "1",
            "keyword": keyword,
            "search_source": "tab_search",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": "7378810571505847586",
            "offset": offset,
            "count": str(count),
            "need_filter_settings": "1",
            "list_type": "single",
            "search_id": search_id,
        }
        referer_url = (
            f"https://www.douyin.com/search/{keyword}"
            f"?aid=f594bbd9-a0e2-4651-9319-ebe3cb6298c1&type=user"
        )
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(referer_url, safe=":/")
        return self._request(
            "/aweme/v1/web/general/search/single/",
            params,
            headers=headers,
        )

    def get_profile_bundle(self, unique_id_or_empty: str = "") -> Dict[str, Any]:
        """根据登录态或抖音号解析主页，并补齐简介/粉丝等资料。

        - 空参数：profile/self
        - 有参数：用户搜索定位 sec_uid 后，再拉 profile/other 详情
        """
        handle = (unique_id_or_empty or "").strip()
        if not handle:
            user = self.get_self_profile()
            if not user:
                raise RuntimeError("profile/self 未返回用户，请检查 cookie")
            creator = normalize_creator(user.get("sec_uid") or "", user)
            if not creator:
                raise RuntimeError("无法归一化当前用户资料")
            creator["is_self"] = True
            creator["sec_uid"] = user.get("sec_uid") or ""
            return crawl_result(
                crawl_type="profile",
                creator_url=creator.get("profile_url"),
                creators=[creator],
            )

        raw = self.search_users(handle)
        users: List[Dict[str, Any]] = []
        for block in raw.get("data") or []:
            for item in block.get("user_list") or []:
                info = item.get("user_info") or item
                if info:
                    users.append(info)

        exact = [
            u
            for u in users
            if str(u.get("unique_id") or "") == handle
            or str(u.get("short_id") or "") == handle
        ]
        chosen = exact or users
        creators: List[Dict[str, Any]] = []
        for user in chosen:
            sec = user.get("sec_uid") or user.get("sec_user_id") or ""
            if not sec:
                continue
            detail = user
            try:
                profile_res = self.get_user_info(sec)
                if profile_res:
                    detail = profile_res.get("user") or profile_res
            except Exception:
                detail = user
            creator = normalize_creator(sec, detail)
            if creator:
                creator["sec_uid"] = sec
                creator["is_self"] = False
                creators.append(creator)
        if not creators:
            raise RuntimeError(f"未找到抖音号/用户: {handle}")
        return crawl_result(
            crawl_type="profile",
            creator_url=creators[0].get("profile_url"),
            creators=creators,
            keyword=handle,
            exact_match=bool(exact),
        )

    def resolve_short_url(self, short_url: str) -> str:
        """解析 v.douyin.com 短链，返回 Location（对齐 mediaspider）。"""
        resp = self.session.get(
            short_url,
            headers={
                "User-Agent": DEFAULT_UA,
                "Cookie": self.cookie,
            },
            allow_redirects=False,
            timeout=10,
        )
        if resp.status_code in (301, 302, 303, 307, 308):
            return resp.headers.get("Location") or ""
        return ""

    def get_detail_bundle(self, url_or_id: str) -> Dict[str, Any]:
        """单条作品详情（对齐 mediaspider crawl_type=detail）。"""
        info = parse_video_info_from_url(url_or_id)
        aweme_id = info["aweme_id"]
        if info["url_type"] == "short":
            resolved = self.resolve_short_url(url_or_id)
            if not resolved:
                raise ValueError(f"短链解析失败: {url_or_id}")
            info = parse_video_info_from_url(resolved)
            aweme_id = info["aweme_id"]
        if not aweme_id:
            raise ValueError(f"无法解析 aweme_id: {url_or_id}")
        raw = self.get_aweme_detail(aweme_id)
        content = normalize_aweme(raw)
        content_url = (
            url_or_id
            if "://" in url_or_id
            else (content or {}).get("aweme_url")
            or f"https://www.douyin.com/video/{aweme_id}"
        )
        return crawl_result(
            crawl_type="detail",
            content_url=content_url,
            contents=[content] if content else [],
        )

    def get_creator_bundle(
        self,
        url_or_id: str,
        *,
        max_notes: int = 10,
        interval: float = 1.0,
        with_posts: bool = True,
        with_comments: bool = False,
        max_comments: int = 0,
        progress: bool = True,
        resume: bool = True,
        checkpoint_path: Optional[str] = None,
        clear_checkpoint: bool = False,
        refetch_posts: bool = False,
    ) -> Dict[str, Any]:
        """博主资料 + 作品（可选评论挂在每条作品下）。

        支持断点续爬（checkpoint）与 cookie 池风控轮换。
        refetch_posts=True 时重拉作品列表（补封面等），按 aweme_id 合并已有评论。
        """
        import sys
        from pathlib import Path

        from platforms.common.store import (
            creator_checkpoint_path,
            write_json,
        )

        def log(msg: str) -> None:
            if progress:
                print(f"[dy] {msg}", file=sys.stderr, flush=True)

        sec_user_id = self.resolve_creator_sec_uid(url_or_id)
        ckpt = Path(checkpoint_path) if checkpoint_path else creator_checkpoint_path(
            "dy", sec_user_id
        )
        if clear_checkpoint and ckpt.is_file():
            ckpt.unlink()
            log(f"已清除断点 {ckpt}")

        state: Dict[str, Any] = {}
        if resume and ckpt.is_file():
            try:
                state = json.loads(ckpt.read_text(encoding="utf-8"))
            except Exception as exc:
                log(f"断点读取失败，重新开始: {exc}")
                state = {}
            if state.get("sec_uid") and state.get("sec_uid") != sec_user_id:
                log("断点 sec_uid 不匹配，忽略旧断点")
                state = {}
            elif state:
                log(
                    f"从断点续爬 {ckpt.name} "
                    f"(作品 {len(state.get('contents') or [])}，"
                    f"评论进度 {state.get('next_comment_idx', 0)})"
                )

        def save_ckpt(**extra: Any) -> None:
            payload = {
                "sec_uid": sec_user_id,
                "creators": creators,
                "contents": contents,
                "posts_done": posts_done,
                "max_cursor": cursor,
                "has_more_posts": bool(has_more),
                "next_comment_idx": next_comment_idx,
                "total_comments": total_comments,
                "cookie_account": self.account_name,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            payload.update(extra)
            write_json(payload, ckpt)

        log(f"解析博主 sec_uid={sec_user_id[:24]}... cookie={self.account_name or '?'}")
        if state.get("creators") and not refetch_posts:
            creators = state["creators"]
            creator = creators[0] if creators else None
        else:
            profile = self.get_user_info(sec_user_id)
            creator = normalize_creator(sec_user_id, profile)
            if creator:
                creator["sec_uid"] = sec_user_id
            creators = [creator] if creator else []
        works_total = int((creator or {}).get("works_count") or 0)
        log(
            f"博主={(creator or {}).get('display_name') or '?'} "
            f"作品数≈{works_total or '?'}"
        )
        if not with_posts:
            return crawl_result(
                crawl_type="creator",
                creator_url=f"https://www.douyin.com/user/{sec_user_id}",
                creators=creators,
            )

        old_contents: List[Dict[str, Any]] = list(state.get("contents") or [])
        # 兼容旧断点：已有评论的标为完成
        for it in old_contents:
            if it.get("comments_done"):
                continue
            if it.get("comments_error"):
                continue
            if it.get("comments_fetched") is not None or (
                isinstance(it.get("comments"), list) and it.get("comments")
            ):
                it["comments_done"] = True

        comment_keep_keys = (
            "comments",
            "comments_done",
            "comments_fetched",
            "comments_error",
            "replies_error",
        )

        def _comment_side(old: Dict[str, Any]) -> Dict[str, Any]:
            return {k: old[k] for k in comment_keep_keys if k in old}

        old_by_id = {
            str(x.get("aweme_id") or ""): x
            for x in old_contents
            if x.get("aweme_id")
        }

        if refetch_posts:
            kept = sum(
                1
                for x in old_contents
                if x.get("comments_done") and not x.get("comments_error")
            )
            log(f"重爬作品列表（保留已完成评论 {kept} 条作品）")
            contents = []
            cursor = ""
            has_more = 1
            posts_done = False
            next_comment_idx = 0
            total_comments = sum(
                int(it.get("comments_fetched") or 0) for it in old_contents
            )
        else:
            contents = list(old_contents)
            cursor = str(state.get("max_cursor") or "")
            has_more = int(
                state.get("has_more_posts") if "has_more_posts" in state else 1
            )
            posts_done = bool(state.get("posts_done"))
            next_comment_idx = int(state.get("next_comment_idx") or 0)
            total_comments = int(state.get("total_comments") or 0)
            if contents and total_comments == 0:
                total_comments = sum(
                    int(it.get("comments_fetched") or 0) for it in contents
                )

        page_i = 0
        try:
            if not posts_done:
                while has_more and len(contents) < max_notes:
                    page_i += 1
                    page = self.get_user_posts(sec_user_id, max_cursor=cursor)
                    aweme_list = page.get("aweme_list") or []
                    seen = {
                        str(x.get("aweme_id") or "")
                        for x in contents
                        if x.get("aweme_id")
                    }
                    added = 0
                    for aweme in aweme_list:
                        item = normalize_aweme(aweme)
                        if not item:
                            continue
                        aid = str(item.get("aweme_id") or "")
                        if aid and aid in seen:
                            continue
                        old = old_by_id.get(aid) if aid else None
                        if old:
                            item.update(_comment_side(old))
                        else:
                            item["comments"] = []
                            item["comments_done"] = False
                        contents.append(item)
                        added += 1
                        if len(contents) >= max_notes:
                            break
                    has_more = int(page.get("has_more") or 0)
                    cursor = str(page.get("max_cursor") or "")
                    with_cover = sum(1 for x in contents if x.get("cover_url"))
                    log(
                        f"作品进度 {len(contents)}"
                        f"{f'/{works_total}' if works_total else ''} "
                        f"(第{page_i}页, +{added}条, 封面{with_cover}) "
                        f"cookie={self.account_name or '?'}"
                    )
                    save_ckpt()
                    if not aweme_list:
                        break
                    if has_more and len(contents) < max_notes and interval > 0:
                        time.sleep(interval)
                posts_done = True
                # 重爬后若旧作品未再出现在列表，仍挂在末尾以免丢评论
                if refetch_posts and old_by_id:
                    have = {
                        str(x.get("aweme_id") or "")
                        for x in contents
                        if x.get("aweme_id")
                    }
                    orphans = [
                        old_by_id[k]
                        for k in old_by_id
                        if k and k not in have
                    ]
                    if orphans:
                        log(f"保留列表外旧作品 {len(orphans)} 条（含评论）")
                        contents.extend(orphans)
                save_ckpt()
                log(
                    f"作品列表完成，共 {len(contents)} 条，"
                    f"含封面 {sum(1 for x in contents if x.get('cover_url'))}"
                )

            if with_comments and contents:
                n = len(contents)
                for idx, item in enumerate(contents):
                    if item.get("comments_done") and not item.get("comments_error"):
                        continue
                    aweme_id = str(item.get("aweme_id") or "")
                    next_comment_idx = idx
                    if not aweme_id:
                        item["comments_done"] = True
                        item.pop("comments_error", None)
                        save_ckpt()
                        continue
                    title = (item.get("title") or item.get("desc") or "")[:30]
                    log(
                        f"评论 [{idx + 1}/{n}] {aweme_id} {title!r} "
                        f"cookie={self.account_name or '?'}"
                    )
                    try:
                        comments = self.get_aweme_all_comments(
                            aweme_id,
                            creator_sec_uid=sec_user_id,
                            max_comments=max_comments,
                            interval=max(0.4, interval * 0.6),
                        )
                        item["comments"] = comments
                        item.pop("comments_error", None)
                        cnt = sum(1 + len(c.get("replies") or []) for c in comments)
                        item["comments_fetched"] = cnt
                        item["comments_done"] = True
                        total_comments = sum(
                            int(x.get("comments_fetched") or 0) for x in contents
                        )
                        creator_replies = sum(
                            1
                            for c in comments
                            for x in ([c] + (c.get("replies") or []))
                            if x.get("is_creator")
                        )
                        log(
                            f"  → 一级 {len(comments)} / 合计 {cnt} "
                            f"/ 博主回复 {creator_replies}"
                        )
                    except Exception as exc:
                        item["comments"] = item.get("comments") or []
                        item["comments_error"] = str(exc)[:200]
                        item["comments_done"] = False
                        log(f"  → 失败: {exc}")
                    save_ckpt()
                    if interval > 0:
                        time.sleep(interval)
                next_comment_idx = n
                save_ckpt()
                log(f"评论完成，合计 {total_comments} 条")
        except KeyboardInterrupt:
            save_ckpt()
            log(f"已保存断点，下次加同样命令即可续爬: {ckpt}")
            raise

        result = crawl_result(
            crawl_type="creator",
            creator_url=f"https://www.douyin.com/user/{sec_user_id}",
            contents=contents,
            creators=creators,
            comments=[],
            has_more=bool(has_more),
            max_cursor=cursor,
            comments_fetched=total_comments,
            comment_count=total_comments,
            checkpoint=str(ckpt),
            cookie_account=self.account_name,
        )
        # 完成后保留断点文件便于核对，标记完成
        save_ckpt(completed=True)
        return result
