from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse

from app.auth import COOKIE, MAX_AGE, issue_token
from app.deps import library_of, require_api_key
from app.http import fail
from app.library import Library
from app.paths import WEB
from app.schemas import LoginIn

router = APIRouter()


def _same(got: str, expected: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(got.encode()).digest(),
        hashlib.sha256(expected.encode()).digest(),
    )


@router.post("/api/admin/login", summary="登录后台")
def admin_login(body: LoginIn, request: Request, response: Response, lib: Library = Depends(library_of)) -> dict:
    username = os.environ.get("GALLERY_ADMIN_USER", "admin")
    password = os.environ.get("GALLERY_ADMIN_PASSWORD", "")
    if not password or not _same(body.username.strip(), username) or not _same(body.password, password):
        raise fail(401, "unauthorized", "用户名或密码不正确")
    response.set_cookie(
        COOKIE,
        issue_token(lib.api_key()),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=MAX_AGE,
        path="/",
    )
    return {"ok": True, "oss": lib.store.status()}


@router.post("/api/admin/logout", summary="退出后台")
def admin_logout(response: Response) -> dict:
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/api/admin/me", summary="当前登录与 OSS 状态")
def admin_me(_auth: None = Depends(require_api_key), lib: Library = Depends(library_of)) -> dict:
    return {"ok": True, "oss": lib.store.status(), "stats": lib.summary()}


@router.get("/admin")
def admin_page() -> HTMLResponse:
    return HTMLResponse((WEB / "admin.html").read_text(encoding="utf-8"))
