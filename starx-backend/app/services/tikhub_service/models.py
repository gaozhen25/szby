from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class TikHubPlatform(str, Enum):
    DOUYIN = "douyin"
    XIAOHONGSHU = "xiaohongshu"
    KUAISHOU = "kuaishou"


class TikHubSearchRequest(BaseModel):
    platform: TikHubPlatform
    keyword: str = Field(min_length=1, max_length=200)
    offset: int = Field(default=0, ge=0)
    cursor: str = ""
    pageSize: int = Field(default=20, ge=1, le=100)
    sortType: str = "default"
    noteType: str = ""
    timeFilter: str = ""


class TikHubAccountDetailRequest(BaseModel):
    platform: TikHubPlatform
    accountId: str = ""
    userId: str = ""
    authorUrl: str = ""

    @model_validator(mode="after")
    def validate_identity(self) -> "TikHubAccountDetailRequest":
        if not any((self.accountId.strip(), self.userId.strip(), self.authorUrl.strip())):
            raise ValueError("accountId, userId or authorUrl is required")
        return self


class TikHubContentDetailRequest(BaseModel):
    platform: TikHubPlatform
    workId: str = ""
    workUrl: str = ""
    contentType: str = ""

    @model_validator(mode="after")
    def validate_identity(self) -> "TikHubContentDetailRequest":
        if not self.workId.strip() and not self.workUrl.strip():
            raise ValueError("workId or workUrl is required")
        return self


class TikHubAccountContentsRequest(BaseModel):
    platform: TikHubPlatform
    accountId: str = ""
    authorUrl: str = ""
    secUserId: str = ""
    offset: int = Field(default=0, ge=0)
    cursor: str = ""
    pageSize: int = Field(default=20, ge=1, le=100)
    sortType: str = "default"

    @model_validator(mode="after")
    def validate_identity(self) -> "TikHubAccountContentsRequest":
        if not any((self.accountId.strip(), self.authorUrl.strip(), self.secUserId.strip())):
            raise ValueError("accountId, authorUrl or secUserId is required")
        return self


class TikHubAiContentSearchRequest(BaseModel):
    platform: TikHubPlatform
    keyword: str = Field(min_length=1, max_length=200)
    pageNum: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)


class TikHubAccount(BaseModel):
    platform: TikHubPlatform
    accountId: str = ""
    userId: str = ""
    name: str = ""
    avatarUrl: str = ""
    description: str = ""
    profileUrl: str = ""
    followers: int = 0
    follows: int = 0
    contentCount: int = 0
    totalLikes: int = 0
    totalCollects: int = 0
    ipLocation: str = ""
    province: str = ""
    city: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class TikHubContent(BaseModel):
    platform: TikHubPlatform
    contentId: str = ""
    title: str = ""
    description: str = ""
    contentUrl: str = ""
    coverUrl: str = ""
    audioUrl: str = ""
    authorId: str = ""
    authorName: str = ""
    authorUrl: str = ""
    authorAvatarUrl: str = ""
    authorFollowers: int = 0
    authorContentCount: int = 0
    authorTotalLikes: int = 0
    publishedAt: str = ""
    duration: int = 0
    likeCount: int = 0
    commentCount: int = 0
    shareCount: int = 0
    collectCount: int = 0
    readCount: int = 0
    contentType: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class TikHubAccountPage(BaseModel):
    platform: TikHubPlatform
    total: int = 0
    hasMore: bool = False
    offset: int = 0
    nextCursor: str = ""
    accounts: list[TikHubAccount] = Field(default_factory=list)


class TikHubContentPage(BaseModel):
    platform: TikHubPlatform
    total: int = 0
    hasMore: bool = False
    offset: int = 0
    pageNum: int = 0
    pageSize: int = 0
    pages: int = 0
    nextCursor: str = ""
    contents: list[TikHubContent] = Field(default_factory=list)
