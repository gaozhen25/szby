"""Shared lookup for current and durably favorited topic snapshots."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import FavoriteTopicRecord, TopicRecord


def find_topic_snapshot(
    session: Session,
    *,
    account_id: str,
    topic_id: str,
    content_type: str | None = None,
) -> TopicRecord | FavoriteTopicRecord | None:
    conditions = [TopicRecord.id == f"{account_id}_{topic_id}", TopicRecord.account_id == account_id]
    if content_type:
        conditions.append(TopicRecord.content_type == content_type)
    current = session.scalar(select(TopicRecord).where(*conditions))
    if current is not None:
        return current

    favorite_conditions = [FavoriteTopicRecord.id == topic_id, FavoriteTopicRecord.account_id == account_id]
    if content_type:
        favorite_conditions.append(FavoriteTopicRecord.content_type == content_type)
    return session.scalar(select(FavoriteTopicRecord).where(*favorite_conditions))
