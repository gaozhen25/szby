from __future__ import annotations

import re

import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.core.concurrency import run_parse
from app.deps import library_of, require_api_key
from app.http import fail
from app.intake import IntakeError, coerce_batch, parse_batch
from app.library import Library
from app.oss import StoreError
from app.schemas import LibraryPatch

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


def clean_labels(labels: list[str]) -> list[str]:
    out: list[str] = []
    for raw in labels:
        label = raw.strip()
        if not label or label in out:
            continue
        if len(label) > 40:
            raise fail(422, "invalid_label", "单个标签最多 40 个字")
        out.append(label)
    return out


@router.post("/parse", summary="接收对方上报，解析分享链接并写入素材库")
async def parse_library(request: Request, lib: Library = Depends(library_of)) -> dict:
    raw = await request.body()
    if not raw:
        raise fail(422, "empty", "没有可解析的链接")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise fail(422, "invalid_json", "请求体不是 JSON") from exc
    try:
        body = coerce_batch(payload)
        return await run_parse(parse_batch, lib, body)
    except IntakeError as exc:
        raise fail(exc.status, exc.code, exc.message) from exc


@router.get("/library", summary="查询素材库，一条记录是一张图或一个视频")
def library_list(
    q: str = Query("", max_length=100),
    platform: str = Query("", pattern="^(douyin|xhs)?$"),
    type: str = Query("", alias="type", pattern="^(image|video)?$"),
    kind: str = Query("", pattern="^(image|video)?$"),
    tag: str = Query("", max_length=40),
    category: str = Query("", max_length=40),
    industry: str = Query("", max_length=40),
    source_id: str = Query("", max_length=32),
    group: str = Query("", pattern="^(source)?$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current: int = Query(0, ge=0),
    size: int = Query(0, ge=0, le=100),
    lib: Library = Depends(library_of),
) -> dict:
    if size:
        limit = size
        offset = (max(current, 1) - 1) * size
    return lib.query(
        q=q.strip(),
        platform=platform,
        kind=type or kind,
        tag=tag.strip(),
        category=category.strip(),
        industry=industry.strip(),
        source_id=source_id.strip(),
        group=group,
        limit=limit,
        offset=offset,
    )


@router.get("/library/stats", summary="素材库数量")
def library_stats(lib: Library = Depends(library_of)) -> dict:
    return {"ok": True, "stats": lib.summary()}


@router.get("/library/{item_id}", summary="读取一条素材")
def library_get(item_id: str, lib: Library = Depends(library_of)) -> dict:
    item = lib.get(item_id)
    if item is None:
        raise fail(404, "not_found", "素材不存在")
    return {"ok": True, "item": item}


@router.patch("/library/{item_id}", summary="修改分类、备注、行业或二次使用标签")
def library_patch(item_id: str, body: LibraryPatch, lib: Library = Depends(library_of)) -> dict:
    labels = clean_labels(body.labels) if body.labels is not None else None
    category = body.category.strip() if body.category is not None else None
    industry = body.industry.strip() if body.industry is not None else None
    item = lib.patch(item_id, note=body.note, labels=labels, category=category, industry=industry)
    if item is None:
        raise fail(404, "not_found", "素材不存在")
    return {"ok": True, "item": item}


@router.delete("/library/{item_id}", summary="从素材库删除")
def library_delete(item_id: str, lib: Library = Depends(library_of)) -> dict:
    if not lib.delete(item_id):
        raise fail(404, "not_found", "素材不存在")
    return {"ok": True, "id": item_id}


@router.get("/library/{item_id}/file", summary="读取这一条素材的文件")
@router.get("/library/{item_id}/files/{index}", summary="读取这一条素材的文件")
def library_file(item_id: str, index: int = 0, lib: Library = Depends(library_of)) -> StreamingResponse:
    if index < 0:
        raise fail(404, "not_found", "文件不存在")
    try:
        found = lib.file_url(item_id, index)
    except StoreError as e:
        raise fail(502, "oss", str(e)) from e
    if found is None:
        raise fail(404, "not_found", "文件不存在")
    name, mime, chunks = found
    safe = name if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", name) else "file"
    return StreamingResponse(chunks, media_type=mime, headers={"content-disposition": f'inline; filename="{safe}"'})
