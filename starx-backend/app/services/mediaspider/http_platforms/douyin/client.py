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
from typing import Any, Callable, Dict, List, Optional

import requests

from .normalize import (
    crawl_result,
    normalize_aweme,
    normalize_creator,
    normalize_search_items,
)
from .help import (
    device_fingerprint_from_cookie,
    generate_ms_token,
    get_a_bogus,
    parse_cookie_str,
    parse_sec_user_id,
    parse_video_info_from_url,
    webid_from_cookie,
)
from . import search_gate

HOST = "https://www.douyin.com"
# 抖音综合搜索实测：count>10 或 list_type=single 更容易 verify_check
_SEARCH_PAGE_SIZE_MAX = 10
# verify_check 后同 Cookie 冷却；词间最小间隔见 search_gate
_SEARCH_VERIFY_RETRY_SLEEP_SEC = 8.0
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


class PublishTimeType(int, Enum):
    UNLIMITED = 0
    ONE_DAY = 1
    ONE_WEEK = 7
    SIX_MONTH = 180


def _search_page_referer(keyword: str, *, result_type: str = "general") -> str:
    """构建搜索页 Referer：只编码 path 中的关键词，保留 ?&=。"""

    path = urllib.parse.quote(str(keyword or ""), safe="")
    return (
        f"{HOST}/search/{path}"
        f"?aid=f594bbd9-a0e2-4651-9319-ebe3cb6298c1&type={result_type}"
    )


