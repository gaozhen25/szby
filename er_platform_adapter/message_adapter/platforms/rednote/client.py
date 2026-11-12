"""Rednote signed HTTP client used by private messages."""

from __future__ import annotations

import json
from typing import Any

import requests

from .signing import build_sign_string, sign_headers

HOST = "https://edith.xiaohongshu.com"
DOMAIN = "https://www.xiaohongshu.com"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)


class RednoteClient:
    def __init__(self, cookie: str, timeout: int = 20):
        self.cookie = cookie
        self.timeout = timeout
        self.session = requests.Session()

    def _base_headers(self) -> dict[str, str]:
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
        params: dict | None = None,
        payload: dict | None = None,
        host: str = HOST,
    ) -> dict[str, Any]:
        method = method.upper()
        signed = sign_headers(
            uri,
            self.cookie,
            data=params if method == "GET" else payload or {},
            method=method,
        )
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
            if params:
                url = host + build_sign_string(uri, params, method="GET")
            response = self.session.get(url, headers=headers, timeout=self.timeout)
        else:
            headers["content-type"] = "application/json;charset=UTF-8"
            body = json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=False)
            response = self.session.post(
                url,
                data=body.encode("utf-8"),
                headers=headers,
                timeout=self.timeout,
            )
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"响应非 JSON HTTP {response.status_code}: {response.text[:300]}") from exc
        if response.status_code != 200 or not data.get("success", data.get("code") == 0):
            raise RuntimeError(
                f"接口失败 HTTP {response.status_code}: {json.dumps(data, ensure_ascii=False)[:500]}"
            )
        result = data.get("data", data)
        return result if isinstance(result, dict) else {"data": result}

    def user_me(self) -> dict[str, Any]:
        return self._request("GET", "/api/sns/web/v2/user/me", params={})
