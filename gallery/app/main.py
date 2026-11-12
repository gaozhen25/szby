from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.library import Library
from app.paths import ROOT, WEB
from app.routers import admin, public, v1


def create_app(data_dir: Path | None = None, api_key: str | None = None, store: object | None = None) -> FastAPI:
    root = data_dir or Path(os.environ.get("GALLERY_DATA", str(ROOT / "data")))
    lib = Library(root, api_key=api_key, store=store)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if lib.key_source == "env":
            print("素材库 API 使用环境变量 GALLERY_API_KEY", file=sys.stderr)
        elif lib.key_source == "file":
            lib.api_key()
            print(f"素材库 API Key 文件：{lib.key_path}", file=sys.stderr)
        yield

    app = FastAPI(
        title="Gallery",
        version="1.2.0",
        description="抖音 / 小红书分享链接解析，以及给其他服务调用的素材库。",
        lifespan=lifespan,
    )
    app.state.library = lib
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["127.0.0.1", "::1"])
    app.include_router(public.router)
    app.include_router(v1.router)
    app.include_router(admin.router)
    if WEB.is_dir():
        app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


app = create_app()
