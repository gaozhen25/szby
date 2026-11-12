"""API client for Boss Zhipin with rate limiting, retry, and anti-detection."""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.parse
from collections import deque
from typing import Any

import httpx

from .constants import (
    BASE_URL,
    BOSS_CHAT_GEEK_INFO_URL,
    BOSS_CHATTED_JOB_LIST_URL,
    BOSS_EXCHANGE_ACCEPT_URL,
    BOSS_EXCHANGE_CONTENT_URL,
    BOSS_EXCHANGE_REQUEST_URL,
    BOSS_FRIEND_DETAIL_URL,
    BOSS_FRIEND_LABELS_URL,
    BOSS_FRIEND_LIST_URL,
    BOSS_FRIEND_NOTE_URL,
    BOSS_GREET_REC_SORT_URL,
    BOSS_GREET_SORT_LIST_URL,
    BOSS_HISTORY_MSG_URL,
    BOSS_INTERVIEW_INVITE_URL,
    BOSS_INTERVIEW_LIST_URL,
    BOSS_JOB_OFFLINE_URL,
    BOSS_JOB_ONLINE_URL,
    BOSS_LAST_MSG_URL,
    BOSS_REMOVE_FILTER_URL,
    BOSS_SEARCH_GEEK_URL,
    BOSS_SEND_MSG_URL,
    BOSS_SESSION_ENTER_URL,
    BOSS_VIEW_GEEK_URL,
    CITY_CODES,
    DELIVER_LIST_URL,
    FRIEND_ADD_URL,
    FRIEND_LIST_URL,
    GEEK_GET_JOB_URL,
    GEEK_HISTORY_MSG_URL,
    GET_WT_URL,
    HEADERS,
    INTERVIEW_DATA_URL,
    JOB_CARD_URL,
    JOB_DETAIL_URL,
    JOB_HISTORY_URL,
    JOB_SEARCH_URL,
    RESUME_BASEINFO_URL,
    RESUME_EXPECT_URL,
    RESUME_STATUS_URL,
    USER_INFO_URL,
    WEB_BOSS_CHAT_URL,
    WEB_GEEK_CHAT_URL,
    WEB_GEEK_HISTORY_URL,
    WEB_GEEK_JOB_URL,
    WEB_GEEK_RECOMMEND_URL,
)
from .exceptions import BossApiError, ParamError, RateLimitError, SessionExpiredError, IdentityMismatchError

logger = logging.getLogger(__name__)


def _history_msg_key(msg: dict[str, Any]) -> int | str:
    mid = msg.get("mid") or msg.get("msgId") or msg.get("messageId")
    if mid is not None:
        return int(mid) if str(mid).isdigit() else str(mid)
    return json.dumps(msg, sort_keys=True, default=str, ensure_ascii=False)


def _history_min_mid(messages: list[dict[str, Any]]) -> int | None:
    mids: list[int] = []
    for msg in messages:
        raw = msg.get("mid") or msg.get("msgId") or msg.get("messageId")
        if raw is None:
            continue
        try:
            mids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return min(mids) if mids else None


