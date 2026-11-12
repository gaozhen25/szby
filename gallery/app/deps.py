from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.auth import COOKIE, token_ok
from app.http import fail
from app.library import Library

_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)


def library_of(request: Request) -> Library:
    return request.app.state.library


def require_api_key(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_api_key: str | None = Depends(_api_key_header),
) -> None:
    lib = library_of(request)
    if creds and creds.scheme.lower() == "bearer":
        got = creds.credentials
    else:
        got = x_api_key or ""
    if got:
        if not lib.check_key(got):
            raise fail(401, "unauthorized", "需要 API Key。请求头用 Authorization: Bearer <key> 或 X-Api-Key。")
        return
    if token_ok(request.cookies.get(COOKIE, ""), lib.api_key()):
        return
    raise fail(401, "unauthorized", "需要登录后台，或在请求头带 API Key。")
