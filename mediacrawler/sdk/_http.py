# -*- coding: utf-8 -*-
"""HTTP 传输层（远程模式）。"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .exceptions import ApiError, NotFoundError


def request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
) -> Any:
    """发送请求并解析 JSON，统一处理 FastAPI 错误响应。"""
    if params:
        params = {key: value for key, value in params.items() if value is not None}
    response = client.request(method, path, params=params or None, json=json_body)
    if response.status_code == 404:
        detail = _extract_detail(response)
        raise NotFoundError(detail)
    if response.status_code >= 400:
        raise ApiError(response.status_code, _extract_detail(response))
    return response.json()


def _extract_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict) and "detail" in payload:
            detail = payload["detail"]
            return detail if isinstance(detail, str) else str(detail)
    except Exception:
        pass
    return response.text or response.reason_phrase
