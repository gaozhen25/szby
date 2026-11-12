from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from .models import Actor, BootstrapState, Conversation, Message, SendResult


@dataclass(frozen=True, slots=True)
class PlatformCapabilities:
    text_receive: bool = True
    text_send: bool = True
    history_backfill: bool = True
    automatic_catch_up: bool = True
    image_receive: bool = False
    image_send: bool = False
    wechat_exchange: bool = False


class PlatformAdapter(ABC):
    """The only platform-specific surface visible to the runtime."""

    platform: str
    capabilities = PlatformCapabilities()

    @abstractmethod
    async def authenticate(self) -> Actor: ...

    async def validate_identity(self, actor: Actor) -> None:
        """Reject an authenticated UID that conflicts with persisted credentials."""

    async def persist_identity(self, actor: Actor) -> None:
        """Persist a validated UID after local state accepts it."""

    @abstractmethod
    async def bootstrap(self) -> BootstrapState: ...

    @abstractmethod
    def stream_messages(self) -> AsyncIterator[Message]: ...

    @abstractmethod
    async def catch_up(self, cursor: str) -> list[Message]: ...

    @abstractmethod
    async def resolve_conversation(self, platform_audience_id: str) -> Conversation | None:
        """Resolve a real platform conversation for a stable audience UID."""

    @abstractmethod
    async def send_text(self, conversation: Conversation, text: str) -> SendResult: ...

    @abstractmethod
    async def close(self) -> None: ...
