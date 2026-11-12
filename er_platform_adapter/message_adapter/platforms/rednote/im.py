"""Rednote private-message inbox and history.

Interfaces match the boss_cli xhs implementation:
  GET /api/im/web/v3/chats
  GET /api/im/web/messages/history
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from .client import RednoteClient

CHATS_URI = "/api/im/web/v3/chats"
HISTORY_URI = "/api/im/web/messages/history"


def account_summary(client: RednoteClient) -> dict[str, str]:
    me = client.user_me()
    return {
        "user_id": str(me.get("user_id") or ""),
        "nickname": str(me.get("nickname") or ""),
        "red_id": str(me.get("red_id") or ""),
        "avatar": str(me.get("image") or me.get("avatar") or me.get("images") or ""),
    }


def parse_message_content(raw: Any) -> tuple[str, int | None]:
    """Return readable text and the platform content type."""
    if raw is None:
        return "", None
    if isinstance(raw, dict):
        text = raw.get("content") or raw.get("text") or raw.get("front_chain") or ""
        ctype = raw.get("content_type")
        return str(text), int(ctype) if isinstance(ctype, int) else None
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("{"):
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                return text, None
            if isinstance(obj, dict):
                inner = obj.get("content") or obj.get("text") or obj.get("front_chain") or ""
                if isinstance(inner, str) and inner.startswith("{"):
                    try:
                        nested = json.loads(inner)
                    except json.JSONDecodeError:
                        nested = None
                    if isinstance(nested, dict):
                        inner = nested.get("content") or nested.get("text") or inner
                ctype = obj.get("content_type")
                return str(inner), int(ctype) if isinstance(ctype, int) else None
        return text, None
    return str(raw), None


def uplink_content(raw: Any, *, raw_inner: Any = None, raw_info: Any = None) -> dict[str, Any] | None:
    """Map a Rednote private message onto the existing uplink content types.

    Text and sticker codes stay 101. Images are 102, voice is 103, and video
    or live photos are 104. Sending from the backend stays text-only.
    """
    text, inner, outer = _split_content(raw, raw_inner=raw_inner, raw_info=raw_info)
    content_type = _content_type(inner, outer)
    media = _extract_media(inner, outer)
    label = _front_chain(inner, outer)
    if media["audio"]:
        return {
            "content_type": 103,
            "text": label or "[语音]",
            "content": {
                "voice": {
                    "uuid": str(uuid.uuid4()),
                    "soundPath": "",
                    "sourceUrl": media["audio"],
                    "dataSize": media["size"],
                    "duration": _duration_ms(media["duration"]),
                }
            },
        }
    if media["video"]:
        return {
            "content_type": 104,
            "text": label or "[视频]",
            "content": {
                "video": {
                    "videoPath": "",
                    "videoUUID": str(uuid.uuid4()),
                    "videoUrl": media["video"],
                    "videoType": "mp4",
                    "videoSize": media["size"],
                    "duration": _duration_ms(media["duration"]),
                    "snapshotPath": "",
                    "snapshotUUID": str(uuid.uuid4()),
                    "snapshotSize": 0,
                    "snapshotUrl": media["images"][0] if media["images"] else "",
                    "snapshotWidth": media["width"],
                    "snapshotHeight": media["height"],
                }
            },
        }
    if media["images"] and content_type != 1:
        return {
            "content_type": 102,
            "text": label or "[图片]",
            "content": {
                "picture": {
                    "sourcePath": "./",
                    "sourcePicture": {
                        "uuid": str(uuid.uuid4()),
                        "type": "image",
                        "size": media["size"] or 100,
                        "width": media["width"] or 100,
                        "height": media["height"] or 100,
                        "url": media["images"][0],
                    },
                }
            },
        }
    body = _plain_text(text) or _plain_text(label)
    if not body or (content_type == 9 and body in {"[图片]", "[语音]", "[视频]"}):
        return None
    return {"content_type": 101, "text": body, "content": {"text": body}}


def _split_content(raw: Any, *, raw_inner: Any = None, raw_info: Any = None) -> tuple[str, Any, Any]:
    outer = raw_info if isinstance(raw_info, dict) else None
    inner = raw_inner if isinstance(raw_inner, dict) else None
    if outer is None and isinstance(raw, dict):
        outer = raw
    source = raw
    if isinstance(outer, dict) and "content" in outer:
        source = outer.get("content")
    text = ""
    if isinstance(source, dict):
        text = str(source.get("content") or source.get("text") or source.get("front_chain") or "")
        if inner is None:
            inner = source
    elif isinstance(source, str):
        text = source.strip()
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                if outer is None:
                    outer = parsed
                nested = parsed.get("content")
                text = str(nested or parsed.get("front_chain") or parsed.get("text") or "")
                if isinstance(nested, str) and nested.strip().startswith("{"):
                    try:
                        decoded = json.loads(nested)
                    except json.JSONDecodeError:
                        decoded = None
                    if isinstance(decoded, dict):
                        inner = decoded
                        text = str(decoded.get("content") or decoded.get("text") or text)
                elif isinstance(nested, dict):
                    inner = nested
                    text = str(nested.get("content") or nested.get("text") or "")
                elif inner is None and any(key in parsed for key in ("link", "livePhotoVideo")):
                    inner = parsed
    return text, inner, outer


def _content_type(inner: Any, outer: Any) -> int | None:
    for source in (outer, inner):
        if not isinstance(source, dict):
            continue
        value = source.get("content_type")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _front_chain(inner: Any, outer: Any) -> str:
    for source in (outer, inner):
        if isinstance(source, dict):
            label = source.get("front_chain") or source.get("frontChain")
            if isinstance(label, str) and label.strip():
                return label.strip()
    return ""


def _plain_text(value: str) -> str:
    body = value.strip()
    if not body or _json_blob(body):
        return ""
    return body


def _json_blob(value: str) -> bool:
    if not value.startswith(("{", "[")):
        return False
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, (dict, list))


def _duration_ms(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number <= 0:
        return 0
    return int(number if number > 1000 else number * 1000)


def _positive_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _positive_int(value: Any) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _classify_url(url: str) -> str:
    lowered = url.lower()
    if "/audio/" in lowered or lowered.endswith((".mp3", ".m4a", ".aac", ".wav", ".amr")):
        return "audio"
    if "/chat_livephoto/" in lowered or "/video/" in lowered:
        return "video"
    if "msg-img" in lowered or any(ext in lowered for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return "image"
    return "other"


def _extract_media(inner: Any, outer: Any) -> dict[str, Any]:
    images: list[str] = []
    audio = ""
    video = ""
    duration = 0
    width = 0
    height = 0
    size = 0

    def push(url: str) -> None:
        nonlocal audio, video
        kind = _classify_url(url)
        if kind == "image" and url not in images:
            images.append(url)
        elif kind == "audio" and not audio:
            audio = url
        elif kind == "video" and not video:
            video = url

    for source in (inner, outer):
        if not isinstance(source, dict):
            continue
        for key in ("image_url", "imageUrl", "pic_url", "picUrl", "url", "link"):
            value = source.get(key)
            if isinstance(value, str) and value.startswith("http"):
                push(value)
        for key in ("voice_url", "voiceUrl", "audio_url", "audioUrl"):
            value = source.get(key)
            if isinstance(value, str) and value.startswith("http"):
                push(value)
        live = source.get("livePhotoVideo")
        if isinstance(live, dict):
            link = live.get("videoLink")
            if isinstance(link, str) and link.startswith("http"):
                video = video or link
            duration = duration or _positive_number(live.get("duration"))
        duration = duration or _positive_number(source.get("duration"))
        width = width or _positive_int(source.get("width"))
        height = height or _positive_int(source.get("height"))
        size = size or _positive_int(source.get("size") or source.get("data_size"))
    return {
        "images": images,
        "audio": audio,
        "video": video,
        "duration": duration,
        "width": width,
        "height": height,
        "size": size,
    }


def list_chats(client: RednoteClient, *, limit: int = 100, page: int = 0) -> dict[str, Any]:
    return client._request(
        "GET",
        CHATS_URI,
        params={
            "limit": str(limit),
            "complete": "true",
            "page": str(page),
            "source": "pc",
        },
    )


def fetch_history(
    client: RednoteClient,
    chat_user_id: str,
    *,
    last_id: int,
    start_id: int = 0,
    limit: int = 30,
) -> list[dict[str, Any]]:
    data = client._request(
        "GET",
        HISTORY_URI,
        params={
            "chat_user_id": str(chat_user_id),
            "last_id": str(last_id),
            "start_id": str(start_id),
            "limit": str(limit),
        },
    )
    if isinstance(data, dict):
        return list(data.get("out_message_list") or data.get("messages") or [])
    return []


def fetch_since(
    client: RednoteClient,
    chat_user_id: str,
    *,
    since_store_id: int,
    max_store_id: int,
    page_size: int = 30,
) -> list[dict[str, Any]]:
    """Return messages with store_id greater than since_store_id, oldest first."""
    if max_store_id <= since_store_id:
        return []
    messages: list[dict[str, Any]] = []
    seen: set[str] = set()
    last_id = int(max_store_id)
    start_id = int(since_store_id)
    while last_id > start_id:
        batch = fetch_history(
            client,
            chat_user_id,
            last_id=last_id,
            start_id=start_id,
            limit=page_size,
        )
        if not batch:
            break
        store_ids: list[int] = []
        for item in batch:
            mid = str(item.get("id") or item.get("store_id") or "")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            messages.append(item)
            try:
                store_ids.append(int(item.get("store_id")))
            except (TypeError, ValueError):
                pass
        if len(batch) < page_size or not store_ids:
            break
        min_sid = min(store_ids)
        if min_sid <= start_id + 1:
            break
        last_id = min_sid - 1
    messages.sort(key=lambda item: int(item.get("store_id") or 0))
    return messages
