# -*- coding: utf-8 -*-
"""
小红书 API 客户端（搜索 + 博主 + 单条）

接口：
- POST https://so.xiaohongshu.com/api/sns/web/v2/search/notes  关键词搜索（浏览器现行）
- POST /api/sns/web/v1/feed              单条笔记详情
- GET  /api/sns/web/v1/user_posted       博主笔记列表（edith）
- GET  主站 /user/profile/{user_id}      博主主页信息（HTML 解析）
- GET  /api/sns/web/v2/user/me           当前登录用户（edith）
"""

from __future__ import annotations

import json
import random
import re
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, urlparse

import requests

from .help import build_sign_string, sign_headers

HOST = "https://edith.xiaohongshu.com"
SEARCH_HOST = "https://so.xiaohongshu.com"
DOMAIN = "https://www.xiaohongshu.com"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)
SEARCH_NOTES_URI = "/api/sns/web/v2/search/notes"


class SearchSortType(str, Enum):
    GENERAL = "general"
    MOST_POPULAR = "popularity_descending"
    LATEST = "time_descending"


class SearchNoteType(int, Enum):
    ALL = 0
    VIDEO = 1
    IMAGE = 2


def get_search_id() -> str:
    """与 MediaCrawler help.get_search_id 一致。"""

    def base36encode(number: int) -> str:
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if number == 0:
            return alphabet[0]
        base36 = ""
        sign = ""
        if number < 0:
            sign = "-"
            number = -number
        while number != 0:
            number, i = divmod(number, 36)
            base36 = alphabet[i] + base36
        return sign + base36

    e = int(time.time() * 1000) << 64
    t = int(random.uniform(0, 2147483646))
    return base36encode(e + t)


def get_session_id() -> str:
    """浏览器搜索 v2 的 session_id（UUID）。"""
    return str(uuid.uuid4())


def _search_filters(sort: str) -> List[Dict[str, Any]]:
    """对齐网页 v2 search body 的 filters（综合搜索以 sort_type 为主）。"""
    return [{"tags": [sort], "type": "sort_type"}]


def parse_creator_url(url: str) -> Dict[str, str]:
    """从博主主页 URL 解析 user_id / xsec_token / xsec_source。"""
    path_match = re.search(r"/user/profile/([^/?]+)", url)
    if not path_match:
        raise ValueError(f"无法从 URL 解析 user_id: {url}")
    params = parse_qs(urlparse(url).query)
    return {
        "user_id": path_match.group(1),
        "xsec_token": (params.get("xsec_token") or [""])[0],
        "xsec_source": (params.get("xsec_source") or ["pc_feed"])[0],
    }


def parse_note_url(url_or_id: str) -> Dict[str, str]:
    """解析笔记 URL / 纯 note_id（对齐 mediaspider parse_note_info_from_note_url）。"""
    text = (url_or_id or "").strip()
    if not text:
        raise ValueError("空的笔记 URL/ID")
    if not text.startswith("http") and "xiaohongshu.com" not in text:
        return {
            "note_id": text.split("?")[0],
            "xsec_token": "",
            "xsec_source": "",
        }
    note_id = text.split("/")[-1].split("?")[0]
    if not note_id:
        raise ValueError(f"无法从 URL 解析 note_id: {url_or_id}")
    params = parse_qs(urlparse(text).query)
    return {
        "note_id": note_id,
        "xsec_token": (params.get("xsec_token") or [""])[0],
        "xsec_source": (params.get("xsec_source") or [""])[0],
    }


def extract_creator_info_from_html(html: str) -> Optional[Dict]:
    match = re.search(
        r"<script>window\.__INITIAL_STATE__=(.+?)</script>", html, re.S
    )
    if not match:
        return None
    info = json.loads(match.group(1).replace(":undefined", ":null"), strict=False)
    if not info:
        return None
    return (info.get("user") or {}).get("userPageData")


