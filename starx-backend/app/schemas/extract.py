from typing import Any
from datetime import datetime

from pydantic import BaseModel, Field


class ExtractLinkRequest(BaseModel):
    text: str = Field(min_length=1)
    accountId: str | None = None
    creationId: str | None = None
    taskId: str | None = None


class ExtractProfileRequest(BaseModel):
    url: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class ExtractedProfileWorkSchema(BaseModel):
    id: str
    url: str
    title: str = ""
    cover: str = ""
    publishedAt: str = ""


class ExtractProfileResponse(BaseModel):
    platform: str
    url: str
    resolvedUrl: str
    name: str = ""
    accountId: str = ""
    avatar: str = ""
    description: str = ""
    following: int | None = None
    followers: int | None = None
    liked: int | None = None
    worksCount: int | None = None
    metricLabels: dict[str, str] = Field(default_factory=dict)
    works: list[ExtractedProfileWorkSchema] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class ExtractedMediaSchema(BaseModel):
    sourceUrl: str
    url: str
    contentType: str = ""
    kind: str
    storageStatus: str = "external"


class ExtractLinkResponse(BaseModel):
    historyId: str | None = None
    url: str
    resolvedUrl: str
    platform: str
    type: str
    title: str = ""
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    images: list[ExtractedMediaSchema] = Field(default_factory=list)
    videos: list[ExtractedMediaSchema] = Field(default_factory=list)
    cover: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ExtractHistorySchema(ExtractLinkResponse):
    id: str
    accountId: str | None = None
    creationId: str | None = None
    taskId: str | None = None
    persistenceStatus: str = "external"
    persistenceJobId: str | None = None
    persistenceError: str = ""
    persistedAt: datetime | None = None
    mediaUrlMap: dict[str, str] = Field(default_factory=dict)
    createdAt: datetime


class BindExtractHistoryRequest(BaseModel):
    historyIds: list[str] = Field(default_factory=list)
    creationId: str | None = None
    taskId: str | None = None


class VideoScriptWordSchema(BaseModel):
    beginMs: int = 0
    endMs: int = 0
    text: str = ""
    punctuation: str = ""


class VideoScriptLineSchema(BaseModel):
    timeRange: str = ""
    beginMs: int = 0
    endMs: int = 0
    text: str = ""
    emotion: str = "neutral"
    emotionLabel: str = "平静"
    language: str = ""
    words: list[VideoScriptWordSchema] = Field(default_factory=list)


class VideoShotBreakdownItemSchema(BaseModel):
    shot: int = 0
    image: str = ""
    timeRange: str = ""
    script: str = ""
    scriptRole: str = ""
    visualContent: str = ""
    visualRole: str = ""
    shotSizeCamera: str = ""
    shootingTechnique: str = ""
    bgmSound: str = ""
    moodPace: str = ""
    optimizationSuggestion: str = ""


class VideoRewriteReferenceSchema(BaseModel):
    title: str = ""
    rhythm: str = ""
    script: list[str] = Field(default_factory=list)


class VideoAnalysisResultSchema(BaseModel):
    sourceAudioUrl: str = ""
    audioTimeline: list[VideoScriptLineSchema] = Field(default_factory=list)
    videoScript: list[VideoScriptLineSchema] = Field(default_factory=list)
    shotBreakdown: list[VideoShotBreakdownItemSchema] = Field(default_factory=list)
    rewriteReferences: list[VideoRewriteReferenceSchema] = Field(default_factory=list)
    publishCopy: str = ""
    replicationPrompt: str = ""


class CreateVideoAnalysisWorkflowRequest(BaseModel):
    accountId: str | None = None
    creationId: str | None = None
    sourceUrl: str = ""
    videoUrl: str = ""
    coverUrl: str = ""
    platform: str = ""
    title: str = ""
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    images: list[ExtractedMediaSchema] = Field(default_factory=list)
    videos: list[ExtractedMediaSchema] = Field(default_factory=list)


class VideoAnalysisWorkflowSchema(BaseModel):
    id: str
    type: str = "video_analysis"
    accountId: str | None = None
    creationId: str | None = None
    status: str
    progress: int = 0
    currentStage: str = ""
    sourceUrl: str = ""
    videoUrl: str = ""
    coverUrl: str = ""
    platform: str = ""
    title: str = ""
    description: str = ""
    inputPayload: dict[str, Any] = Field(default_factory=dict)
    resultPayload: VideoAnalysisResultSchema = Field(default_factory=VideoAnalysisResultSchema)
    error: str = ""
    createdAt: datetime
    updatedAt: datetime