class BossClient:
    """Boss Zhipin API client with Gaussian jitter, exponential backoff, and session-stable identity.

    Anti-detection strategy:
    - Gaussian jitter delay between requests (~1s mean, σ=0.3)
    - 5% chance of a random long pause (2-5s) to mimic reading behavior
    - Exponential backoff on HTTP 429/5xx (up to 3 retries)
    - Response cookies merged back into session jar
    - Request counter for monitoring
    """

    def __init__(
        self,
        credential: object | None = None,
        timeout: float = 30.0,
        request_delay: float = 1.0,
        max_retries: int = 3,
    ):
        self.credential = credential
        self._timeout = timeout
        self._request_delay = request_delay
        self._base_request_delay = request_delay
        self._max_retries = max_retries
        self._last_request_time = 0.0
        self._request_count = 0
        self._rate_limit_count = 0
        self._stoken_refreshed = False
        self._recent_request_times: deque[float] = deque(maxlen=12)
        self._http: httpx.Client | None = None

    def _build_client(self) -> httpx.Client:
        cookies = {}
        if self.credential:
            cookies = self.credential.cookies
        return httpx.Client(
            base_url=BASE_URL,
            headers=dict(HEADERS),
            cookies=cookies,
            follow_redirects=True,
            timeout=httpx.Timeout(self._timeout),
        )

    @property
    def client(self) -> httpx.Client:
        if not self._http:
            raise RuntimeError("Client not initialized. Use 'with BossClient() as client:'")
        return self._http

    def __enter__(self) -> BossClient:
        self._http = self._build_client()
        self._ensure_stoken()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._http:
            self._http.close()
            self._http = None

    # ── __zp_stoken__ (anti-bot) ────────────────────────────────────

    def _ensure_stoken(self, force: bool = False) -> None:
        """Ensure ``__zp_stoken__`` cookie exists for sensitive endpoints.

        Boss 直聘的风控接口（search / friend / exchange 等）需要浏览器端
        security JS 生成的 ``__zp_stoken__``。本方法在缺失或失效时，通过
        本地无头 Playwright Chromium（反自动化检测）加载页面自动生成并持久化。
        无头模式不弹窗，约 5-15s。
        """
        if not self._http:
            return
        current = self._http.cookies.get("__zp_stoken__")
        if current and not force:
            return
        # 非强制刷新时, 先尝试从已持久化的 credential 同步
        if not force and self.credential and "__zp_stoken__" in (self.credential.cookies or {}):
            self._http.cookies.set("__zp_stoken__", self.credential.cookies["__zp_stoken__"])
            return
        try:
            from ._stoken_gen import gen_stoken
        except Exception as exc:
            logger.warning("__zp_stoken__ 生成模块不可用: %s", exc)
            return
        print("🔧 正在通过无头浏览器生成 __zp_stoken__（约 5-15s，不弹窗）...")
        try:
            cred_cookies = dict(self.credential.cookies) if self.credential else None
            stoken = gen_stoken(cookies=cred_cookies, headless=True)
        except Exception as exc:
            logger.warning("生成 __zp_stoken__ 失败: %s", exc)
            return
        if not stoken:
            logger.warning("未能生成 __zp_stoken__")
            return
        self._http.cookies.set("__zp_stoken__", stoken)
        if self.credential:
            self.credential.cookies["__zp_stoken__"] = stoken
            try:
                from .auth import save_credential
                save_credential(self.credential)
            except Exception:
                pass
        print("✅ __zp_stoken__ 已生成并保存")

    # ── Rate limiting ───────────────────────────────────────────────

    def _rate_limit_delay(self) -> None:
        """Enforce minimum delay with Gaussian jitter to mimic human browsing."""
        if self._request_delay <= 0:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self._request_delay:
            # Gaussian jitter: mean=0.3, σ=0.15, clamped to [0, ∞)
            jitter = max(0, random.gauss(0.3, 0.15))
            # 5% chance of a long pause to mimic reading
            if random.random() < 0.05:
                jitter += random.uniform(2.0, 5.0)
            sleep_time = self._request_delay - elapsed + jitter
            logger.debug("Rate-limit delay: %.2fs", sleep_time)
            time.sleep(sleep_time)

        burst_penalty = self._burst_penalty_delay()
        if burst_penalty > 0:
            logger.debug("Burst penalty delay: %.2fs", burst_penalty)
            time.sleep(burst_penalty)

    def _burst_penalty_delay(self) -> float:
        """Add extra delay when a burst pattern looks less like human browsing."""
        if not self._recent_request_times:
            return 0.0

        now = time.time()
        recent_15s = sum(1 for ts in self._recent_request_times if now - ts <= 15)
        recent_45s = sum(1 for ts in self._recent_request_times if now - ts <= 45)

        if recent_45s >= 6:
            return random.uniform(4.0, 7.0)
        if recent_15s >= 3:
            return random.uniform(1.2, 2.8)
        return 0.0

    def _mark_request(self) -> None:
        now = time.time()
        self._last_request_time = now
        self._request_count += 1
        self._recent_request_times.append(now)

    @property
    def request_stats(self) -> dict[str, int | float]:
        """Return current request statistics."""
        return {
            "request_count": self._request_count,
            "last_request_time": self._last_request_time,
        }

    # ── Response handling ───────────────────────────────────────────

    def _merge_response_cookies(self, resp: httpx.Response) -> None:
        """Persist response Set-Cookie headers back into the session jar."""
        for name, value in resp.cookies.items():
            if value:
                self.client.cookies.set(name, value)

    def _headers_for_request(self, url: str, params: dict[str, Any] | None = None) -> dict[str, str]:
        """Build browser-like headers, including endpoint-specific Referer and zp_token."""
        headers = dict(HEADERS)
        # Add security headers that the boss web app sends with every request
        headers["X-Requested-With"] = "XMLHttpRequest"
        zp_token = (
            self.client.cookies.get("geek_zp_token", "")
            or self.client.cookies.get("bst", "")
            or self.client.cookies.get("zp_at", "")
        )
        if zp_token:
            headers["zp_token"] = zp_token
        if url == JOB_SEARCH_URL:
            query = ""
            if params and params.get("query"):
                query = f"?{urllib.parse.urlencode({'query': params['query']})}"
            headers["Referer"] = f"{WEB_GEEK_JOB_URL}{query}"
        elif url == GEEK_GET_JOB_URL and params and params.get("tag") == 5:
            headers["Referer"] = WEB_GEEK_RECOMMEND_URL
        elif url == GEEK_GET_JOB_URL:
            headers["Referer"] = WEB_GEEK_CHAT_URL
        elif url in (JOB_CARD_URL, JOB_DETAIL_URL):
            headers["Referer"] = WEB_GEEK_JOB_URL
        elif url == JOB_HISTORY_URL:
            headers["Referer"] = WEB_GEEK_HISTORY_URL
        elif url in (FRIEND_LIST_URL, FRIEND_ADD_URL, GEEK_HISTORY_MSG_URL, GET_WT_URL):
            headers["Referer"] = WEB_GEEK_CHAT_URL
        # Recruiter (boss) endpoints
        elif url == BOSS_SEARCH_GEEK_URL:
            headers["Referer"] = f"{BASE_URL}/web/chat/search"
        elif url in (BOSS_VIEW_GEEK_URL, BOSS_SEND_MSG_URL):
            headers["Referer"] = WEB_BOSS_CHAT_URL
        elif url in (BOSS_FRIEND_LIST_URL, BOSS_FRIEND_DETAIL_URL, BOSS_LAST_MSG_URL,
                      BOSS_HISTORY_MSG_URL, BOSS_CHAT_GEEK_INFO_URL, BOSS_FRIEND_LABELS_URL,
                      BOSS_FRIEND_NOTE_URL, BOSS_GREET_SORT_LIST_URL, BOSS_GREET_REC_SORT_URL,
                      BOSS_CHATTED_JOB_LIST_URL, BOSS_INTERVIEW_LIST_URL,
                      BOSS_EXCHANGE_REQUEST_URL, BOSS_EXCHANGE_CONTENT_URL,
                      BOSS_INTERVIEW_INVITE_URL, BOSS_REMOVE_FILTER_URL,
                      BOSS_SESSION_ENTER_URL):
            headers["Referer"] = WEB_BOSS_CHAT_URL
        return headers

    def _handle_response(self, data: dict[str, Any], action: str) -> dict[str, Any]:
        """Validate API response and return zpData, raise typed exceptions."""
        code = data.get("code", -1)

        if code == 0:
            return data.get("zpData", {})

        message = data.get("message", "Unknown error")

        if code == 37:
            raise SessionExpiredError()
        if code == 24:
            raise IdentityMismatchError()
        if code in (17, 19):
            raise ParamError(message, code=code)
        if code in (121, 122):
            raise BossApiError(
                f"{action}: 请求被安全系统拦截 (code={code})。"
                "此操作需要浏览器环境的安全验证，CLI 暂不支持。"
                "请在 BOSS直聘 网页端完成此操作。",
                code=code, response=data,
            )
        if code == 9:
            # Rate limited — auto-cooldown with exponential backoff
            self._rate_limit_count += 1
            cooldown = min(60, 10 * (2 ** (self._rate_limit_count - 1)))
            self._request_delay = max(self._request_delay, self._base_request_delay * 2)
            logger.warning(
                "Rate limited (count=%d), cooling down %.0fs, delay raised to %.1fs",
                self._rate_limit_count, cooldown, self._request_delay,
            )
            time.sleep(cooldown)
            raise RateLimitError()

        raise BossApiError(f"{action}: {message} (code={code})", code=code, response=data)

    # ── Request with retry ──────────────────────────────────────────

    def _request(self, method: str, url: str, **kwargs) -> dict[str, Any]:
        """Execute HTTP request with rate-limit delay, retry, and cookie merge."""
        self._rate_limit_delay()
        last_exc: Exception | None = None
        params = kwargs.get("params")
        merged_headers = self._headers_for_request(url, params=params)
        request_headers = kwargs.pop("headers", None)
        if request_headers:
            merged_headers.update(request_headers)

        for attempt in range(self._max_retries):
            t0 = time.time()
            try:
                resp = self.client.request(method, url, headers=merged_headers, **kwargs)
                elapsed = time.time() - t0
                self._merge_response_cookies(resp)
                self._mark_request()

                logger.info(
                    "[#%d] %s %s → %d (%.2fs)",
                    self._request_count, method, url[:60], resp.status_code, elapsed,
                )

                # Retry on server errors
                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "HTTP %d from %s, retrying in %.1fs (attempt %d/%d)",
                        resp.status_code, url[:80], wait, attempt + 1, self._max_retries,
                    )
                    time.sleep(wait)
                    continue

                # For non-server errors (4xx except 404), raise immediately
                if resp.status_code == 404:
                    # Some endpoints return 404 when anti-bot blocks the request
                    text = resp.text
                    if text.strip().startswith("{"):
                        return resp.json()
                    raise BossApiError(f"接口不存在: {url} (HTTP 404)", code=404)

                resp.raise_for_status()

                # Check for HTML responses (redirect to login page)
                text = resp.text
                if text.startswith("<"):
                    raise BossApiError(f"Received HTML instead of JSON from {url} (possible auth redirect)")

                data = resp.json()

                # 风控拦截(37=环境异常/需 stoken, 121=请求不合法): 刷新 stoken 后重试一次
                if (
                    isinstance(data, dict)
                    and data.get("code") in (37, 121)
                    and not self._stoken_refreshed
                ):
                    self._stoken_refreshed = True
                    logger.info(
                        "[#%d] %s %s → 风控 code=%s, 刷新 __zp_stoken__ 后重试",
                        self._request_count, method, url[:60], data.get("code"),
                    )
                    self._ensure_stoken(force=True)
                    continue

                return data

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                elapsed = time.time() - t0
                last_exc = exc
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "[#%d] %s %s → Network error: %s (%.2fs), retrying in %.1fs (attempt %d/%d)",
                    self._request_count + 1, method, url[:60], exc, elapsed, wait,
                    attempt + 1, self._max_retries,
                )
                time.sleep(wait)

        if last_exc:
            raise BossApiError(f"Request failed after {self._max_retries} retries: {last_exc}") from last_exc
        raise BossApiError(f"Request failed after {self._max_retries} retries")

    def _get(self, url: str, params: dict[str, Any] | None = None, action: str = "") -> dict[str, Any]:
        """GET request with response validation and rate-limit retry."""
        data = self._request("GET", url, params=params)
        try:
            result = self._handle_response(data, action)
            # Reset rate-limit counter on success
            self._rate_limit_count = 0
            return result
        except RateLimitError:
            # Auto-retry once after cooldown (cooldown already happened in _handle_response)
            logger.info("Retrying after rate-limit cooldown...")
            data = self._request("GET", url, params=params)
            result = self._handle_response(data, action)
            self._rate_limit_count = 0
            return result

    # ── Job Search & Browse ─────────────────────────────────────────

    def search_jobs(
        self,
        query: str,
        city: str = "101010100",
        page: int = 1,
        page_size: int = 15,
        experience: str | None = None,
        degree: str | None = None,
        salary: str | None = None,
        industry: str | None = None,
        scale: str | None = None,
        stage: str | None = None,
        job_type: str | None = None,
    ) -> dict[str, Any]:
        """Search jobs."""
        params: dict[str, Any] = {
            "query": query,
            "city": city,
            "page": page,
            "pageSize": page_size,
        }
        if experience:
            params["experience"] = experience
        if degree:
            params["degree"] = degree
        if salary:
            params["salary"] = salary
        if industry:
            params["industry"] = industry
        if scale:
            params["scale"] = scale
        if stage:
            params["stage"] = stage
        if job_type:
            params["jobType"] = job_type
        return self._get(JOB_SEARCH_URL, params=params, action="搜索职位")

    def get_recommend_jobs(self, page: int = 1) -> dict[str, Any]:
        """Get personalized job recommendations.

        The live web page currently loads recommendation cards from
        ``/wapi/zprelation/interaction/geekGetJob`` with tag=5 rather
        than the older ``/wapi/zpgeek/pc/recommend/job/list.json`` path.
        Normalize that payload back into the CLI's historical shape.
        """
        data = self._get(
            GEEK_GET_JOB_URL,
            params={"page": page, "tag": 5, "isActive": "true"},
            action="推荐职位",
        )
        if "jobList" in data:
            return data

        card_list = data.get("cardList", [])
        return {
            "jobList": card_list,
            "hasMore": data.get("hasMore", False),
            "totalCount": data.get("totalCount", len(card_list)),
            "page": data.get("page", page),
            "startIndex": data.get("startIndex", 0),
            "type": data.get("type", 2),
            "lid": data.get("lid", ""),
        }

    def get_job_card(self, security_id: str, lid: str) -> dict[str, Any]:
        """Get job card info (hover preview)."""
        return self._get(JOB_CARD_URL, params={"securityId": security_id, "lid": lid}, action="职位卡片")

    def get_job_detail(self, security_id: str, lid: str = "") -> dict[str, Any]:
        """Get detailed information for a specific job."""
        params: dict[str, str] = {"securityId": security_id}
        if lid:
            params["lid"] = lid
        return self._get(JOB_DETAIL_URL, params=params, action="职位详情")

    # ── Personal Center ─────────────────────────────────────────────

    def get_user_info(self) -> dict[str, Any]:
        """Get current user info (userId, name, avatar, etc.)."""
        return self._get(USER_INFO_URL, action="用户信息")

    def get_resume_baseinfo(self) -> dict[str, Any]:
        """Get resume basic info (full profile: name, age, degree, etc.)."""
        return self._get(RESUME_BASEINFO_URL, action="简历基本信息")

    def get_resume_expect(self) -> dict[str, Any]:
        """Get job expectations (desired position, salary, city)."""
        return self._get(RESUME_EXPECT_URL, action="求职期望")

    def get_resume_status(self) -> dict[str, Any]:
        """Get resume status."""
        return self._get(RESUME_STATUS_URL, action="简历状态")

    def get_deliver_list(self, page: int = 1) -> dict[str, Any]:
        """Get list of jobs applied to (已投递)."""
        return self._get(DELIVER_LIST_URL, params={"page": page}, action="已投递列表")

    def get_interview_data(self) -> dict[str, Any]:
        """Get interview data (面试)."""
        return self._get(INTERVIEW_DATA_URL, action="面试数据")

    def get_job_history(self, page: int = 1) -> dict[str, Any]:
        """Get job browsing history."""
        return self._get(JOB_HISTORY_URL, params={"page": page}, action="浏览历史")

    # ── Social / Chat ───────────────────────────────────────────────

    @staticmethod
    def _job_name_from_payload(payload: dict[str, Any]) -> str:
        if payload.get("jobName"):
            return str(payload["jobName"])
        for key in ("jobCard", "jobInfo", "job"):
            inner = payload.get(key)
            if isinstance(inner, dict) and inner.get("jobName"):
                return str(inner["jobName"])
        return ""

    @staticmethod
    def _company_from_payload(payload: dict[str, Any]) -> str:
        for key in ("brandName", "brandComName", "companyName"):
            if payload.get(key):
                return str(payload[key])
        for wrap in ("jobCard", "jobInfo", "job", "brandComInfo"):
            inner = payload.get(wrap)
            if isinstance(inner, dict):
                for key in ("brandName", "brandComName", "companyName", "name"):
                    if inner.get(key):
                        return str(inner[key])
        return ""

    def get_friend_list(self, page: int = 1) -> dict[str, Any]:
        """Get geek friend list (沟通过的 Boss)."""
        data = self._get(FRIEND_LIST_URL, params={"page": page}, action="好友列表")
        friends = data.get("result") or data.get("friendList") or data.get("list") or []
        for friend in friends:
            security_id = friend.get("securityId")
            if not security_id:
                continue
            brand = str(friend.get("brandName") or "")
            need_job = not friend.get("jobName")
            need_company = (not brand) or brand.endswith("...") or brand.endswith("…")
            if not need_job and not need_company:
                continue
            try:
                card = self.get_job_card(security_id, "")
            except BossApiError:
                logger.debug("Failed to enrich chat friend from job card")
                continue
            if need_job:
                job_name = self._job_name_from_payload(card)
                if job_name:
                    friend["jobName"] = job_name
            if need_company:
                company = self._company_from_payload(card)
                if company:
                    friend["brandName"] = company
        return data

    def add_friend(self, security_id: str, lid: str = "") -> dict[str, Any]:
        """Send greeting to a Boss (打招呼 / 投递简历)."""
        params: dict[str, str] = {"securityId": security_id}
        if lid:
            params["lid"] = lid
        return self._get(FRIEND_ADD_URL, params=params, action="打招呼")

    def get_geek_job(self, security_id: str) -> dict[str, Any]:
        """Get interacted job info."""
        return self._get(GEEK_GET_JOB_URL, params={"securityId": security_id}, action="互动职位")

    def get_geek_chat_history(
        self,
        boss_id: str,
        max_msg_id: int | str = 0,
        count: int = 20,
        page: int = 1,
    ) -> dict[str, Any]:
        """Get geek-side chat history with a recruiter.

        bossId is encryptBossId / encryptUid from the friend list.
        Paginate with maxMsgId = smallest mid from the previous page.
        """
        if not boss_id:
            raise ParamError("bossId 不能为空")
        data = self._get(
            GEEK_HISTORY_MSG_URL,
            params={
                "bossId": boss_id,
                "maxMsgId": max_msg_id,
                "c": count,
                "page": page,
                "src": 0,
            },
            action="聊天记录",
        )
        raw = data.get("messages") or data.get("historyMsgList") or data.get("message") or []
        messages = []
        for item in raw:
            body = item.get("body") or {}
            job = body.get("jobDesc") if isinstance(body, dict) else None
            text = ""
            if isinstance(body, dict):
                text = body.get("text") or body.get("headTitle") or ""
            elif isinstance(body, str):
                text = body
            messages.append({
                "mid": item.get("mid"),
                "type": item.get("type"),
                "received": item.get("received"),
                "fromName": (item.get("from") or {}).get("name") or "",
                "fromUid": (item.get("from") or {}).get("uid"),
                "text": text,
                "job": {
                    "title": job.get("title"),
                    "salary": job.get("salary"),
                    "company": job.get("company"),
                } if isinstance(job, dict) else None,
            })
        return {
            "hasMore": data.get("hasMore", False),
            "count": len(messages),
            "messages": messages,
        }

    def get_geek_chat_history_all(
        self,
        boss_id: str,
        page_size: int = 50,
        max_pages: int = 80,
        start_msg_id: int | str = 0,
    ) -> dict[str, Any]:
        """Paginate geek chat history until the server reports no more messages."""
        return self._paginate_chat_history(
            lambda cursor: self.get_geek_chat_history(
                boss_id=boss_id, max_msg_id=cursor, count=page_size,
            ),
            start_msg_id=start_msg_id,
            page_size=page_size,
            max_pages=max_pages,
        )

    def get_ws_auth(self) -> tuple[str, str, dict[str, Any]]:
        """Return (page_token, wt2, user_info) for geek MQTT authentication."""
        user_info = self.get_user_info()
        page_token = str(user_info.get("token") or user_info.get("pageToken") or "")
        wt_data = self._get(GET_WT_URL, action="WS Token")
        wt2 = str(wt_data.get("wt2") or self.client.cookies.get("wt2") or "")
        if not page_token:
            raise BossApiError(
                "无法获取 MQTT page_token。请用已登录的 Chrome 重新提取 Cookie："
                "uv run boss logout && uv run boss login --cookie-source chrome"
            )
        if not wt2:
            raise BossApiError("无法获取 MQTT wt2，请重新登录")
        return page_token, wt2, user_info

    def send_geek_message(self, to_uid: int, to_encrypt_uid: str, text: str) -> dict[str, Any]:
        """Send a geek-side text DM over MQTT."""
        return self.send_chat_message(to_uid, to_encrypt_uid, text, identity=0)

    def send_boss_message(self, to_uid: int, to_encrypt_uid: str, text: str) -> dict[str, Any]:
        """Send a recruiter-side text DM over MQTT."""
        return self.send_chat_message(to_uid, to_encrypt_uid, text, identity=1)

    def send_chat_message(
        self,
        to_uid: int,
        to_encrypt_uid: str,
        text: str,
        *,
        identity: int = 0,
    ) -> dict[str, Any]:
        """Send a text DM over MQTT as geek (0) or recruiter (1)."""
        if not to_uid:
            raise ParamError("缺少对方 uid")
        if not text.strip():
            raise ParamError("消息内容不能为空")
        from .mqtt_chat import BossMQTTChat

        page_token, wt2, user_info = self.get_ws_auth()
        my_uid = user_info.get("userId")
        my_enc = str(user_info.get("encryptUserId") or "")
        if not my_uid:
            raise BossApiError("无法获取当前用户 userId")

        cookies = self.session_cookies()

        with BossMQTTChat(page_token, wt2, cookies=cookies, identity=identity) as chat:
            chat.send(
                from_uid=int(my_uid),
                from_encrypt_uid=my_enc,
                to_uid=int(to_uid),
                to_encrypt_uid=to_encrypt_uid,
                text=text,
            )
        return {"ok": True, "toUid": int(to_uid), "identity": int(identity)}

    def session_cookies(self) -> dict[str, str]:
        cookies: dict[str, str] = {}
        if self.credential:
            cookies.update({k: v for k, v in self.credential.cookies.items() if v})
        for name, value in self.client.cookies.items():
            if value:
                cookies[name] = value
        return cookies

    # ── Recruiter (Boss) Mode ────────────────────────────────────────

    def _post(self, url: str, data: dict[str, Any] | None = None, action: str = "", json_body: bool = False) -> dict[str, Any]:
        """POST request with form-encoded or JSON body, response validation, and rate-limit retry."""
        kwargs = {"json": data} if json_body else {"data": data}
        resp = self._request("POST", url, **kwargs)
        try:
            result = self._handle_response(resp, action)
            self._rate_limit_count = 0
            return result
        except RateLimitError:
            logger.info("Retrying after rate-limit cooldown...")
            resp = self._request("POST", url, **kwargs)
            result = self._handle_response(resp, action)
            self._rate_limit_count = 0
            return result

    def get_boss_chatted_jobs(self) -> list[dict[str, Any]]:
        """Get list of jobs the boss has posted (chatted job list)."""
        return self._get(BOSS_CHATTED_JOB_LIST_URL, action="招聘职位列表")

    def get_boss_friend_list(self, label_id: int = 0, enc_job_id: str = "", sort: str = "", page: int = 1) -> dict[str, Any]:
        """Get boss friend list (candidates who have chatted)."""
        data: dict[str, Any] = {"labelId": label_id, "page": page}
        if enc_job_id:
            data["encJobId"] = enc_job_id
        if sort:
            data["sort"] = sort
        return self._post(BOSS_FRIEND_LIST_URL, data=data, action="候选人列表")

    def get_boss_friend_details(self, friend_ids: list[int], batch_size: int = 50) -> dict[str, Any]:
        """Get detailed info for boss friends (candidates).

        The upstream API rejects very large friendId batches (code=1092),
        so IDs are requested in chunks.
        """
        if not friend_ids:
            return {"friendList": []}
        merged: list[dict[str, Any]] = []
        size = max(1, int(batch_size))
        for i in range(0, len(friend_ids), size):
            chunk = friend_ids[i:i + size]
            ids_str = ",".join(str(fid) for fid in chunk)
            data = self._post(BOSS_FRIEND_DETAIL_URL, data={"friendIds": ids_str}, action="候选人详情")
            merged.extend(data.get("friendList") or [])
        return {"friendList": merged}

    def get_boss_last_messages(self, friend_ids: list[int], src: int = 0, batch_size: int = 50) -> list[dict[str, Any]]:
        """Get last message for each friend."""
        if not friend_ids:
            return []
        merged: list[dict[str, Any]] = []
        size = max(1, int(batch_size))
        for i in range(0, len(friend_ids), size):
            chunk = friend_ids[i:i + size]
            ids_str = ",".join(str(fid) for fid in chunk)
            data = self._post(BOSS_LAST_MSG_URL, data={"friendIds": ids_str, "src": src}, action="最近消息")
            if isinstance(data, list):
                merged.extend(data)
            elif isinstance(data, dict):
                merged.extend(data.get("result") or data.get("list") or [])
        return merged

    def get_boss_chat_history(self, gid: int, count: int = 20, max_msg_id: int = 0) -> dict[str, Any]:
        """Get chat history with a specific candidate."""
        params: dict[str, Any] = {"gid": gid, "c": count, "src": 0}
        if max_msg_id:
            params["maxMsgId"] = max_msg_id
        return self._get(BOSS_HISTORY_MSG_URL, params=params, action="聊天记录")

    def get_boss_chat_history_all(
        self,
        gid: int,
        page_size: int = 50,
        max_pages: int = 80,
        start_msg_id: int = 0,
    ) -> dict[str, Any]:
        """Paginate recruiter chat history until no more messages are returned."""
        return self._paginate_chat_history(
            lambda cursor: self.get_boss_chat_history(
                gid=gid, count=page_size, max_msg_id=int(cursor or 0),
            ),
            start_msg_id=start_msg_id,
            page_size=page_size,
            max_pages=max_pages,
        )

    def _paginate_chat_history(
        self,
        fetch_page,
        *,
        start_msg_id: int | str = 0,
        page_size: int = 50,
        max_pages: int = 80,
    ) -> dict[str, Any]:
        """Walk maxMsgId cursors until empty, hasMore=false, or max_pages."""
        messages: list[dict[str, Any]] = []
        seen: set[int | str] = set()
        cursor: int | str = start_msg_id or 0
        pages = 0
        truncated = False
        for _ in range(max(1, int(max_pages))):
            pages += 1
            data = fetch_page(cursor)
            batch = data.get("messages") or []
            if not batch:
                break
            added = 0
            for msg in batch:
                key = _history_msg_key(msg)
                if key in seen:
                    continue
                seen.add(key)
                messages.append(msg)
                added += 1
            if added == 0:
                break
            if data.get("hasMore") is False:
                break
            nxt = _history_min_mid(batch)
            if nxt is None:
                break
            if cursor not in (0, "0", None, "") and int(nxt) >= int(cursor):
                break
            if data.get("hasMore") is True:
                cursor = nxt
                continue
            if len(batch) < page_size:
                break
            cursor = nxt
        else:
            truncated = True
        return {
            "messages": messages,
            "count": len(messages),
            "hasMore": truncated,
            "pages": pages,
        }

    def get_boss_chat_geek_info(
        self, encrypt_geek_id: str, security_id: str, job_id: int,
    ) -> dict[str, Any]:
        """Get detailed info for a candidate in chat context."""
        return self._get(
            BOSS_CHAT_GEEK_INFO_URL,
            params={"encryptGeekId": encrypt_geek_id, "securityId": security_id, "jobId": job_id},
            action="候选人信息",
        )

    def get_boss_friend_labels(self) -> dict[str, Any]:
        """Get recruiter's friend labels/tags."""
        return self._get(BOSS_FRIEND_LABELS_URL, action="标签列表")

    def get_boss_greet_list(self, enc_job_id: str = "", page: int = 1) -> dict[str, Any]:
        """Get list of new greetings (candidates who greeted the boss)."""
        params: dict[str, Any] = {"page": page}
        if enc_job_id:
            params["encJobId"] = enc_job_id
        return self._get(BOSS_GREET_SORT_LIST_URL, params=params, action="新招呼列表")

    def get_boss_greet_rec_list(self, enc_job_id: str = "", page: int = 1) -> dict[str, Any]:
        """Get recommended greeting sort list."""
        params: dict[str, Any] = {"page": page}
        if enc_job_id:
            params["encJobId"] = enc_job_id
        return self._get(BOSS_GREET_REC_SORT_URL, params=params, action="推荐招呼排序")

    def get_boss_interview_list(self) -> dict[str, Any]:
        """Get boss interview list."""
        return self._get(BOSS_INTERVIEW_LIST_URL, action="面试列表")

    def search_geeks(
        self, query: str, city: str = "101020100", page: int = 1,
        experience: str | None = None, degree: str | None = None,
        salary: str | None = None, encrypt_job_id: str = "",
    ) -> dict[str, Any]:
        """Search candidates (geeks) as a recruiter."""
        params: dict[str, Any] = {
            "query": query, "city": city, "page": page,
        }
        if encrypt_job_id:
            params["encryptJobId"] = encrypt_job_id
        if experience:
            params["experience"] = experience
        if degree:
            params["degree"] = degree
        if salary:
            params["salary"] = salary
        return self._get(BOSS_SEARCH_GEEK_URL, params=params, action="搜索候选人")

    def get_boss_recommend_geeks(self, page: int = 1, enc_job_id: str = "") -> dict[str, Any]:
        """Get recommended candidates (new greetings sorted by recommendation)."""
        params: dict[str, Any] = {"page": page}
        if enc_job_id:
            params["encJobId"] = enc_job_id
        return self._get(BOSS_GREET_REC_SORT_URL, params=params, action="推荐候选人")

    def get_boss_view_geek(
        self, encrypt_geek_id: str, encrypt_job_id: str, security_id: str = "",
    ) -> dict[str, Any]:
        """Get full candidate resume/profile view."""
        params: dict[str, Any] = {
            "encryptGeekId": encrypt_geek_id,
            "encryptJobId": encrypt_job_id,
        }
        if security_id:
            params["securityId"] = security_id
        return self._get(BOSS_VIEW_GEEK_URL, params=params, action="候选人简历")

    def boss_send_message(self, gid: int, content: str) -> dict[str, Any]:
        """Send a text message to a candidate as a recruiter."""
        return self._post(
            BOSS_SEND_MSG_URL,
            data={"gid": gid, "content": content},
            action="发送消息",
        )

    def boss_job_offline(self, encrypt_job_id: str) -> dict[str, Any]:
        """Take a job posting offline (close)."""
        return self._post(BOSS_JOB_OFFLINE_URL, data={"encryptJobId": encrypt_job_id}, action="关闭职位")

    def boss_job_online(self, encrypt_job_id: str) -> dict[str, Any]:
        """Bring a job posting online (reopen)."""
        return self._post(BOSS_JOB_ONLINE_URL, data={"encryptJobId": encrypt_job_id}, action="开启职位")

    # ── Recruiter Chat Actions ────────────────────────────────────────

    def boss_exchange_request(
        self,
        security_id: str,
        unique_id: str,
        exchange_type: int,
        name: str = "",
    ) -> dict[str, Any]:
        """Request exchange with candidate.

        exchange_type: 1=phone, 2=wechat, 4=resume (前端 exchangeObj 定义)

        BOSS 前端真实参数为 ``{type, securityId, uniqueId, name}``
        (uniqueId = ``{friendId}-{friendSource}``, securityId 需实时拉取;
        resume 场景不传 name)。
        旧参数 ``{type, uid, jobId, gid}`` 已被服务端拒绝（缺少必要参数）。
        """
        data: dict[str, Any] = {
            "type": exchange_type,
            "securityId": security_id,
            "uniqueId": unique_id,
        }
        if name:
            data["name"] = name
        return self._post(
            BOSS_EXCHANGE_REQUEST_URL,
            data=data,
            action="交换请求",
        )

    def boss_exchange_accept(
        self,
        security_id: str,
        mid: int,
        exchange_type: int,
    ) -> dict[str, Any]:
        """Agree to a candidate's exchange request (accept).

        BOSS 前端真实参数为 ``{securityId, mid, type}``（逆向自 typeMap：
        收到手机号请求→type=1、微信请求→type=2、简历请求→type=3）。
        ``mid`` 是对应「请求与您交换」系统消息的消息 id。
        """
        return self._post(
            BOSS_EXCHANGE_ACCEPT_URL,
            data={"securityId": security_id, "mid": mid, "type": exchange_type},
            action="同意交换",
        )

    def boss_get_exchange_content(self, uid: int) -> dict[str, Any]:
        """Get exchanged contact info (phone/wechat) for a candidate."""
        return self._post(
            BOSS_EXCHANGE_CONTENT_URL,
            data={"uid": uid},
            action="查看交换内容",
        )

    def boss_interview_invite(
        self, encrypt_geek_id: str, encrypt_job_id: str, security_id: str,
        address: str = "", start_time: str = "", description: str = "",
    ) -> dict[str, Any]:
        """Invite candidate for an interview."""
        data: dict[str, Any] = {
            "encryptGeekId": encrypt_geek_id,
            "encryptJobId": encrypt_job_id,
            "securityId": security_id,
        }
        if address:
            data["address"] = address
        if start_time:
            data["startTime"] = start_time
        if description:
            data["description"] = description
        return self._post(BOSS_INTERVIEW_INVITE_URL, data=data, action="约面试", json_body=True)

    def boss_mark_unsuitable(self, encrypt_geek_id: str, encrypt_job_id: str) -> dict[str, Any]:
        """Mark candidate as unsuitable."""
        return self._post(
            BOSS_REMOVE_FILTER_URL,
            data={"encryptGeekId": encrypt_geek_id, "encryptJobId": encrypt_job_id},
            action="标记不合适",
        )

    def boss_session_enter(self, geek_id: str, expect_id: str, job_id: str, security_id: str) -> dict[str, Any]:
        """Enter a chat session with a candidate (required before sending messages)."""
        return self._post(
            BOSS_SESSION_ENTER_URL,
            data={"geekId": geek_id, "expectId": expect_id, "jobId": job_id, "securityId": security_id},
            action="进入会话",
        )


# ── City resolution ─────────────────────────────────────────────────

def resolve_city(name: str) -> str:
    """Resolve city name to code, passthrough if already a code."""
    if name.isdigit() and len(name) >= 6:
        return name
    return CITY_CODES.get(name, CITY_CODES["全国"])


def list_cities() -> dict[str, str]:
    """Return all supported city name -> code mappings."""
    return dict(CITY_CODES)
