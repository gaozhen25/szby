from __future__ import annotations

import re

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.cdn import host_allowed, referer_for
from app.extract import as_mp4_start


def stream_media(url: str, name: str | None) -> StreamingResponse:
    if not host_allowed(url):
        raise HTTPException(status_code=400, detail="host not allowed")
    referer = referer_for(url)
    client = httpx.Client(follow_redirects=True, timeout=60, trust_env=False)
    try:
        req = client.build_request(
            "GET",
            url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": referer},
        )
        resp = client.send(req, stream=True)
    except httpx.HTTPError as e:
        client.close()
        raise HTTPException(status_code=502, detail=str(e)) from e
    if resp.status_code >= 400:
        client.close()
        raise HTTPException(status_code=502, detail=f"upstream {resp.status_code}")

    headers: dict[str, str] = {}
    ctype = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    safe = name.strip() if name else ""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", safe):
        safe = ""
    want_mp4 = safe.endswith(".mp4")
    if want_mp4 and ctype in ("", "application/octet-stream", "binary/octet-stream", "video/quicktime"):
        headers["content-type"] = "video/mp4"
    elif ctype:
        headers["content-type"] = resp.headers.get("content-type") or ctype
    if safe:
        headers["content-disposition"] = f'attachment; filename="{safe}"'
    elif resp.headers.get("content-disposition"):
        headers["content-disposition"] = resp.headers["content-disposition"]

    def chunks():
        try:
            pending = b""
            patched = not want_mp4
            for chunk in resp.iter_bytes():
                if patched:
                    yield chunk
                    continue
                pending += chunk
                if len(pending) < 32:
                    continue
                patched = True
                yield as_mp4_start(pending)
                pending = b""
            if pending:
                yield as_mp4_start(pending) if want_mp4 else pending
        finally:
            resp.close()
            client.close()

    return StreamingResponse(chunks(), headers=headers, status_code=200)
