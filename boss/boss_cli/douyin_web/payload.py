"""Normalize Douyin IM payloads for the local web UI (BOSS webchat shape)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from boss_cli.webchat.payload import format_msg_time, render_emoticons

DY_MEDIA_HOST_SUFFIXES = (
    ".douyinpic.com",
    ".douyin.com",
    ".ibyteimg.com",
    ".bytednsdoc.com",
    ".byteimg.com",
    ".snssdk.com",
    ".amemv.com",
    ".tiktokcdn.com",
    ".tiktokcdn-us.com",
    ".tiktokcdn-eu.com",
    ".pstatp.com",
    ".bytecdn.cn",
    ".ibytedtos.com",
    ".bytedance.net",
    ".bytedance.com",
    ".zjcdn.com",
    ".douyinstatic.com",
)
DY_MEDIA_HOSTS = {
    "douyin.com",
    "douyinpic.com",
    "ibyteimg.com",
    "pstatp.com",
    "douyinstatic.com",
    "tiktokcdn.com",
    "tiktokcdn-us.com",
    "tiktokcdn-eu.com",
}

_HEIC_EXT_RE = re.compile(r"\.(heic|heif)(?=$|\?)", re.I)
_SIGN_HOST_RE = re.compile(r"^(https://p\d+(?:-[a-z0-9]+)*)-sign(\.[^/]+)", re.I)
_AVATAR_KEYS = (
    "avatar_300x300",
    "avatar_168x168",
    "avatar_medium",
    "avatar_larger",
    "avatar_thumb",
)


def _abs_http_url(value: str) -> str:
    text = (value or "").strip()
    if text.startswith("//"):
        return "https:" + text
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return ""


def allowed_media_url(url: str) -> str | None:
    normalized = _abs_http_url(url or "")
    if not normalized:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if not host or host.startswith("[") or host.replace(".", "").isdigit():
        return None
    if host in DY_MEDIA_HOSTS or host.endswith(DY_MEDIA_HOST_SUFFIXES):
        return normalized
    return None


def _collect_avatar_urls(user: dict[str, Any]) -> list[str]:
    urls: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.get("url_list") or []:
                add(item)
            add(value.get("url") or value.get("uri"))
            return
        text = _abs_http_url(str(value or ""))
        if text and text not in urls:
            urls.append(text)

    for key in _AVATAR_KEYS:
        add(user.get(key))
    add(user.get("avatar"))
    add(user.get("avatar_url"))
    return urls


def _avatar_rank(url: str) -> tuple[int, int, int]:
    lower = url.lower()
    if ".heic" in lower or ".heif" in lower:
        fmt = 9
    elif ".jpeg" in lower or ".jpg" in lower:
        fmt = 0
    elif ".webp" in lower or ".png" in lower:
        fmt = 1
    else:
        fmt = 2
    signed = 1 if "-sign." in lower or "x-signature=" in lower else 0
    return (fmt, signed, 0 if "300x300" in lower or "168x168" in lower else 1)


def pick_avatar_url(urls: list[str]) -> str:
    clean = [_abs_http_url(str(u)) for u in urls]
    clean = [u for u in clean if u]
    if not clean:
        return ""
    return sorted(clean, key=_avatar_rank)[0]


def media_url_fallbacks(url: str) -> list[str]:
    """Browser-friendly variants: JPEG instead of HEIC, unsigned CDN host."""
    base = _abs_http_url(url or "")
    if not base:
        return []
    out: list[str] = []

    def add(value: str) -> None:
        text = _abs_http_url(value)
        if text and text not in out:
            out.append(text)

    jpeg = _HEIC_EXT_RE.sub(".jpeg", base)
    add(jpeg)
    add(base)
    for item in (jpeg, base):
        unsigned = _SIGN_HOST_RE.sub(r"\1\2", item, count=1)
        add(unsigned)
    return out


def avatar_from_user(user: dict[str, Any]) -> str:
    if not isinstance(user, dict):
        return ""
    return pick_avatar_url(_collect_avatar_urls(user))


def public_me(summary: dict[str, Any], *, avatar: str = "") -> dict[str, Any]:
    uid = str(summary.get("uid") or "")
    return {
        "uid": uid,
        "name": str(summary.get("nickname") or "我"),
        "avatar": avatar or "",
        "uniqueId": str(summary.get("unique_id") or summary.get("short_id") or ""),
    }


def _pick_http_url(val: Any) -> str:
    if isinstance(val, str):
        return _abs_http_url(val)
    if isinstance(val, dict):
        for key in ("url_list", "origin_url_list", "large_url_list", "medium_url_list", "thumb_url_list"):
            for item in val.get(key) or []:
                url = _abs_http_url(str(item))
                if url:
                    return url
        # Emoji / sticker payloads often only expose uri (not url_list).
        for key in ("url", "uri", "origin_url", "download_url"):
            url = _abs_http_url(str(val.get(key) or ""))
            if url:
                return url
            uri = str(val.get(key) or "").strip()
            if uri and not uri.startswith("http") and "/" in uri:
                return f"https://p3.douyinpic.com/obj/{uri.lstrip('/')}"
    return ""


def conversation_item(
    *,
    index: int,
    conversation_id: str,
    conversation_short_id: int,
    peer_uid: str = "",
    peer_unique_id: str = "",
    name: str = "",
    avatar: str = "",
    last_text: str = "",
    last_time: str = "",
    last_ts: int = 0,
) -> dict[str, Any]:
    cid = str(conversation_id or "")
    return {
        "index": index,
        "uid": peer_uid or "",
        "friendId": cid,
        "name": name or peer_uid or "未知",
        "job": peer_unique_id or "",
        "avatar": avatar or "",
        "lastMessage": last_text or "",
        "lastTime": last_time or "",
        "lastTs": int(last_ts or 0),
        "unread": 0,
        "_meta": {
            "conversation_id": cid,
            "conversation_short_id": int(conversation_short_id or 0),
            "peer_uid": peer_uid or "",
            "peer_unique_id": peer_unique_id or "",
        },
    }


def history_message(
    auth: Any,
    raw: dict[str, Any],
    *,
    my_uid: str,
    peer_name: str = "",
    peer_avatar: str = "",
    my_name: str = "我",
    my_avatar: str = "",
    resolve_profiles: bool = True,
) -> dict[str, Any] | None:
    from boss_cli.douyin.im import parse_media_urls, resolve_user_profile

    mt = int(raw.get("message_type") or 0)
    if mt == 50001:
        return None

    sender = str(raw.get("sender") or "")
    mine = bool(my_uid) and sender == my_uid
    mid = str(raw.get("server_message_id") or raw.get("index_in_conversation") or "")
    content = str(raw.get("content") or "")
    media = parse_media_urls(content)
    raw_obj = media.get("raw") if isinstance(media.get("raw"), dict) else {}
    urls = list(media.get("urls") or [])

    kind = "text"
    text = ""
    image: dict[str, Any] | None = None
    audio: dict[str, Any] | None = None
    file_info: dict[str, Any] | None = None

    if mt == 7:
        try:
            text = str(json.loads(content).get("text") or "")
        except Exception:
            text = content[:500]
        text = render_emoticons(text)
    elif mt == 5:
        kind = "emoji"
        from boss_cli.douyin_web.im_media import pick_im_image_url, remember_image_urls

        url = pick_im_image_url(urls) if urls else ""
        if not url:
            url = _pick_http_url(raw_obj.get("url")) or _pick_http_url(raw_obj.get("emoji_url"))
        if urls:
            remember_image_urls(mid, urls)
        # Always attach mid so /api/media can resolve from cache even if CDN url is empty.
        image = {"preview": url or "", "origin": url or "", "mid": mid} if (url or mid) else None
        label = str(raw_obj.get("display_name") or "").strip()
        text = label or "[表情]"
    elif mt == 27:
        kind = "image"
        from boss_cli.douyin_web.im_media import pick_im_image_url, remember_image_urls, remember_inline_pic

        ru = raw_obj.get("resource_url") if isinstance(raw_obj.get("resource_url"), dict) else {}
        skey = str(ru.get("skey") or raw_obj.get("skey") or "")
        oid = str(ru.get("oid") or raw_obj.get("oid") or "")
        inline = str(raw_obj.get("inline_pic") or "")
        if urls:
            remember_image_urls(mid, urls)
        if inline:
            remember_inline_pic(mid, inline)
        url = pick_im_image_url(urls)
        if not url and oid:
            url = f"https://p3.douyinpic.com/obj/{oid}"
        # Always keep image meta for type=27 so UI can hit /api/media?mid=&skey=&oid=
        # even when WS content lacks CDN url lists (common for live pushes).
        if url or inline or oid or skey or mid:
            image = {
                "preview": url or "",
                "origin": url or "",
                "skey": skey,
                "oid": oid,
                "mid": mid,
            }
        text = "[图片]"
    elif mt == 17:
        kind = "voice"
        url = urls[0] if urls else ""
        duration = 0
        if isinstance(raw_obj, dict):
            duration = int(raw_obj.get("duration") or raw_obj.get("audio_duration") or 0)
        audio = {"url": url, "duration": duration, "mid": mid} if url else None
        text = "[语音]" + (f" {duration // 1000}s" if duration > 0 else "")
    elif mt in (8, 77, 105, 110) or (
        isinstance(raw_obj, dict)
        and (
            raw_obj.get("aweType") in (800, "800")
            or raw_obj.get("itemId")
            or raw_obj.get("share_id")
            or raw_obj.get("awemeType") is not None
        )
        and mt not in (5, 7, 17, 27)
    ):
        from boss_cli.douyin.im import _extract_share_item_id

        item_id = _extract_share_item_id(raw_obj)
        if not item_id:
            for key in ("itemId", "item_id", "aweme_id", "awemeId", "video_id"):
                val = raw_obj.get(key)
                if val not in (None, "", 0, "0"):
                    item_id = str(val)
                    break
        title = str(
            raw_obj.get("content_title")
            or raw_obj.get("content_name")
            or raw_obj.get("title")
            or ""
        ).strip() or "分享"
        thumb = (
            _pick_http_url(raw_obj.get("cover_url"))
            or _pick_http_url(raw_obj.get("cover_url_v2"))
            or _pick_http_url(raw_obj.get("content_thumb"))
            or (urls[0] if urls else "")
        )
        aweme_type = raw_obj.get("awemeType")
        is_images = aweme_type in (68, "68") or mt in (77, 110)
        kind = "card" if is_images else "video"
        if item_id:
            link = f"https://www.douyin.com/video/{item_id}"
            text = title
            if thumb:
                image = {"preview": thumb, "origin": link, "mid": mid}
            else:
                image = {"preview": "", "origin": link, "mid": mid}
            file_info = {"url": link, "name": title, "mime": "text/html", "size": 0}
        else:
            # Keep share kind even without item id so UI does not fall back to plain「分享」.
            text = title
            if thumb:
                image = {"preview": thumb, "origin": thumb, "mid": mid}
    else:
        text = content[:500] if content else "[消息]"

    ts = int(raw.get("create_time_ms") or 0)
    name = my_name if mine else peer_name or sender
    avatar = my_avatar if mine else peer_avatar
    if resolve_profiles and mine and not avatar and sender:
        prof = resolve_user_profile(auth, sender, str(raw.get("sec_sender") or ""))
        avatar = avatar_from_user(prof)
    elif resolve_profiles and not mine and sender and not peer_name and not peer_avatar:
        prof = resolve_user_profile(auth, sender, str(raw.get("sec_sender") or ""))
        if name == sender:
            name = str(prof.get("nickname") or sender)
        if not avatar:
            avatar = avatar_from_user(prof)

    return {
        "mid": mid,
        "text": text or "",
        "time": format_msg_time(ts),
        "ts": ts if ts > 10_000_000_000 else ts * 1000 if ts else 0,
        "mine": mine,
        "fromUid": sender,
        "kind": kind,
        "image": image,
        "audio": audio,
        "file": file_info,
        "name": name,
        "avatar": avatar,
    }


def live_message(
    *,
    conversation_id: str,
    peer_uid: str,
    text: str,
    mine: bool,
    name: str = "",
    avatar: str = "",
    from_uid: str = "",
    mid: Any = None,
    ts: int | None = None,
    kind: str = "text",
    image: dict[str, Any] | None = None,
    audio: dict[str, Any] | None = None,
    file: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now_ms = int(datetime.now().timestamp() * 1000)
    stamp = format_msg_time(ts or now_ms) or datetime.now().strftime("%H:%M")
    sender = str(from_uid or (peer_uid if not mine else "") or "")
    return {
        "type": "message",
        "uid": peer_uid or conversation_id,
        "friendId": conversation_id,
        "name": name,
        "avatar": avatar or "",
        "text": render_emoticons(text or ""),
        "mine": bool(mine),
        "fromUid": sender,
        "mid": mid,
        "time": stamp,
        "ts": ts or now_ms,
        "kind": kind or "text",
        "image": image,
        "audio": audio,
        "file": file,
    }


def message_preview(raw: dict[str, Any]) -> str:
    from boss_cli.douyin.im import message_body

    class _Auth:
        pass

    try:
        return message_body(_Auth(), raw)[:120]
    except Exception:
        mt = int(raw.get("message_type") or 0)
        if mt == 7:
            try:
                return str(json.loads(str(raw.get("content") or "")).get("text") or "")[:120]
            except Exception:
                return ""
        return "[消息]"
