"""爬虫公开进度文本的统一 fail-closed 净化策略。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from .vendor.user_hash import mask_nickname


SENSITIVE_TEXT = "[敏感信息已移除]"
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}"
)
_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LANDLINE_PATTERN = re.compile(
    r"(?<!\d)(?:\(0\d{2,3}\)[- ]?\d{7,8}|0\d{2,3}[- ]?\d{7,8}|"
    r"(?:400|800)[- ]?\d{3}[- ]?\d{4})(?!\d)"
)
_CONTACT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:qq\s*(?:号码|号)?|wechat|weixin|vx|wx)"
    r"\s*(?:(?:是|为)|[:：=])?\s*[A-Za-z0-9_-]{4,}\b|"
    r"微信\s*(?:号)?\s*(?:(?:是|为)|[:：=])?\s*[A-Za-z0-9_-]{4,}",
    re.IGNORECASE,
)
_CREDENTIAL_PATTERN = re.compile(
    r'''(?ix)
    (?:
        (?<![A-Za-z0-9_])
        ["']?
        (?:
            set-cookie|cookies?|authorization|proxy-authorization|
            bearer|access[_-]?token|refresh[_-]?token|id[_-]?token|
            tokens?|sessions?(?:id)?|csrf(?:token)?|csrf[_-]?token|
            xsrf(?:token)?|xsrf[_-]?token|client[_-]?secret|secret(?:[_-]?key)?
        )
        ["']?\s*[:=]
        |
        \bbearer\s+[A-Za-z0-9._~+/=-]+
    )
    ''',
)
_REQUEST_HEADER_PATTERN = re.compile(
    r'''(?ix)
    (?<![A-Za-z0-9_])
    ["']?
    (?:
        (?:request[_-]?)?headers?|x[_-][A-Za-z0-9_-]+|
        sec[_-][A-Za-z0-9_-]+|api[_-]?key|referer|referrer|
        user[_-]?agent|set[_-]?cookie|cookies?|authorization|
        proxy[_-]?authorization|host|origin|forwarded|via|range|pragma|connection|
        cache-control|accept(?:-[A-Za-z0-9_-]+)?|content[_-]?(?:type|length)|
        upgrade-insecure-requests|dnt
    )
    ["']?\s*[:=]
    ''',
)
_RAW_ID_LABEL_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:user[_-]?id|uid|sec[_-]?(?:user[_-]?)?id|"
    r"author[_-]?id|creator[_-]?id)\s*[:=]"
)
_RAW_ID_VALUE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._~-])[A-Za-z0-9._~-]{16,}(?![A-Za-z0-9._~-])"
)
_PLATFORM_NAMES = {"xhs": "小红书", "dy": "抖音", "ks": "快手"}
_ACTION_MESSAGES = {
    "waiting_for_slot": "等待运行槽位",
    "run_started": "开始平台采集",
    "keyword_started": "开始关键词采集",
    "keyword_completed": "关键词采集完成",
    "keyword_failed": "关键词采集失败，继续处理其他关键词",
    "creator_started": "开始博主主页采集",
    "content_discovered": "发现公开内容",
    "creator_discovered": "发现公开博主",
    "comments_updated": "更新评论计数",
    "run_completed": "平台采集完成",
    "run_failed": "平台采集失败",
}


def contains_unsafe_public_text(value: Any) -> bool:
    text = str(value or "")
    return bool(
        _CREDENTIAL_PATTERN.search(text)
        or _REQUEST_HEADER_PATTERN.search(text)
        or _RAW_ID_LABEL_PATTERN.search(text)
        or _RAW_ID_VALUE_PATTERN.search(text)
    )


def sanitize_public_text(value: Any, *, limit: int) -> str:
    text = str(value or "")
    if contains_unsafe_public_text(text):
        return SENSITIVE_TEXT[:limit]
    text = _URL_PATTERN.sub("[链接已移除]", text)
    text = _EMAIL_PATTERN.sub("[邮箱已脱敏]", text)
    text = _PHONE_PATTERN.sub("[手机号已脱敏]", text)
    text = _LANDLINE_PATTERN.sub("[座机已脱敏]", text)
    text = _CONTACT_PATTERN.sub("[联系方式已脱敏]", text)
    return " ".join(text.split())[:limit]


def sanitize_nickname_subject(value: Any, *, limit: int = 100) -> str:
    text = str(value or "").strip()
    if not text or contains_unsafe_public_text(text):
        return ""
    if any(
        pattern.search(text)
        for pattern in (
            _URL_PATTERN,
            _EMAIL_PATTERN,
            _PHONE_PATTERN,
            _LANDLINE_PATTERN,
            _CONTACT_PATTERN,
        )
    ):
        return ""
    return mask_nickname(" ".join(text.split()))[:limit]


def public_action_message(action: str) -> str:
    return _ACTION_MESSAGES.get(str(action), "更新采集进度")


def safe_keyword_subject(keywords: Sequence[str], *, limit: int = 100) -> str:
    safe_keywords: list[str] = []
    for value in keywords:
        text = sanitize_public_text(value, limit=30)
        if not text or text == SENSITIVE_TEXT or "已脱敏" in text or "已移除" in text:
            continue
        safe_keywords.append(text)
        if len(safe_keywords) == 3:
            break
    return ("、".join(safe_keywords) or "已配置检索词")[:limit]


def safe_creator_subject(platform: str, platform_name: str = "") -> str:
    name = sanitize_public_text(
        platform_name or _PLATFORM_NAMES.get(str(platform), ""), limit=20
    )
    if not name or name == SENSITIVE_TEXT:
        return "已配置账号主页"
    return f"{name}账号主页"


def sanitize_event_subject(
    action: str,
    subject: Any,
    *,
    platform: str,
    platform_name: str = "",
) -> str:
    if action == "creator_started":
        return safe_creator_subject(platform, platform_name)
    if action in {"keyword_started", "keyword_completed", "keyword_failed"}:
        text = sanitize_public_text(subject, limit=100)
        return "" if text == SENSITIVE_TEXT else text
    if action == "creator_discovered":
        return sanitize_nickname_subject(subject)
    text = sanitize_public_text(subject, limit=100)
    return "" if text == SENSITIVE_TEXT else text
