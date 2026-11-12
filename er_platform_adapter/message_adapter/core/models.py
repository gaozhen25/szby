from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


_EVENT_NAMESPACE = uuid.UUID("0bfb8662-e12c-4b1a-9ca8-1c6210680f11")
_REQUEST_NAMESPACE = uuid.UUID("dedfbad7-18a5-42a4-b9c8-c83e23a52bcf")
_STATUS_NAMESPACE = uuid.UUID("1dc4d322-9c77-4b9e-9c02-3b88e6785f04")


def _required(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _stable_uuid(namespace: uuid.UUID, *parts: str) -> str:
    return str(uuid.uuid5(namespace, "\x1f".join(str(part) for part in parts)))


@dataclass(frozen=True, slots=True)
class Actor:
    platform: str
    platform_actor_id: str
    username: str = ""
    avatar: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "platform", _required(self.platform, "platform"))
        object.__setattr__(self, "platform_actor_id", _required(self.platform_actor_id, "actor.platform_actor_id"))


@dataclass(frozen=True, slots=True)
class Audience:
    platform_audience_id: str
    username: str = ""
    avatar: str = ""
    remark: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "platform_audience_id",
            _required(self.platform_audience_id, "audience.platform_audience_id"),
        )


@dataclass(frozen=True, slots=True)
class Conversation:
    platform: str
    platform_actor_id: str
    audience: Audience
    platform_conversation_id: str
    platform_data: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "platform", _required(self.platform, "platform"))
        object.__setattr__(
            self,
            "platform_actor_id",
            _required(self.platform_actor_id, "conversation.platform_actor_id"),
        )
        object.__setattr__(
            self,
            "platform_conversation_id",
            _required(self.platform_conversation_id, "platform_conversation_id"),
        )


@dataclass(frozen=True, slots=True)
class Message:
    platform: str
    message_id: str
    conversation: Conversation
    text: str
    sent_at_ms: int
    is_send: bool = False
    platform_message_id: str = ""
    content_type: int = 101
    content: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "platform", _required(self.platform, "platform"))
        object.__setattr__(self, "message_id", _required(self.message_id, "message_id"))
        object.__setattr__(self, "sent_at_ms", int(self.sent_at_ms or time.time() * 1000))

    @property
    def event_id(self) -> str:
        return _stable_uuid(
            _EVENT_NAMESPACE,
            self.platform,
            self.conversation.platform_actor_id,
            self.conversation.platform_conversation_id,
            self.message_id,
        )

    @property
    def request_id(self) -> str:
        return _stable_uuid(_REQUEST_NAMESPACE, self.event_id)

    def mq_payload(self, actor: Actor, *, created_at_ms: int | None = None) -> dict[str, Any]:
        if actor.platform != self.platform or actor.platform_actor_id != self.conversation.platform_actor_id:
            raise ValueError("message Actor does not match authenticated Adapter Actor")
        return {
            "id": self.event_id,
            "func": "push_message_v2",
            "timestamp": int(created_at_ms or time.time() * 1000),
            "platform": self.platform,
            "is_task_message": not self.is_send,
            "data": {
                "actorPlatformID": actor.platform_actor_id,
                "audiencePlatformID": self.conversation.audience.platform_audience_id,
                "platform": self.platform,
                "requestID": self.request_id,
                "audienceNickname": self.conversation.audience.username,
                "audienceFaceURL": self.conversation.audience.avatar,
                "sendTime": self.sent_at_ms,
                "actorNickname": actor.username,
                "actorFaceURL": actor.avatar,
                "contentType": int(self.content_type or 101),
                "content": self.content if self.content is not None else {"text": self.text},
                "ex": "{}",
                "direction": 1 if self.is_send else 0,
            },
        }

    def echo_fingerprint(self) -> str:
        # Prefer audience + text over conversation_id: Douyin may rewrite the
        # conversation id after create/send, which would miss echo suppression
        # and republish the same outbound as a「人工」bubble in IM.
        material = json.dumps(
            [
                self.platform,
                self.conversation.platform_actor_id,
                self.conversation.audience.platform_audience_id,
                self.text,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SendRequest:
    platform: str
    platform_actor_id: str
    platform_audience_id: str
    client_msg_id: str
    content_type: int
    content: str

    @classmethod
    def from_mq_payload(cls, payload: dict[str, Any]) -> "SendRequest":
        if not isinstance(payload, dict):
            raise TypeError("MQ body must be a JSON object")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("data must be a JSON object")
        encoded = data.get("content")
        if not isinstance(encoded, str):
            raise ValueError("data.content must be a JSON string")
        try:
            decoded = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise ValueError("data.content is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError("decoded data.content must be a JSON object")
        content_type = int(data.get("content_type") or data.get("contentType") or 0)
        text = str(decoded.get("content") or "") if content_type == 101 else ""
        return cls(
            platform=_required(str(payload.get("platform") or ""), "platform"),
            platform_actor_id=_required(str(payload.get("platform_actor_id") or ""), "platform_actor_id"),
            platform_audience_id=_required(str(payload.get("platform_audience_id") or ""), "platform_audience_id"),
            client_msg_id=_required(downlink_client_msg_id(payload, data), "clientMsgID"),
            content_type=content_type,
            content=text,
        )


def downlink_client_msg_id(payload: dict[str, Any], data: dict[str, Any] | None = None) -> str:
    """轻回下发带回的 clientMsgID。兼容旧字段 client_msg_id。"""
    sources = [data, payload] if isinstance(data, dict) else [payload]
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("clientMsgID", "client_msg_id"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def send_status_payload(
    *,
    platform: str,
    client_msg_id: str,
    status: int,
    actual_send_time: int,
) -> dict[str, Any]:
    """发送结果上报。status 0 成功，1 失败。"""
    del platform
    return {
        "clientMsgID": client_msg_id,
        "status": int(status),
        "actualSendTime": int(actual_send_time),
    }


def status_event_id(status_event: dict[str, Any]) -> str:
    explicit = str(status_event.get("id") or "").strip()
    if explicit:
        return explicit
    client_msg_id = str(status_event.get("clientMsgID") or status_event.get("client_msg_id") or "")
    return _stable_uuid(_STATUS_NAMESPACE, client_msg_id, str(status_event.get("status")))


@dataclass(frozen=True, slots=True)
class SendResult:
    success: bool
    sent_at_ms: int
    platform_message_id: str = ""
    error: str = ""
    retryable: bool = False
    conversation_id: str = ""
    conversation_short_id: int = 0
    conversation_ticket: str = ""


@dataclass(frozen=True, slots=True)
class BootstrapState:
    cursor: str
    conversations: tuple[Conversation, ...] = ()
    baseline_message_ids: frozenset[str] = frozenset()
