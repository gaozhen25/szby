from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.library import MAX_BATCH

_COUNT_ALIASES = {
    "like_count": ("liked_count", "likedCount", "digg_count", "zanCount", "zan_count", "likes", "点赞"),
    "collect_count": ("collected_count", "collectedCount", "favorite_count", "favorites", "收藏"),
    "share_count": ("shareCount", "分享"),
    "comment_count": ("commentCount", "评论"),
}
_TEXT_ALIASES = ("shareLink", "share_link", "share_url")


class ParseIn(BaseModel):
    text: str = Field(..., min_length=1)


class ReportItem(BaseModel):
    """One share link plus the numbers the caller already has."""

    model_config = ConfigDict(extra="allow")

    text: str = Field(..., min_length=1, max_length=20_000)
    like_count: Any = None
    collect_count: Any = None
    share_count: Any = None
    comment_count: Any = None

    @model_validator(mode="before")
    @classmethod
    def fold_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        folded = dict(data)
        if not folded.get("text"):
            for name in _TEXT_ALIASES:
                if folded.get(name):
                    folded["text"] = folded.pop(name)
                    break
        for name in _TEXT_ALIASES:
            folded.pop(name, None)
        for canonical, names in _COUNT_ALIASES.items():
            if folded.get(canonical) is None:
                for name in names:
                    if folded.get(name) is not None:
                        folded[canonical] = folded[name]
                        break
            for name in names:
                folded.pop(name, None)
        return folded


class BatchParseIn(BaseModel):
    text: str | None = Field(None, max_length=100_000)
    texts: list[str] = Field(default_factory=list, max_length=MAX_BATCH)
    items: list[ReportItem] = Field(default_factory=list, max_length=MAX_BATCH)
    download: bool = True
    refresh_files: bool = False


class LibraryPatch(BaseModel):
    note: str | None = Field(None, max_length=4000)
    labels: list[str] | None = Field(None, max_length=30)
    category: str | None = Field(None, max_length=40)
    industry: str | None = Field(None, max_length=40)


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=200)
