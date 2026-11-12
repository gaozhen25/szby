"""HTTP and MQTT client used by the BOSS message adapter."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from typing import Any

import httpx

from .constants import (
    BASE_URL,
    BOSS_EXCHANGE_ACCEPT_URL,
    BOSS_EXCHANGE_CONTENT_URL,
    BOSS_EXCHANGE_REQUEST_URL,
    BOSS_FRIEND_DETAIL_URL,
    BOSS_FRIEND_LIST_URL,
    BOSS_HISTORY_MSG_URL,
    BOSS_LAST_MSG_URL,
    GET_WT_URL,
    HEADERS,
    USER_INFO_URL,
    WEB_BOSS_CHAT_URL,
)
from .exceptions import BossApiError, IdentityMismatchError, ParamError, RateLimitError, SessionExpiredError

logger = logging.getLogger(__name__)
_STOKEN_LOCK = threading.Lock()
_STOKEN_RETRY_CODES = {37, 121}


class BossClient:
    """Authenticated BOSS transport limited to private-message operations."""

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

    @property
    def client(self) -> httpx.Client:
        if self._http is None:
            raise RuntimeError("BossClient must be used as a context manager")
        return self._http

    def __enter__(self) -> BossClient:
        cookies = self.credential.cookies if self.credential else {}
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers=dict(HEADERS),
            cookies=cookies,
            follow_redirects=True,
            timeout=httpx.Timeout(self._timeout),
        )
        self._ensure_stoken()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    def _ensure_stoken(self, force: bool = False) -> None:
        """Generate and persist ``__zp_stoken__`` when the saved session does not have one."""
        if self._http is None or self._stoken_is_ready(force):
            return
        with _STOKEN_LOCK:
            if self._stoken_is_ready(force):
                return
            from .stoken import STOKEN_COOKIE, generate_stoken

            session = dict(self.credential.cookies) if self.credential else {}
            stoken = generate_stoken(session)
            if not stoken:
                return
            self._http.cookies.set(STOKEN_COOKIE, stoken)
            if self.credential is None:
                return
            self.credential.cookies[STOKEN_COOKIE] = stoken
            try:
                from .auth import save_credential

                save_credential(self.credential)
            except Exception as exc:
                logger.warning("保存 __zp_stoken__ 失败: %s", exc)
            else:
                logger.info("__zp_stoken__ 已写入登录会话")

    def _stoken_is_ready(self, force: bool) -> bool:
        if force or self._http is None:
            return False
        from .stoken import STOKEN_COOKIE

        current = str(self._http.cookies.get(STOKEN_COOKIE) or "")
        if current:
            return True
        saved = ""
        if self.credential is not None:
            saved = str(self.credential.cookies.get(STOKEN_COOKIE) or "")
        if not saved:
            return False
        self._http.cookies.set(STOKEN_COOKIE, saved)
        return True

    def _rate_limit_delay(self) -> None:
        if self._request_delay <= 0:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self._request_delay:
            time.sleep(self._request_delay - elapsed + max(0.0, random.gauss(0.3, 0.15)))
        now = time.time()
        recent_15s = sum(1 for timestamp in self._recent_request_times if now - timestamp <= 15)
        recent_45s = sum(1 for timestamp in self._recent_request_times if now - timestamp <= 45)
        if recent_45s >= 6:
            time.sleep(random.uniform(4.0, 7.0))
        elif recent_15s >= 3:
            time.sleep(random.uniform(1.2, 2.8))

    def _request_headers(self, url: str) -> dict[str, str]:
        headers = dict(HEADERS)
        headers["X-Requested-With"] = "XMLHttpRequest"
        token = self.client.cookies.get("geek_zp_token", "") or self.client.cookies.get("bst", "") or self.client.cookies.get("zp_at", "")
        if token:
            headers["zp_token"] = token
        if url in {
            BOSS_EXCHANGE_ACCEPT_URL,
            BOSS_EXCHANGE_CONTENT_URL,
            BOSS_EXCHANGE_REQUEST_URL,
            BOSS_FRIEND_LIST_URL,
            BOSS_FRIEND_DETAIL_URL,
            BOSS_LAST_MSG_URL,
            BOSS_HISTORY_MSG_URL,
        }:
            headers["Referer"] = WEB_BOSS_CHAT_URL
        return headers

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        self._rate_limit_delay()
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = self.client.request(method, url, headers=self._request_headers(url), **kwargs)
                self._last_request_time = time.time()
                self._request_count += 1
                self._recent_request_times.append(self._last_request_time)
                for name, value in response.cookies.items():
                    if value:
                        self.client.cookies.set(name, value)
                if response.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2**attempt + random.uniform(0, 1))
                    continue
                if response.status_code == 404:
                    if response.text.strip().startswith("{"):
                        return response.json()
                    raise BossApiError(f"BOSS endpoint not found: {url}", code=404)
                response.raise_for_status()
                if response.text.startswith("<"):
                    raise BossApiError(f"BOSS returned HTML for {url}; the session may have expired")
                payload = response.json()
                if (
                    isinstance(payload, dict)
                    and payload.get("code") in _STOKEN_RETRY_CODES
                    and not self._stoken_refreshed
                ):
                    self._stoken_refreshed = True
                    logger.info("BOSS 风控 code=%s，刷新 __zp_stoken__ 后重试", payload.get("code"))
                    self._ensure_stoken(force=True)
                    continue
                return payload
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                time.sleep(2**attempt + random.uniform(0, 1))
        if last_error:
            raise BossApiError(f"BOSS request failed after retries: {last_error}") from last_error
        raise BossApiError("BOSS request failed after retries")

    def _unwrap(self, payload: dict[str, Any], action: str) -> Any:
        code = payload.get("code", -1)
        if code == 0:
            return payload.get("zpData", {})
        message = str(payload.get("message") or "unknown error")
        if code == 37:
            raise SessionExpiredError()
        if code == 24:
            raise IdentityMismatchError()
        if code in (17, 19):
            raise ParamError(message, code=code)
        if code == 9:
            self._rate_limit_count += 1
            cooldown = min(60, 10 * (2 ** (self._rate_limit_count - 1)))
            self._request_delay = max(self._request_delay, self._base_request_delay * 2)
            time.sleep(cooldown)
            raise RateLimitError()
        raise BossApiError(f"{action}: {message} (code={code})", code=code, response=payload)

    def _get(self, url: str, *, params: dict[str, Any] | None = None, action: str) -> Any:
        try:
            result = self._unwrap(self._request("GET", url, params=params), action)
        except RateLimitError:
            result = self._unwrap(self._request("GET", url, params=params), action)
        self._rate_limit_count = 0
        return result

    def _post(self, url: str, *, data: dict[str, Any], action: str) -> Any:
        try:
            result = self._unwrap(self._request("POST", url, data=data), action)
        except RateLimitError:
            result = self._unwrap(self._request("POST", url, data=data), action)
        self._rate_limit_count = 0
        return result

    def get_user_info(self) -> dict[str, Any]:
        return self._get(USER_INFO_URL, action="用户信息")

    def get_ws_auth(self) -> tuple[str, str, dict[str, Any]]:
        user_info = self.get_user_info()
        page_token = str(user_info.get("token") or user_info.get("pageToken") or "")
        wt_data = self._get(GET_WT_URL, action="WS Token")
        wt2 = str(wt_data.get("wt2") or self.client.cookies.get("wt2") or "")
        if not page_token:
            raise BossApiError("无法获取 MQTT page_token，请重新登录 BOSS")
        if not wt2:
            raise BossApiError("无法获取 MQTT wt2，请重新登录 BOSS")
        return page_token, wt2, user_info

    def session_cookies(self) -> dict[str, str]:
        cookies = dict(self.credential.cookies) if self.credential else {}
        cookies.update({name: value for name, value in self.client.cookies.items() if value})
        return cookies

    def get_boss_friend_list(self, *, page: int = 1) -> dict[str, Any]:
        return self._post(BOSS_FRIEND_LIST_URL, data={"labelId": 0, "page": page}, action="候选人列表")

    def get_boss_friend_details(self, friend_ids: list[int], *, batch_size: int = 50) -> dict[str, Any]:
        friends: list[dict[str, Any]] = []
        for start in range(0, len(friend_ids), max(1, batch_size)):
            ids = ",".join(str(value) for value in friend_ids[start : start + batch_size])
            data = self._post(BOSS_FRIEND_DETAIL_URL, data={"friendIds": ids}, action="候选人详情")
            friends.extend(data.get("friendList") or [])
        return {"friendList": friends}

    def get_boss_last_messages(self, friend_ids: list[int], *, batch_size: int = 50) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for start in range(0, len(friend_ids), max(1, batch_size)):
            ids = ",".join(str(value) for value in friend_ids[start : start + batch_size])
            data = self._post(BOSS_LAST_MSG_URL, data={"friendIds": ids, "src": 0}, action="最近消息")
            if isinstance(data, list):
                messages.extend(data)
            else:
                messages.extend(data.get("result") or data.get("list") or [])
        return messages

    def get_boss_chat_history(self, friend_id: int, *, count: int = 50, max_message_id: int = 0) -> dict[str, Any]:
        params: dict[str, Any] = {"gid": friend_id, "c": count, "src": 0}
        if max_message_id:
            params["maxMsgId"] = max_message_id
        return self._get(BOSS_HISTORY_MSG_URL, params=params, action="聊天记录")

    def request_exchange(
        self,
        *,
        security_id: str,
        unique_id: str,
        exchange_type: int,
        name: str = "",
    ) -> dict[str, Any]:
        """Request a BOSS-native phone, WeChat, or resume exchange."""
        if not security_id.strip():
            raise ParamError("交换请求缺少 securityId")
        if not unique_id.strip():
            raise ParamError("交换请求缺少 uniqueId")
        try:
            exchange_type_value = int(exchange_type)
        except (TypeError, ValueError) as exc:
            raise ParamError(f"无效的交换请求类型: {exchange_type}") from exc
        if exchange_type_value not in {1, 2, 4}:
            raise ParamError(f"不支持的交换请求类型: {exchange_type}")
        data: dict[str, Any] = {
            "type": exchange_type_value,
            "securityId": security_id,
            "uniqueId": unique_id,
        }
        if name.strip():
            data["name"] = name
        return self._post(BOSS_EXCHANGE_REQUEST_URL, data=data, action="发起交换")

    def accept_exchange(
        self,
        *,
        security_id: str,
        platform_message_id: int,
        exchange_type: int,
    ) -> dict[str, Any]:
        """Accept an incoming BOSS-native exchange system message."""
        if not security_id.strip():
            raise ParamError("同意交换缺少 securityId")
        try:
            message_id_value = int(platform_message_id)
            exchange_type_value = int(exchange_type)
        except (TypeError, ValueError) as exc:
            raise ParamError("同意交换包含无效的平台消息 ID 或类型") from exc
        if message_id_value <= 0:
            raise ParamError("同意交换缺少平台消息 ID")
        if exchange_type_value not in {1, 2, 3}:
            raise ParamError(f"不支持的同意交换类型: {exchange_type}")
        return self._post(
            BOSS_EXCHANGE_ACCEPT_URL,
            data={
                "securityId": security_id,
                "mid": message_id_value,
                "type": exchange_type_value,
            },
            action="同意交换",
        )

    def get_exchange_content(self, audience_id: int) -> dict[str, Any]:
        """Read contact information made available after an exchange."""
        try:
            audience_id_value = int(audience_id)
        except (TypeError, ValueError) as exc:
            raise ParamError("查看交换结果包含无效的候选人 uid") from exc
        if audience_id_value <= 0:
            raise ParamError("查看交换结果缺少候选人 uid")
        return self._post(
            BOSS_EXCHANGE_CONTENT_URL,
            data={"uid": audience_id_value},
            action="查看交换结果",
        )

    def send_boss_message(self, to_uid: int, to_encrypt_uid: str, text: str) -> dict[str, Any]:
        if not to_uid:
            raise ParamError("缺少对方 uid")
        if not text.strip():
            raise ParamError("消息内容不能为空")
        from .mqtt import BossMQTTChat, IDENTITY_BOSS

        page_token, wt2, user_info = self.get_ws_auth()
        my_uid = user_info.get("userId")
        if not my_uid:
            raise BossApiError("无法获取当前用户 userId")
        with BossMQTTChat(
            page_token,
            wt2,
            cookies=self.session_cookies(),
            identity=IDENTITY_BOSS,
        ) as chat:
            chat.send(
                from_uid=int(my_uid),
                from_encrypt_uid=str(user_info.get("encryptUserId") or ""),
                to_uid=int(to_uid),
                to_encrypt_uid=to_encrypt_uid,
                text=text,
            )
        return {"ok": True, "toUid": int(to_uid), "identity": IDENTITY_BOSS}
