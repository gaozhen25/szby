"""BOSS-specific contact-exchange domain types and message parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Iterable

from .exceptions import ParamError


class ExchangeType(IntEnum):
    """Values used by BOSS's exchange endpoints."""

    PHONE = 1
    WECHAT = 2
    RESUME_REQUEST = 4


class ExchangeAcceptType(IntEnum):
    """Values used when accepting an incoming exchange request."""

    PHONE = 1
    WECHAT = 2
    RESUME = 3


@dataclass(frozen=True, slots=True)
class ExchangeContext:
    """Fresh candidate fields required by BOSS exchange APIs."""

    friend_id: int
    audience_id: int
    friend_source: int
    security_id: str
    audience_name: str = ""

    @property
    def unique_id(self) -> str:
        return f"{self.audience_id}-{self.friend_source}"


@dataclass(frozen=True, slots=True)
class PendingExchangeRequest:
    """An actionable exchange system message found in conversation history."""

    platform_message_id: str
    exchange_type: ExchangeAcceptType
    text: str
    sent_at_ms: int = 0


@dataclass(frozen=True, slots=True)
class ExchangeResult:
    """Successful execution of one BOSS exchange operation."""

    action: str
    exchange_type: str
    platform_message_id: str = ""
    data: dict[str, Any] = field(default_factory=dict, compare=False)


def exchange_context_from_friend(
    friend: dict[str, Any],
    *,
    fallback_friend_id: str = "",
    fallback_audience_id: str = "",
) -> ExchangeContext:
    """Validate a freshly loaded friend record for an exchange operation."""
    try:
        friend_id = int(friend.get("friendId") or fallback_friend_id or 0)
        audience_id = int(friend.get("uid") or fallback_audience_id or 0)
        friend_source = int(friend.get("friendSource") or 0)
    except (TypeError, ValueError) as exc:
        raise ParamError("BOSS 会话包含无效的交换标识") from exc
    security_id = str(friend.get("securityId") or "").strip()
    if not friend_id:
        raise ParamError("交换联系方式缺少 friendId")
    if not audience_id:
        raise ParamError("交换联系方式缺少候选人 uid")
    if not security_id:
        raise ParamError("交换联系方式缺少实时 securityId，请刷新会话后重试")
    return ExchangeContext(
        friend_id=friend_id,
        audience_id=audience_id,
        friend_source=friend_source,
        security_id=security_id,
        audience_name=str(friend.get("name") or friend.get("geekName") or ""),
    )


def find_pending_exchange_request(
    messages: Iterable[dict[str, Any]],
    *,
    audience_id: int,
    exchange_type: ExchangeAcceptType | None = None,
) -> PendingExchangeRequest | None:
    """Return the newest incoming, unambiguous exchange system request."""
    candidates: list[PendingExchangeRequest] = []
    for message in messages:
        sender = message.get("from") if isinstance(message.get("from"), dict) else {}
        try:
            sender_id = int(sender.get("uid") or message.get("fromUid") or 0)
        except (TypeError, ValueError):
            continue
        if sender_id != int(audience_id):
            continue
        text = str(message.get("pushText") or "").strip()
        if "请求与您交换" not in text:
            continue
        detected = _exchange_type_from_text(text)
        if detected is None or (exchange_type is not None and detected != exchange_type):
            continue
        platform_message_id = str(message.get("mid") or message.get("msgId") or "").strip()
        if not platform_message_id:
            continue
        candidates.append(
            PendingExchangeRequest(
                platform_message_id=platform_message_id,
                exchange_type=detected,
                text=text,
                sent_at_ms=_timestamp_ms(message.get("time") or message.get("addTime")),
            )
        )
    return max(candidates, key=lambda item: item.sent_at_ms) if candidates else None


def _exchange_type_from_text(text: str) -> ExchangeAcceptType | None:
    if "微信" in text:
        return ExchangeAcceptType.WECHAT
    if "手机号" in text or "联系方式" in text or "电话" in text:
        return ExchangeAcceptType.PHONE
    if "简历" in text:
        return ExchangeAcceptType.RESUME
    return None


def _timestamp_ms(value: Any) -> int:
    try:
        timestamp = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return timestamp if timestamp > 10_000_000_000 else timestamp * 1000
