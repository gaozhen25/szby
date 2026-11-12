from datetime import datetime

from pydantic import BaseModel, Field


class TopicSchema(BaseModel):
    id: str
    title: str
    source: str
    category: str
    type: str
    reason: str = ""
    platforms: list[str] = Field(default_factory=list)
    referenceNote: dict[str, object] = Field(default_factory=dict)
    batchId: str = ""


class FavoriteTopicSchema(TopicSchema):
    sourceTopicId: str
    sourceBatchId: str = ""
    collectedAt: datetime
