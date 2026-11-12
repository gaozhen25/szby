"""竞品监控内部稳定数据类型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TargetType = Literal["account", "video"]


class NormalizedCompetitorVideo(BaseModel):
    model_config = ConfigDict(frozen=True)

    platform_content_id: str = ""
    title: str = ""
    description: str = ""
    content_url: str = ""
    cover_url: str = ""
    published_at: datetime | None = None
    metrics: dict[str, int | None] = Field(default_factory=dict)


class NormalizedCompetitor(BaseModel):
    model_config = ConfigDict(frozen=True)

    platform: Literal["xhs", "dy", "ks"]
    platform_content_id: str = ""
    name: str = ""
    title: str = ""
    description: str = ""
    profile_url: str = ""
    avatar_url: str = ""
    content_url: str = ""
    cover_url: str = ""
    author_name: str = ""
    author_profile_url: str = ""
    published_at: datetime | None = None
    metrics: dict[str, int | None] = Field(default_factory=dict)
    videos: list[NormalizedCompetitorVideo] = Field(default_factory=list)
