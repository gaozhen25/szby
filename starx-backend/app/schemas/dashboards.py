from typing import Literal

from pydantic import BaseModel, Field


class DashboardMetricSchema(BaseModel):
    key: str
    label: str
    value: float | int | None = None
    change: float | None = None
    unit: str = ""
    available: bool = True
    note: str = ""


class DashboardTrendPointSchema(BaseModel):
    timestamp: str
    likes: int | None = None
    comments: int | None = None
    favorites: int | None = None
    shares: int | None = None


class DashboardContentStructureSchema(BaseModel):
    label: str
    count: int
    percentage: float


class DashboardTopContentSchema(BaseModel):
    rank: int
    contentId: str
    title: str
    contentType: str
    contentUrl: str = ""
    coverUrl: str = ""
    publishedAt: str | None = None
    likes: int | None = None
    comments: int | None = None
    favorites: int | None = None
    shares: int | None = None
    delta1h: int | None = None
    delta24h: int | None = None


class DashboardInsightSchema(BaseModel):
    title: str
    description: str


class SocialDashboardSchema(BaseModel):
    status: Literal["ready", "unconfigured", "unresolved", "unavailable"]
    platform: str = ""
    platformAccount: str = ""
    displayName: str = ""
    provider: str = ""
    days: int = 30
    updatedAt: str | None = None
    nextRefreshAt: str | None = None
    metrics: list[DashboardMetricSchema] = Field(default_factory=list)
    trend: list[DashboardTrendPointSchema] = Field(default_factory=list)
    contentStructure: list[DashboardContentStructureSchema] = Field(default_factory=list)
    topContents: list[DashboardTopContentSchema] = Field(default_factory=list)
    insights: list[DashboardInsightSchema] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)


class DashboardContentTrendSchema(BaseModel):
    contentId: str
    title: str = ""
    platform: str = ""
    provider: str = ""
    points: list[DashboardTrendPointSchema] = Field(default_factory=list)


class DashboardRefreshJobSchema(BaseModel):
    refreshId: str
    accountId: str
    platform: str
    provider: str = ""
    status: Literal["pending", "running", "succeeded", "failed"]
    stage: Literal["queued", "collecting", "persisting", "completed", "failed"]
    progress: int = 0
    itemCount: int = 0
    message: str = ""
    createdAt: str
    startedAt: str | None = None
    finishedAt: str | None = None


class DashboardSchema(BaseModel):
    views: str
    changeCount: int
    creation: int
    tools: int
    competitorCount: int
    competitorPosts: int
    materialCount: int
    availablePlatforms: list[str] = Field(default_factory=list)
    social: SocialDashboardSchema | None = None


class SummaryItemSchema(BaseModel):
    id: str
    name: str
    type: str
    dashboard: DashboardSchema
