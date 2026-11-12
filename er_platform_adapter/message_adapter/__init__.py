"""Platform-neutral edge adapter connected directly to RabbitMQ."""

from .core.models import Actor, Audience, Conversation, Message, SendRequest, SendResult

__all__ = ["Actor", "Audience", "Conversation", "Message", "SendRequest", "SendResult"]
__version__ = "0.1.0"