class XhsClient:
    def __init__(
        self,
        cookie: Optional[str] = None,
        timeout: int = 20,
        *,
        account_name: str = "",
    ):
        if cookie is None:
            from .credentials import load_xhs_cookie

            cookie = load_xhs_cookie(account_name=account_name).cookie
        self.cookie = cookie
        self.timeout = timeout
        self.session = requests.Session()
        self.account_name = account_name or ""

    def _base_headers(self) -> Dict[str, str]:
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "origin": DOMAIN,
            "referer": f"{DOMAIN}/",
            "user-agent": DEFAULT_UA,
            "cookie": self.cookie,
        }

    def _request(
        self,
        method: str,
        uri: str,
        *,
        params: Optional[Dict] = None,
        payload: Optional[Dict] = None,
        host: str = HOST,
    ) -> Dict[str, Any]:
        method = method.upper()
        if method == "GET":
            signed = sign_headers(uri, self.cookie, data=params or {}, method="GET")
        else:
            signed = sign_headers(uri, self.cookie, data=payload or {}, method="POST")

        headers = self._base_headers()
        headers.update(
            {
                "x-s": signed["x-s"],
                "x-t": signed["x-t"],
                "x-s-common": signed["x-s-common"],
                "x-b3-traceid": signed["x-b3-traceid"],
            }
        )

        url = host + uri
        if method == "GET":
            # 查询串编码必须与签名 content_string 一致（同 MediaCrawler）
            if params:
                signed_path = build_sign_string(uri, params, method="GET")
                url = host + signed_path
            resp = self.session.get(url, headers=headers, timeout=self.timeout)
        else:
            headers["content-type"] = "application/json;charset=UTF-8"
            body = json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=False)
            resp = self.session.post(
                url, data=body.encode("utf-8"), headers=headers, timeout=self.timeout
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"响应非 JSON HTTP {resp.status_code}: {resp.text[:300]}") from exc

        if resp.status_code != 200 or not data.get("success", data.get("code") == 0):
            raise RuntimeError(
                f"接口失败 HTTP {resp.status_code}: {json.dumps(data, ensure_ascii=False)[:500]}"
            )
        return data.get("data", data)

    def user_me(self) -> Dict[str, Any]:
        return self._request("GET", "/api/sns/web/v2/user/me", params={})

    def search_users(
        self,
        keyword: str,
        *,
        page: int = 1,
        page_size: int = 15,
        search_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """用户搜索（含小红书号精确匹配）。

        POST /api/sns/web/v1/search/usersearch
        """
        payload = {
            "search_user_request": {
                "keyword": keyword,
                "search_id": search_id or get_search_id(),
                "page": page,
                "page_size": page_size,
                "biz_type": "web_search_user",
                "request_id": str(uuid.uuid4()),
            }
        }
        return self._request("POST", "/api/sns/web/v1/search/usersearch", payload=payload)

    def get_profile_bundle(self, red_id_or_empty: str = "") -> Dict[str, Any]:
        """根据登录态或小红书号解析主页，并补齐简介/粉丝等资料。

        - 空参数：用 cookie 调 user/me，再拉主页 HTML
        - 有参数：按小红书号/昵称搜索，再拉主页详情
        """
        from .store import crawl_result
        from .normalize import normalize_creator

        handle = (red_id_or_empty or "").strip()
        seeds: List[Dict[str, Any]] = []
        exact = False

        if not handle:
            me = self.user_me()
            user_id = me.get("user_id") or ""
            if not user_id:
                raise RuntimeError("user/me 未返回 user_id，请检查 cookie")
            seeds.append(
                {
                    "user_id": user_id,
                    "red_id": me.get("red_id") or "",
                    "xsec_token": "",
                    "xsec_source": "pc_feed",
                    "is_self": True,
                    "fallback": {
                        "nickname": me.get("nickname") or "",
                        "avatar": me.get("images") or me.get("imageb") or "",
                        "desc": me.get("desc") or "",
                    },
                }
            )
        else:
            raw = self.search_users(handle)
            users = raw.get("users") or []
            matched = [u for u in users if str(u.get("red_id") or "") == handle]
            exact = bool(matched)
            chosen = matched or users
            for u in chosen:
                user_id = u.get("id") or ""
                if not user_id:
                    continue
                seeds.append(
                    {
                        "user_id": user_id,
                        "red_id": u.get("red_id") or "",
                        "xsec_token": u.get("xsec_token") or "",
                        "xsec_source": "pc_search",
                        "is_self": bool(u.get("is_self")),
                        "fallback": {
                            "nickname": u.get("name") or "",
                            "avatar": u.get("image") or "",
                            "sub_title": u.get("sub_title") or "",
                            "note_count": u.get("note_count"),
                        },
                    }
                )

        if not seeds:
            raise RuntimeError(f"未找到小红书号/用户: {handle or '(self)'}")

        creators: List[Dict[str, Any]] = []
        for seed in seeds:
            user_id = seed["user_id"]
            xsec_token = seed.get("xsec_token") or ""
            xsec_source = seed.get("xsec_source") or "pc_search"
            raw_profile = None
            try:
                raw_profile = self.get_creator_info(
                    user_id, xsec_token=xsec_token, xsec_source=xsec_source
                )
            except Exception:
                raw_profile = None

            creator = normalize_creator(user_id, raw_profile) if raw_profile else None
            if not creator:
                fb = seed.get("fallback") or {}
                creator = {
                    "platform": "xhs",
                    "creator_hash": user_id,
                    "nickname": fb.get("nickname") or "",
                    "display_name": (fb.get("nickname") or "")[:100],
                    "profile_url": f"{DOMAIN}/user/profile/{user_id}",
                    "bio": fb.get("desc") or "",
                    "avatar": fb.get("avatar") or "",
                    "gender": "未知",
                    "ip_location": "",
                    "following_count": None,
                    "fans_count": None,
                    "works_count": fb.get("note_count"),
                    "liked_count": None,
                    "interaction_count": None,
                }

            basic = (raw_profile or {}).get("basicInfo") or {}
            red_id = (
                seed.get("red_id")
                or basic.get("redId")
                or basic.get("red_id")
                or ""
            )
            profile_url = f"{DOMAIN}/user/profile/{user_id}"
            if xsec_token:
                profile_url = (
                    f"{profile_url}?xsec_token={quote(xsec_token)}"
                    f"&xsec_source={xsec_source}"
                )
            creator["user_id"] = user_id
            creator["red_id"] = red_id
            creator["xsec_token"] = xsec_token
            creator["xsec_source"] = xsec_source
            creator["profile_url"] = profile_url
            creator["is_self"] = bool(seed.get("is_self"))
            if seed.get("fallback", {}).get("sub_title"):
                creator.setdefault("sub_title", seed["fallback"]["sub_title"])
            creators.append(creator)

        result = crawl_result(
            platform="xhs",
            crawl_type="profile",
            creator_url=creators[0]["profile_url"],
            creators=creators,
        )
        if handle:
            result["keyword"] = handle
            result["exact_match"] = exact
        return result

    def search_notes(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        sort: SearchSortType = SearchSortType.GENERAL,
        note_type: SearchNoteType = SearchNoteType.ALL,
        search_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """关键词搜索笔记（浏览器现行 v2）。

        POST https://so.xiaohongshu.com/api/sns/web/v2/search/notes
        page_size 需为 20，否则常空结果。
        """
        if page_size != 20:
            page_size = 20
        sort_value = sort.value if isinstance(sort, SearchSortType) else str(sort)
        note_type_value = (
            note_type.value if isinstance(note_type, SearchNoteType) else int(note_type)
        )
        # 字段顺序对齐浏览器 JSON.stringify，参与 x-s 签名
        payload = {
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
            "search_id": search_id or get_search_id(),
            "session_id": session_id or get_session_id(),
            "sort": sort_value,
            "note_type": note_type_value,
            "ext_flags": [],
            "filters": _search_filters(sort_value),
            "geo": "",
            "image_formats": ["jpg", "webp", "avif"],
            "message_id": "sending",
        }
        return self._request(
            "POST",
            SEARCH_NOTES_URI,
            payload=payload,
            host=SEARCH_HOST,
        )

    def search_notes_with_detail(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        sort: SearchSortType = SearchSortType.GENERAL,
        note_type: SearchNoteType = SearchNoteType.ALL,
        search_id: Optional[str] = None,
        session_id: Optional[str] = None,
        *,
        interval: float = 0.8,
    ) -> Dict[str, Any]:
        """搜索 + 逐条拉 feed 详情（MediaCrawler.search 同款流程）。"""
        from .store import crawl_result
        from .normalize import normalize_note_item

        raw = self.search_notes(
            keyword=keyword,
            page=page,
            page_size=page_size,
            sort=sort,
            note_type=note_type,
            search_id=search_id,
            session_id=session_id,
        )
        contents = []
        for post_item in raw.get("items") or []:
            if post_item.get("model_type") in ("rec_query", "hot_query"):
                continue
            note_id = post_item.get("id")
            xsec_token = post_item.get("xsec_token") or ""
            xsec_source = post_item.get("xsec_source") or "pc_search"
            if not note_id or not xsec_token:
                continue
            try:
                detail = self.get_note_by_id(note_id, xsec_token, xsec_source)
            except Exception:
                detail = {}
            if not detail:
                # 详情失败时至少保留列表卡片信息
                card = dict(post_item.get("note_card") or {})
                card.setdefault("note_id", note_id)
                card.setdefault("xsec_token", xsec_token)
                card.setdefault("xsec_source", xsec_source)
                detail = card
            normalized = normalize_note_item(
                detail,
                source_keyword=keyword,
                xsec_source=xsec_source,
            )
            if normalized:
                contents.append(normalized)
            if interval > 0:
                time.sleep(interval)
        return crawl_result(
            platform="xhs",
            crawl_type="search",
            keywords=[keyword],
            contents=contents,
            has_more=bool(raw.get("has_more")),
            page=page,
            search_id=search_id or "",
        )

    def search_notes_pages(
        self,
        keyword: str,
        *,
        start_page: int = 1,
        max_pages: int = 3,
        page_size: int = 20,
        sort: SearchSortType = SearchSortType.GENERAL,
        note_type: SearchNoteType = SearchNoteType.ALL,
        interval: float = 0.8,
        page_interval: float = 1.5,
        with_detail: bool = True,
    ) -> Dict[str, Any]:
        """多页搜索翻页（对齐 MediaCrawler）。

        规则：
        1. 同一次关键词搜索共用同一个 search_id
        2. page 从 start_page 递增，page_size 固定 20
        3. has_more=false 或本页无有效笔记时停止
        """
        from .store import crawl_result
        from .normalize import normalize_search_response

        search_id = get_search_id()
        session_id = get_session_id()
        all_contents: List[Dict[str, Any]] = []
        page = start_page
        pages_fetched = 0
        last_has_more = False

        while pages_fetched < max_pages:
            if with_detail:
                page_res = self.search_notes_with_detail(
                    keyword=keyword,
                    page=page,
                    page_size=page_size,
                    sort=sort,
                    note_type=note_type,
                    search_id=search_id,
                    session_id=session_id,
                    interval=interval,
                )
                contents = page_res.get("contents") or []
                last_has_more = bool(page_res.get("has_more"))
            else:
                raw = self.search_notes(
                    keyword=keyword,
                    page=page,
                    page_size=page_size,
                    sort=sort,
                    note_type=note_type,
                    search_id=search_id,
                    session_id=session_id,
                )
                page_res = normalize_search_response(raw, source_keyword=keyword)
                contents = page_res.get("contents") or []
                last_has_more = bool(page_res.get("has_more"))

            if not contents:
                break
            all_contents.extend(contents)
            pages_fetched += 1
            if not last_has_more:
                break
            page += 1
            if page_interval > 0 and pages_fetched < max_pages:
                time.sleep(page_interval)

        return crawl_result(
            platform="xhs",
            crawl_type="search",
            keywords=[keyword],
            contents=all_contents,
            search_id=search_id,
            start_page=start_page,
            pages_fetched=pages_fetched,
            has_more=last_has_more,
        )

    def get_note_by_id(
        self,
        note_id: str,
        xsec_token: str,
        xsec_source: str = "pc_search",
    ) -> Dict[str, Any]:
        """笔记详情（feed），返回 note_card 结构，供 MediaCrawler 同款归一化。"""
        if not xsec_source:
            xsec_source = "pc_search"
        payload = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1},
            "xsec_source": xsec_source,
            "xsec_token": xsec_token,
        }
        res = self._request("POST", "/api/sns/web/v1/feed", payload=payload)
        items = res.get("items") or []
        if not items:
            return {}
        note_card = items[0].get("note_card") or {}
        note_card.setdefault("xsec_token", xsec_token)
        note_card.setdefault("xsec_source", xsec_source)
        return note_card

    def get_notes_by_creator(
        self,
        user_id: str,
        cursor: str = "",
        page_size: int = 10,
        xsec_token: str = "",
        xsec_source: str = "pc_feed",
    ) -> Dict[str, Any]:
        """博主已发布笔记列表（分页）。"""
        params = {
            "num": page_size,
            "cursor": cursor,
            "user_id": user_id,
            "image_formats": "jpg,webp,avif",
            "xsec_token": xsec_token,
            "xsec_source": xsec_source,
        }
        return self._request("GET", "/api/sns/web/v1/user_posted", params=params)

    def get_all_notes_by_creator(
        self,
        user_id: str,
        *,
        max_notes: int = 10,
        crawl_interval: float = 1.0,
        xsec_token: str = "",
        xsec_source: str = "pc_feed",
    ) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        cursor = ""
        has_more = True
        while has_more and len(result) < max_notes:
            page = self.get_notes_by_creator(
                user_id,
                cursor=cursor,
                xsec_token=xsec_token,
                xsec_source=xsec_source,
            )
            notes = page.get("notes") or []
            result.extend(notes)
            has_more = bool(page.get("has_more"))
            cursor = page.get("cursor") or ""
            if not notes:
                break
            if has_more and len(result) < max_notes:
                time.sleep(crawl_interval)
        return result[:max_notes]

    def enrich_notes_with_detail(
        self,
        notes: List[Dict[str, Any]],
        *,
        default_xsec_source: str = "pc_feed",
        interval: float = 0.8,
    ) -> List[Dict[str, Any]]:
        """列表笔记逐条拉 feed 详情并归一化（同搜索逻辑）。"""
        from .normalize import normalize_note_item

        result: List[Dict[str, Any]] = []
        for note in notes or []:
            note_id = note.get("note_id") or note.get("id")
            xsec_token = note.get("xsec_token") or ""
            xsec_source = note.get("xsec_source") or default_xsec_source
            if not note_id or not xsec_token:
                continue
            try:
                detail = self.get_note_by_id(note_id, xsec_token, xsec_source)
            except Exception:
                detail = {}
            if not detail:
                detail = dict(note)
                detail.setdefault("note_id", note_id)
                detail.setdefault("xsec_token", xsec_token)
                detail.setdefault("xsec_source", xsec_source)
            normalized = normalize_note_item(detail, xsec_source=xsec_source)
            if normalized:
                result.append(normalized)
            if interval > 0:
                time.sleep(interval)
        return result

    def get_detail_bundle(
        self,
        url_or_id: str,
        *,
        xsec_token: str = "",
        xsec_source: str = "",
    ) -> Dict[str, Any]:
        """单条笔记详情（对齐 mediaspider crawl_type=detail）。"""
        from .store import crawl_result
        from .normalize import normalize_note_item

        info = parse_note_url(url_or_id)
        note_id = info["note_id"]
        token = xsec_token or info["xsec_token"]
        source = xsec_source or info["xsec_source"] or "pc_search"
        if not token:
            raise ValueError(
                "缺少 xsec_token：请传完整 explore URL，或用 --xsec-token"
            )
        card = self.get_note_by_id(note_id, token, source)
        content = normalize_note_item(card, xsec_source=source) if card else None
        content_url = (
            url_or_id
            if url_or_id.startswith("http")
            else (content or {}).get("note_url")
            or f"https://www.xiaohongshu.com/explore/{note_id}"
        )
        return crawl_result(
            platform="xhs",
            crawl_type="detail",
            content_url=content_url,
            contents=[content] if content else [],
        )

    def get_creator_info(
        self,
        user_id: str,
        xsec_token: str = "",
        xsec_source: str = "",
    ) -> Optional[Dict[str, Any]]:
        """从博主主页 HTML 解析资料（不走 edith 签名接口）。"""
        uri = f"/user/profile/{user_id}"
        if xsec_token and xsec_source:
            uri = f"{uri}?xsec_token={xsec_token}&xsec_source={xsec_source}"
        headers = {
            "user-agent": DEFAULT_UA,
            "cookie": self.cookie,
            "referer": f"{DOMAIN}/",
        }
        resp = self.session.get(DOMAIN + uri, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return extract_creator_info_from_html(resp.text)
