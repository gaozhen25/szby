"""Minimal Douyin HTTP client for Web IM (profile lookup + a_bogus)."""

from __future__ import annotations

import copy
import time
import urllib.parse
from typing import Any

import requests

from message_adapter.browser_identity import chrome_major_from_user_agent, current_browser_identity

from .signing import get_a_bogus, get_web_id, parse_cookie_str, parse_sec_user_id

HOST = "https://www.douyin.com"
DEFAULT_UA = current_browser_identity().user_agent


def _webid_from_cookie_dict(cookie_dict: dict[str, str]) -> str:
    """Prefer browser-issued webid cookies over a freshly generated one."""
    for key in ("tt_webid", "tt_webid_v2", "webid", "web_id"):
        val = str(cookie_dict.get(key) or "").strip().strip('"')
        if val and val.isdigit() and len(val) >= 10:
            return val[:19]
    return ""


class DouyinClient:
    def __init__(self, cookie: str = "", *, user_agent: str = DEFAULT_UA, timeout: int = 60):
        self.timeout = timeout
        self.user_agent = user_agent
        self.session = requests.Session()
        self.cookie = (cookie or "").strip()
        self.cookie_dict = parse_cookie_str(self.cookie)
        # 与浏览器同源：有 tt_webid 就用它，避免每次进程启动换新 webid
        self.webid = _webid_from_cookie_dict(self.cookie_dict) or get_web_id()
        # 搜索结果缓存：同一关键词短时间不重复请求，避免触发搜索频控(2484)
        self._search_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._search_cache_ttl = 3600.0
        self.ms_token = ""
        for part in self.cookie.split(";"):
            part = part.strip()
            if part.lower().startswith("mstoken="):
                self.ms_token = part.split("=", 1)[1].strip()
                break
        self.headers: dict[str, str] = {
            "User-Agent": self.user_agent,
            "Cookie": self.cookie,
            "Host": "www.douyin.com",
            "Origin": "https://www.douyin.com/",
            "Referer": "https://www.douyin.com/",
            "Content-Type": "application/json;charset=UTF-8",
        }

    def _common_params(self) -> dict[str, Any]:
        chrome_major = chrome_major_from_user_agent(self.user_agent)
        params: dict[str, Any] = {
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
            "browser_version": f"{chrome_major}.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "os_name": "Mac OS",
            "os_version": "10.15.7",
            "cpu_core_num": "8",
            "device_memory": "8",
            "engine_version": f"{chrome_major}.0",
            "platform": "PC",
            "screen_width": "2560",
            "screen_height": "1440",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "50",
            "webid": self.webid,
        }
        if self.ms_token:
            params["msToken"] = self.ms_token
        return params

    def _process_req_params(self, uri: str, params: dict[str, Any]) -> None:
        params.update(self._common_params())
        # 所有接口（含搜索）都生成 a_bogus：与浏览器一致，避免搜索被识别为异常请求
        query_string = urllib.parse.urlencode(params)
        params["a_bogus"] = get_a_bogus(query_string, self.user_agent, uri=uri)

    def _request(
        self,
        uri: str,
        params: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        merged = dict(params)
        self._process_req_params(uri, merged)
        req_headers = dict(headers or self.headers)
        req_headers["Cookie"] = self.cookie
        resp = self.session.get(f"{HOST}{uri}", params=merged, headers=req_headers, timeout=self.timeout)
        if resp.status_code >= 400:
            raise RuntimeError(f"抖音 HTTP {resp.status_code}: {uri}")
        try:
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"抖音响应非 JSON: {uri}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"抖音响应格式异常: {uri}")
        return data

    def get_user_info(self, sec_user_id: str) -> dict[str, Any]:
        params = {
            "sec_user_id": sec_user_id,
            "publish_video_strategy_type": 2,
            "personal_center_strategy": 1,
        }
        return self._request("/aweme/v1/web/user/profile/other/", params)

    def get_self_profile(self) -> dict[str, Any]:
        headers = copy.copy(self.headers)
        headers.pop("Origin", None)
        res = self._request("/aweme/v1/web/user/profile/self/", {}, headers=headers)
        return res.get("user") or {}

    def search_users(self, keyword: str, *, count: int = 10) -> dict[str, Any]:
        cache_key = f"{keyword}|{count}"
        now = time.time()
        hit = self._search_cache.get(cache_key)
        if hit and now - hit[0] < self._search_cache_ttl:
            return hit[1]
        params: dict[str, Any] = {
            "search_channel": "aweme_user_web",
            "enable_history": "1",
            "keyword": keyword,
            "search_source": "tab_search",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": "7378810571505847586",
            "offset": 0,
            "count": str(count),
            "need_filter_settings": "1",
            "list_type": "single",
            "search_id": "",
        }
        referer_url = f"https://www.douyin.com/search/{keyword}?aid=f594bbd9-a0e2-4651-9319-ebe3cb6298c1&type=user"
        headers = copy.copy(self.headers)
        headers["Referer"] = urllib.parse.quote(referer_url, safe=":/")
        data = self._request("/aweme/v1/web/general/search/single/", params, headers=headers)
        sc = int(data.get("status_code") or 0)
        # 2484 = 搜索频控：明确报错，避免上层误判"未找到用户"
        if sc == 2484 or sc not in (0, 200):
            msg = str(data.get("status_msg") or data.get("message") or f"status_code={sc}")
            raise RuntimeError(
                f"抖音搜索受限(status_code={sc}: {msg})。请稍后再试，或改用 uid / 主页 URL / sec_uid 直接发消息，避免触发搜索。"
            )
        self._search_cache[cache_key] = (time.time(), data)
        return data

    def get_profile_bundle(self, unique_id_or_empty: str = "") -> dict[str, Any]:
        handle = (unique_id_or_empty or "").strip()
        if not handle:
            user = self.get_self_profile()
            if not user:
                raise RuntimeError("profile/self 未返回用户，请检查 cookie")
            return {"creators": [user]}

        raw = self.search_users(handle)
        users: list[dict[str, Any]] = []
        for block in raw.get("data") or []:
            for item in block.get("user_list") or []:
                info = item.get("user_info") or item
                if isinstance(info, dict):
                    users.append(info)
        exact = [u for u in users if str(u.get("unique_id") or "") == handle or str(u.get("short_id") or "") == handle]
        # 统一只按抖音号（unique_id/short_id）精确匹配补头像/昵称，不再 fallback 到昵称搜索结果
        if not exact:
            raise RuntimeError(f"未找到抖音号: {handle}")
        chosen = exact
        user = chosen[0]
        sec = str(user.get("sec_uid") or user.get("sec_user_id") or "")
        if sec:
            try:
                profile_res = self.get_user_info(sec)
                if profile_res:
                    user = profile_res.get("user") or profile_res
            except Exception:
                pass
        return {"creators": [user]}

    def resolve_creator_sec_uid(self, target: str) -> str:
        text = (target or "").strip()
        if not text:
            raise ValueError("空的博主目标")
        if text.startswith("MS4wLjABAAAA"):
            return text.split("?")[0]
        if text.startswith("http") or "douyin.com" in text:
            return parse_sec_user_id(text)
        bundle = self.get_profile_bundle(text)
        creators = bundle.get("creators") or []
        if not creators:
            raise RuntimeError(f"无法解析对方: {text}")
        user = creators[0]
        sec = str(user.get("sec_uid") or user.get("sec_user_id") or "").strip()
        if not sec and user.get("profile_url"):
            sec = parse_sec_user_id(str(user.get("profile_url")))
        if not sec:
            raise RuntimeError(f"无法解析 sec_uid: {text}")
        return sec
