from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Topic:
    id: str
    title: str
    source: str
    category: str
    type: str
    reason: str = ""
    platforms: list[str] = field(default_factory=list)
    referenceNote: dict[str, object] = field(default_factory=dict)
    batchId: str = ""


@dataclass
class FavoriteTopic(Topic):
    sourceTopicId: str = ""
    sourceBatchId: str = ""
    collectedAt: datetime | None = None