class DouyinClient:
    def __init__(
        self,
        cookie: Optional[str] = None,
        ms_token: str = "",
        timeout: int = 60,
        user_agent: str = DEFAULT_UA,
        *,
        account_name: str = "",
        proxies: Optional[Dict[str, str]] = None,
    ):
        if cookie is None:
            from ..common.cookies import load_primary_account

            acc = load_primary_account("dy", account_name=account_name)
            cookie = acc.cookie
            ms_token = ms_token or acc.ms_token
        self.cookie = cookie
        self.cookie_dict = parse_cookie_str(cookie)
        self.ms_token = (ms_token or "").strip() or generate_ms_token()
        self.timeout = timeout
        self.user_agent = user_agent
        self.proxies = dict(proxies or {})
        self.session = requests.Session()
        if self.proxies:
            self.session.proxies.update(self.proxies)
        self.webid = webid_from_cookie(self.cookie_dict)
        self._device_fp = device_fingerprint_from_cookie(self.cookie_dict)
        self.account_name = account_name or ""
        self.headers = {
            "User-Agent": self.user_agent,
            "Cookie": self.cookie,
            "Host": "www.douyin.com",
            "Origin": "https://www.douyin.com/",
            "Referer": "https://www.douyin.com/",
            "Content-Type": "application/json;charset=UTF-8",
        }

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
            # 每次请求刷新占位 msToken，贴近浏览器动态 xmst
            "msToken": self.ms_token or generate_ms_token(),
        }
        params.update(self._device_fp)
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
    ) -> Dict[str, Any]:
        merged = dict(params)
        self._process_req_params(uri, merged)
        req_headers = headers or self.headers
        if self.proxies:
            self.session.proxies.update(self.proxies)
        resp = self.session.get(
            f"{HOST}{uri}",
            params=merged,
            headers=req_headers,
            timeout=self.timeout,
        )
        if resp.text in ("", "blocked"):
            raise RuntimeError("账号可能被风控（响应 blocked/空）")
        try:
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"非 JSON HTTP {resp.status_code}: {resp.text[:300]}"
            ) from exc
        if resp.status_code != 200:
            raise RuntimeError(
                f"HTTP {resp.status_code}: {json.dumps(data, ensure_ascii=False)[:400]}"
            )
        status = data.get("status_code")
        if status not in (0, None, "0"):
            raise RuntimeError(
                f"接口错误 status_code={status}: "
                f"{json.dumps(data, ensure_ascii=False)[:400]}"
            )
        return data

    def _search_once(
        self,
        keyword: str,
        *,
        offset: int,
        page_size: int,
        sort_type: SearchSortType,
        publish_time: PublishTimeType,
        search_id: str,
        search_channel: SearchChannelType,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "search_channel": search_channel.value,
            "enable_history": "1",
            "keyword": keyword,
            "search_source": "tab_search",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": "7378810571505847586",
            "offset": offset,
            "count": str(page_size),
            "need_filter_settings": "1",
            "list_type": "multi",
            "search_id": search_id,
        }
        if (
            sort_type != SearchSortType.GENERAL
            or publish_time != PublishTimeType.UNLIMITED
        ):
            params["filter_selected"] = json.dumps(
                {
                    "sort_type": str(int(sort_type)),
                    "publish_time": str(int(publish_time)),
                }
            )
            params["is_filter_search"] = 1
            params["search_source"] = "tab_search"

        # 每次搜索换新 msToken，避免空/过期 token 连打
        self.ms_token = generate_ms_token()
        headers = copy.copy(self.headers)
        headers["Referer"] = _search_page_referer(keyword, result_type="general")
        return self._request(
            "/aweme/v1/web/general/search/single/",
            params,
            headers=headers,
        )

    @staticmethod
    def _raise_verify_check(*, cooldown_sec: float) -> None:
        wait = max(1, int(cooldown_sec))
        raise RuntimeError(
            "搜索被抖音风控拦截（search_nil_type=verify_check）。"
            f"同一登录态已进入约 {wait}s 冷却；请勿连打搜索。"
            "可改用主页/详情采集，或重新扫码导出登录态后再搜。"
        )

    def search(
        self,
        keyword: str,
        offset: int = 0,
        count: int = 10,
        sort_type: SearchSortType = SearchSortType.GENERAL,
        publish_time: PublishTimeType = PublishTimeType.UNLIMITED,
        search_id: str = "",
        search_channel: SearchChannelType = SearchChannelType.GENERAL,
    ) -> Dict[str, Any]:
        page_size = max(1, min(int(count or 10), _SEARCH_PAGE_SIZE_MAX))
        search_gate.wait_for_search_slot(self.cookie)

        raw = self._search_once(
            keyword,
            offset=offset,
            page_size=page_size,
            sort_type=sort_type,
            publish_time=publish_time,
            search_id=search_id,
            search_channel=search_channel,
        )
        nil = raw.get("search_nil_info") or {}
        nil_type = nil.get("search_nil_type") or nil.get("search_nil_item") or ""
        if nil_type == "verify_check" and not (raw.get("data") or []):
            # 短退避 + 新 token 再试一次；仍失败则进入跨进程冷却
            time.sleep(_SEARCH_VERIFY_RETRY_SLEEP_SEC)
            self.ms_token = generate_ms_token()
            search_gate.wait_for_search_slot(self.cookie)
            raw = self._search_once(
                keyword,
                offset=offset,
                page_size=page_size,
                sort_type=sort_type,
                publish_time=publish_time,
                search_id=search_id,
                search_channel=search_channel,
            )
            nil = raw.get("search_nil_info") or {}
            nil_type = nil.get("search_nil_type") or nil.get("search_nil_item") or ""
            if nil_type == "verify_check" and not (raw.get("data") or []):
                until = search_gate.mark_verify_check(self.cookie)
                self._raise_verify_check(cooldown_sec=max(0.0, until - time.time()))

        contents = normalize_search_items(raw, source_keyword=keyword)
        search_gate.mark_search_success(self.cookie)
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
        page_interval: float = 6.0,
    ) -> Dict[str, Any]:
        page_size = max(1, min(int(page_size or 10), _SEARCH_PAGE_SIZE_MAX))
        all_contents: List[Dict[str, Any]] = []
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
                search_id=search_id,
            )
            contents = page.get("contents") or []
            if not contents:
                break
            all_contents.extend(contents)
            pages += 1
            search_id = page.get("search_id") or search_id
            has_more = bool(page.get("has_more"))
            offset = int(page.get("cursor") or (offset + page_size))
            if pages < max_pages and has_more and page_interval > 0:
                time.sleep(page_interval)
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
            "count": str(max(1, min(int(count or 10), _SEARCH_PAGE_SIZE_MAX))),
            "need_filter_settings": "1",
            "list_type": "single",
            "search_id": search_id,
        }
        headers = copy.copy(self.headers)
        headers["Referer"] = _search_page_referer(keyword, result_type="user")
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
        on_creator: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Dict[str, Any]:
        creator_target = url_or_id
        if "v.douyin.com" in creator_target:
            creator_target = self.resolve_short_url(creator_target)
            if not creator_target:
                raise ValueError(f"短链解析失败: {url_or_id}")
        sec_user_id = parse_sec_user_id(creator_target)
        profile = self.get_user_info(sec_user_id)
        creator = normalize_creator(sec_user_id, profile)
        creators = [creator] if creator else []
        if creator and on_creator is not None:
            on_creator(creator)
        if not with_posts:
            return crawl_result(
                crawl_type="creator",
                creator_url=f"https://www.douyin.com/user/{sec_user_id}",
                creators=creators,
            )

        contents: List[Dict[str, Any]] = []
        cursor = ""
        has_more = 1
        while has_more and len(contents) < max_notes:
            page = self.get_user_posts(sec_user_id, max_cursor=cursor)
            aweme_list = page.get("aweme_list") or []
            for aweme in aweme_list:
                item = normalize_aweme(aweme)
                if item:
                    contents.append(item)
                if len(contents) >= max_notes:
                    break
            has_more = int(page.get("has_more") or 0)
            cursor = str(page.get("max_cursor") or "")
            if not aweme_list:
                break
            if has_more and len(contents) < max_notes and interval > 0:
                time.sleep(interval)
        return crawl_result(
            crawl_type="creator",
            creator_url=f"https://www.douyin.com/user/{sec_user_id}",
            contents=contents,
            creators=creators,
            has_more=bool(has_more),
            max_cursor=cursor,
        )
