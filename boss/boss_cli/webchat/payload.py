"""Sanitize recruiter chat payloads for the local web UI (no cookies / securityId)."""

from __future__ import annotations

import html
import re
from datetime import datetime
from urllib.parse import unquote, urlparse
from typing import Any


AVATAR_HOST_SUFFIXES = (".zhipin.com", ".bosszhipin.com")
AVATAR_HOSTS = {"zhipin.com", "bosszhipin.com"}


def _first_str(obj: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _abs_http_url(value: str) -> str:
    text = value.strip()
    if text.startswith("//"):
        return "https:" + text
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return ""


def pick_avatar(obj: dict[str, Any] | None) -> str:
    """Return a http(s) avatar URL from common BOSS friend/user fields."""
    if not isinstance(obj, dict):
        return ""
    for key in (
        "tinyAvatar",
        "avatar",
        "headImg",
        "headLarge",
        "webpHeadImg",
        "showAvatar",
        "tinyUrl",
        "large",
        "small",
        "geekAvatar",
        "photoUrl",
        "headPortrait",
    ):
        value = obj.get(key)
        if isinstance(value, str):
            url = _abs_http_url(value)
            if url:
                return url
        elif isinstance(value, dict):
            nested = pick_avatar(value)
            if nested:
                return nested
    for inner_key in ("user", "geekInfo", "friend", "boss"):
        inner = obj.get(inner_key)
        if isinstance(inner, dict):
            nested = pick_avatar(inner)
            if nested:
                return nested
    return ""


def allowed_avatar_url(url: str) -> str | None:
    """Allow only BOSS CDN hosts (blocks SSRF via the local proxy)."""
    normalized = _abs_http_url(url or "")
    if not normalized:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if not host or host.startswith("[") or host.replace(".", "").isdigit():
        return None
    if host in AVATAR_HOSTS or host.endswith(AVATAR_HOST_SUFFIXES):
        return normalized
    return None


def query_param(query: str, name: str) -> str:
    """Read a query value without treating '+' as space (auth_key uses '+')."""
    prefix = f"{name}="
    for part in (query or "").split("&"):
        if part.startswith(prefix):
            return unquote(part[len(prefix) :])
    return ""


def message_ts(msg: dict[str, Any]) -> int:
    raw = msg.get("time") or msg.get("addTime") or 0
    try:
        ts = int(raw)
    except (TypeError, ValueError):
        return 0
    if ts > 10_000_000_000:
        return ts
    return ts * 1000 if ts > 0 else 0


def _image_from_body(body: dict[str, Any]) -> dict[str, Any] | None:
    image = body.get("image")
    preview = ""
    origin = ""
    if isinstance(image, str):
        origin = _abs_http_url(image)
    elif isinstance(image, dict):
        tiny = image.get("tinyImage") if isinstance(image.get("tinyImage"), dict) else {}
        orig = image.get("originImage") if isinstance(image.get("originImage"), dict) else {}
        preview = _abs_http_url(_first_str(tiny, "url") if isinstance(tiny, dict) else "")
        origin = _abs_http_url(_first_str(orig, "url") if isinstance(orig, dict) else "") or _abs_http_url(
            _first_str(image, "url", "originUrl", "tinyUrl")
        )
        if not preview:
            preview = origin
    if not origin and not preview:
        return None
    return {"preview": preview or origin, "origin": origin or preview}


EMOJI_MAP = {
    "微笑": "😊", "开心": "😄", "大笑": "😄", "呲牙": "😁", "偷笑": "😏", "愉快": "🙂",
    "憨笑": "😁", "坏笑": "😏", "奸笑": "😏", "调皮": "😜", "可爱": "🥰", "色": "😍",
    "害羞": "😊", "得意": "😎", "酷": "😎", "爱心": "❤️", "示爱": "💘", "爱情": "💑",
    "飞吻": "😘", "亲亲": "😗", "拥抱": "🤗", "赞": "👍", "强": "👍", "弱": "👎",
    "鼓掌": "👏", "握手": "🤝", "胜利": "✌️", "耶": "✌️", "抱拳": "🙏", "OK": "👌",
    "拳头": "👊", "玫瑰": "🌹", "凋谢": "🥀", "礼物": "🎁", "蛋糕": "🎂", "太阳": "☀️",
    "月亮": "🌙", "咖啡": "☕", "啤酒": "🍺", "西瓜": "🍉", "狗头": "🐶", "猪头": "🐷",
    "捂脸": "🤦", "笑哭": "😂", "流泪": "😢", "大哭": "😭", "可怜": "🥺", "委屈": "🥺",
    "快哭了": "😢", "难过": "😞", "衰": "😞", "尴尬": "😅", "冷汗": "😅", "流汗": "😅",
    "汗": "😅", "疑问": "❓", "惊讶": "😮", "惊恐": "😱", "发怒": "😡", "愤怒": "😡",
    "抓狂": "😫", "睡": "😴", "睡觉": "😴", "困": "😪", "骷髅": "💀", "便便": "💩",
    "炸弹": "💣", "刀": "🔪", "菜刀": "🔪", "吃瓜": "🍉", "机智": "🧠", "嘿哈": "🤠",
    "皱眉": "😟", "白眼": "🙄", "鄙视": "😒", "阴险": "😈", "咒骂": "🤬", "再见": "👋",
    "挥手": "👋", "加油": "💪", "奋斗": "💪", "社会社会": "😎", "旺柴": "🐶",
    "闭嘴": "🤐", "发呆": "😐", "呆": "😐", "呆萌": "😇", "红脸": "😳", "撇嘴": "😒",
    "嘘": "🤫", "晕": "😵", "敲打": "🔨", "擦汗": "😅", "抠鼻": "🤏", "哈欠": "🥱",
    "左哼哼": "😤", "右哼哼": "😤", "吓": "😨", "吐": "🤮", "饥饿": "😋", "悠闲": "😌",
    "傲慢": "😤", "糗大了": "😳",
}


def render_emoticons(text: str) -> str:
    """Turn BOSS `[狗头]` codes into unicode so every bubble is readable text."""
    if not text or "[" not in text:
        return text
    out = text
    for name, glyph in EMOJI_MAP.items():
        out = out.replace(f"[{name}]", glyph)
    return out


def clean_boss_tags(text: str) -> str:
    """清理 BOSS 消息模板标签（微信号/手机号等可复制区域）。

    BOSS 会用 ``<copy>`` / ``<phone>`` 等标签包裹可复制内容，
    部分场景下又被转义成 ``&lt;copy&gt;`` / ``&lt;/phone&gt;``。
    统一反转义 + 移除标签，返回纯文本。
    """
    if not text:
        return ""
    t = html.unescape(str(text))
    t = re.sub(
        r"</?(?:copy|phone|job|company|encrypt|tel|span)\b[^>]*>",
        "",
        t,
        flags=re.IGNORECASE,
    )
    return t.strip()


def guess_mime(name: str = "", url: str = "", hinted: str = "") -> str:
    hinted = (hinted or "").split(";")[0].strip().lower()
    if hinted and hinted not in {"application/octet-stream", "binary/octet-stream"}:
        return hinted
    blob = f"{name} {url}".lower()
    mapping = (
        (".pdf", "application/pdf"),
        (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (".doc", "application/msword"),
        (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        (".xls", "application/vnd.ms-excel"),
        (".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        (".ppt", "application/vnd.ms-powerpoint"),
        (".zip", "application/zip"),
        (".txt", "text/plain"),
        (".mp3", "audio/mpeg"),
        (".m4a", "audio/mp4"),
        (".amr", "audio/amr"),
        (".wav", "audio/wav"),
        (".aac", "audio/aac"),
        (".mp4", "video/mp4"),
        (".png", "image/png"),
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".gif", "image/gif"),
        (".webp", "image/webp"),
    )
    for ext, mime in mapping:
        if ext in blob:
            return mime
    return hinted


def _audio_from_body(body: dict[str, Any]) -> dict[str, Any] | None:
    sound = body.get("sound") or body.get("audio") or body.get("voice")
    if not isinstance(sound, dict):
        return None
    url = _abs_http_url(_first_str(sound, "url", "originUrl", "fileUrl", "src"))
    if not url:
        return None
    duration = sound.get("duration") or sound.get("length") or sound.get("seconds") or 0
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        duration = 0
    if duration > 1000:
        duration = int(duration / 1000)
    return {"url": url, "duration": duration}


def _file_from_body(body: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [
        body.get("file"),
        body.get("fileInfo"),
        body.get("attachment"),
        body.get("article"),
        body.get("document"),
    ]
    file_obj = next((item for item in candidates if isinstance(item, dict)), None)
    url = ""
    name = ""
    mime = ""
    size = 0
    if file_obj:
        url = _abs_http_url(_first_str(file_obj, "url", "originUrl", "fileUrl", "pdfUrl", "downloadUrl", "src"))
        name = _first_str(file_obj, "name", "fileName", "title", "file_name") or "附件"
        mime = _first_str(file_obj, "mime", "mimeType", "contentType")
        size = file_obj.get("size") or file_obj.get("fileSize") or 0
    if not url:
        url = _abs_http_url(_first_str(body, "fileUrl", "pdfUrl", "url"))
        name = name or _first_str(body, "fileName", "name") or "附件"
    if not url:
        return None
    blob = f"{name} {url}".lower()
    looks_file = any(ext in blob for ext in (
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".zip",
    ))
    if not looks_file and not file_obj:
        return None
    try:
        size = int(size or 0)
    except (TypeError, ValueError):
        size = 0
    mime = guess_mime(name, url, mime)
    return {"url": url, "name": name or "附件", "mime": mime, "size": size}


def _resume_card(body: dict[str, Any]) -> dict[str, Any] | None:
    resume = body.get("resume")
    if not isinstance(resume, dict):
        return None
    user = resume.get("user") if isinstance(resume.get("user"), dict) else {}
    pdf = _abs_http_url(_first_str(resume, "pdfUrl", "resumeUrl", "fileUrl", "previewUrl", "annexUrl"))
    name = _first_str(user, "name") if isinstance(user, dict) else ""
    return {
        "name": name,
        "avatar": pick_avatar(user) if isinstance(user, dict) else "",
        "age": _first_str(resume, "age"),
        "education": _first_str(resume, "education"),
        "workYear": _first_str(resume, "workYear"),
        "city": _first_str(resume, "city"),
        "salary": _first_str(resume, "salary", "jobSalary"),
        "position": _first_str(resume, "position", "positionCategory"),
        "expect": _first_str(resume, "content1"),
        "school": _first_str(resume, "content2"),
        "status": _first_str(resume, "applyStatus"),
        "footer": _first_str(resume, "bottomText"),
        "title": _first_str(body, "headTitle") or "在线简历",
        "pdfUrl": pdf,
    }


def chronological(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Oldest first, like a normal chat transcript."""
    def _key(msg: dict[str, Any]) -> tuple[int, int]:
        ts = msg.get("ts")
        mid = msg.get("mid")
        ts_n = int(ts) if isinstance(ts, int) else 0
        mid_n = int(mid) if isinstance(mid, int) else 0
        return (ts_n, mid_n)

    return sorted(messages, key=_key)


def safe_peer_name(name: str, *, my_name: str = "", my_encrypt: str = "") -> str:
    """Keep human nicknames; drop encryptIds, uids, and the recruiter's own name."""
    text = str(name or "").strip()
    if not text:
        return ""
    if my_name and text == str(my_name).strip():
        return ""
    if my_encrypt and text == str(my_encrypt).strip():
        return ""
    if text.isdigit():
        return ""
    if len(text) >= 16 and all(ch.isalnum() or ch in "+/=_-." for ch in text):
        return ""
    return text


def public_me(user_info: dict[str, Any]) -> dict[str, Any]:
    uid = user_info.get("userId") or user_info.get("uid") or 0
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        uid = 0
    return {
        "uid": uid,
        "name": _first_str(user_info, "name", "showName", "nickName") or "我",
        "avatar": pick_avatar(user_info),
    }


def conversation_item(
    friend: dict[str, Any],
    *,
    index: int,
    last_text: str = "",
    last_time: str = "",
) -> dict[str, Any]:
    uid = friend.get("uid") or friend.get("friendId") or 0
    friend_id = friend.get("friendId") or friend.get("uid") or 0
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        uid = 0
    try:
        friend_id = int(friend_id)
    except (TypeError, ValueError):
        friend_id = 0
    last = last_text or _first_str(friend, "lastMsg", "lastText")
    last_info = friend.get("lastMessageInfo") or friend.get("lastMsgInfo") or {}
    if isinstance(last_info, dict) and not last:
        last = _first_str(last_info, "showText", "text")
    stamp = last_time or _first_str(friend, "lastTime")
    if isinstance(last_info, dict) and not stamp:
        stamp = _first_str(last_info, "time", "addTime")
    unread = friend.get("unreadCount") or friend.get("unreadMsgCount") or 0
    try:
        unread = int(unread)
    except (TypeError, ValueError):
        unread = 0
    return {
        "index": index,
        "uid": uid,
        "friendId": friend_id,
        "encryptGeekId": _first_str(
            friend, "encryptGeekId", "encryptUid", "encryptFriendId", "encryptGeekUid"
        ),
        "name": _first_str(friend, "name", "geekName", "showName") or str(friend_id or uid or ""),
        "job": _first_str(friend, "jobName", "job", "expectPositionName"),
        "salary": _first_str(friend, "salaryDesc"),
        "company": _first_str(friend, "companyName", "brandName"),
        "avatar": pick_avatar(friend),
        "lastMessage": last,
        "lastTime": stamp,
        "unread": unread,
    }


def message_text(msg: dict[str, Any], *, kind: str = "text") -> str:
    body = msg.get("body")
    if isinstance(body, str) and body.strip():
        return render_emoticons(body.strip())
    if isinstance(body, dict):
        text = _first_str(body, "text", "showText")
        if text:
            return render_emoticons(text)
        if kind == "resume":
            resume = body.get("resume") if isinstance(body.get("resume"), dict) else {}
            user = resume.get("user") if isinstance(resume.get("user"), dict) else {}
            name = _first_str(user, "name") if isinstance(user, dict) else ""
            title = _first_str(body, "headTitle")
            return title or (f"简历 · {name}" if name else "在线简历")
        if kind == "voice":
            audio = _audio_from_body(body) or {}
            duration = int(audio.get("duration") or 0)
            return f"[语音 {duration}秒]" if duration else "[语音]"
        if kind in {"image", "pdf", "file"}:
            title = _first_str(body, "headTitle", "fileName")
            if title:
                return title
            file_info = _file_from_body(body)
            if file_info:
                return f"[文件] {file_info['name']}"
            if kind == "image":
                return "[图片]"
            if kind == "pdf":
                return "[PDF]"
            return "[文件]"
    direct = _first_str(msg, "text", "showText")
    if direct:
        return render_emoticons(direct)
    push = str(msg.get("pushText") or "")
    if ":" in push:
        push = push.split(":", 1)[-1].strip()
    if push:
        return render_emoticons(push)
    labels = {
        "image": "[图片]",
        "resume": "在线简历",
        "pdf": "[PDF]",
        "file": "[文件]",
        "voice": "[语音]",
    }
    return labels.get(kind, "")


def format_msg_time(raw: Any) -> str:
    if raw is None or raw == "":
        return ""
    if isinstance(raw, str) and not raw.isdigit():
        return raw
    try:
        ts = int(raw)
    except (TypeError, ValueError):
        return str(raw)
    if ts > 10_000_000_000:
        ts = int(ts / 1000)
    if ts <= 0:
        return ""
    try:
        when = datetime.fromtimestamp(ts)
    except (OSError, OverflowError, ValueError):
        return ""
    now = datetime.now()
    if when.date() == now.date():
        return when.strftime("%H:%M")
    if when.year == now.year:
        return when.strftime("%m-%d %H:%M")
    return when.strftime("%Y-%m-%d %H:%M")


def _uid(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def mqtt_is_mine(
    *,
    from_uid: int = 0,
    to_uid: int = 0,
    flag: int = 0,
    my_uid: int = 0,
    from_name: str = "",
    my_encrypt: str = "",
    my_name: str = "",
) -> bool:
    """Classify a live MQTT frame as sent by the logged-in recruiter.

    Dual-identity accounts often echo our send with a different from.uid, while
    protobuf field 2 (decoded as name) is encryptUid or the recruiter display name.
    """
    from_uid = _uid(from_uid)
    to_uid = _uid(to_uid)
    my_uid = _uid(my_uid)
    flag = _uid(flag)
    from_name = str(from_name or "")
    my_encrypt = str(my_encrypt or "")
    my_name = str(my_name or "")
    if my_uid and from_uid == my_uid:
        return True
    if my_encrypt and from_name and from_name == my_encrypt:
        return True
    if flag & 0x10000:
        if my_uid and to_uid == my_uid and from_uid != my_uid:
            return False
        return True
    if my_name and from_name == my_name and my_uid and to_uid and to_uid != my_uid:
        return True
    return False


def message_is_mine(msg: dict[str, Any], *, my_uid: int = 0, peer_uid: int = 0) -> bool:
    """Decide whether this history/live message was sent by the logged-in user.

    Recruiter historyMsg sets received=true on both sides, so uid/flag must win.
    """
    from_obj = msg.get("from") if isinstance(msg.get("from"), dict) else {}
    from_uid = _uid(from_obj.get("uid") or msg.get("fromUid"))
    to_obj = msg.get("to") if isinstance(msg.get("to"), dict) else {}
    to_uid = _uid(to_obj.get("uid") or msg.get("toUid"))
    my_uid = _uid(my_uid)
    peer_uid = _uid(peer_uid)
    if my_uid and from_uid == my_uid:
        return True
    if peer_uid and from_uid == peer_uid:
        return False
    flag = _uid(msg.get("flag"))
    if flag & 0x10000:
        return True
    if peer_uid and from_uid and from_uid != peer_uid:
        return True
    if my_uid and to_uid == my_uid and from_uid and from_uid != my_uid:
        return False
    if "received" in msg:
        return not bool(msg.get("received"))
    return False


def history_message(msg: dict[str, Any], *, my_uid: int = 0, peer_uid: int = 0) -> dict[str, Any]:
    from_obj = msg.get("from") if isinstance(msg.get("from"), dict) else {}
    from_uid = _uid(from_obj.get("uid") or msg.get("fromUid"))
    mine = message_is_mine(msg, my_uid=my_uid, peer_uid=peer_uid)
    mid = msg.get("mid") or msg.get("msgId") or msg.get("cmid")
    try:
        mid = int(mid) if mid is not None else None
    except (TypeError, ValueError):
        pass
    msg_type = msg.get("type")
    body = msg.get("body")
    if msg_type is None and isinstance(body, dict):
        msg_type = body.get("type")
    image = _image_from_body(body) if isinstance(body, dict) else None
    resume = _resume_card(body) if isinstance(body, dict) else None
    file_info = _file_from_body(body) if isinstance(body, dict) else None
    audio = _audio_from_body(body) if isinstance(body, dict) else None
    body_type = body.get("type") if isinstance(body, dict) else None
    kind = "text"
    if resume or body_type == 9:
        kind = "resume"
        if resume and resume.get("pdfUrl"):
            file_info = file_info or {
                "url": resume["pdfUrl"],
                "name": "简历.pdf",
                "mime": "application/pdf",
                "size": 0,
            }
    elif image or body_type == 3:
        kind = "image"
    elif audio or body_type == 2:
        kind = "voice"
    elif file_info:
        mime = str(file_info.get("mime") or "")
        name = str(file_info.get("name") or "").lower()
        kind = "pdf" if mime == "application/pdf" or name.endswith(".pdf") else "file"
    text = message_text(msg, kind=kind)
    if not text and kind == "text":
        text = render_emoticons(_first_str(body if isinstance(body, dict) else {}, "headTitle"))
    text = clean_boss_tags(text) or ""
    return {
        "mid": mid,
        "text": text or "",
        "time": format_msg_time(msg.get("time") or msg.get("addTime")),
        "ts": message_ts(msg),
        "mine": mine,
        "fromUid": from_uid,
        "type": msg_type,
        "kind": kind,
        "image": image,
        "resume": resume,
        "file": file_info,
        "audio": audio,
    }


def live_message(
    *,
    uid: int,
    text: str,
    mine: bool,
    name: str = "",
    mid: Any = None,
    time_raw: Any = None,
    friend_id: int | None = None,
    from_uid: int = 0,
    avatar: str = "",
    kind: str = "text",
    image: dict[str, Any] | None = None,
    resume: dict[str, Any] | None = None,
    file: dict[str, Any] | None = None,
    audio: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        mid_val = int(mid) if mid is not None else None
    except (TypeError, ValueError):
        mid_val = mid
    return {
        "type": "message",
        "uid": int(uid or 0),
        "friendId": int(friend_id) if friend_id else int(uid or 0),
        "name": name,
        "avatar": avatar or "",
        "text": clean_boss_tags(render_emoticons(text or "")),
        "mine": bool(mine),
        "fromUid": int(from_uid or 0),
        "mid": mid_val,
        "time": format_msg_time(time_raw) or datetime.now().strftime("%H:%M"),
        "ts": message_ts({"time": time_raw}),
        "kind": kind or "text",
        "image": image,
        "resume": resume,
        "file": file,
        "audio": audio,
    }
