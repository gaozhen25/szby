from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from app.core.concurrency import run_parse
from app.http import fail
from app.intake import IntakeError, watch_one
from app.media_proxy import stream_media
from app.paths import WEB
from app.schemas import ParseIn

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "host": "gallery.bytech.tech"}


@router.post("/api/parse")
async def parse(body: ParseIn) -> dict:
    try:
        got = await run_parse(watch_one, body.text)
    except IntakeError as exc:
        raise fail(exc.status, exc.code, exc.message) from exc
    return {"ok": True, "item": got.to_dict()}


@router.get("/api/media")
def media(url: str = Query(...), name: str | None = Query(None)) -> StreamingResponse:
    return stream_media(url, name)


@router.get("/")
def index() -> HTMLResponse:
    return HTMLResponse((WEB / "index.html").read_text(encoding="utf-8"))
