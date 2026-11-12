from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AccountQuota:
    changeBatch: int
    changeSingle: int
    aiImage: int


@dataclass
class Account:
    id: str
    name: str
    type: str
    platform: str
    platforms: list[str]
    avatar: str
    description: str
    purpose: str
    quota: AccountQuota
    accountLinks: dict[str, str] = field(default_factory=dict)
    publishSettings: dict[str, dict[str, str]] = field(default_factory=dict)
    industry: str = ""
    productService: str = ""
    targetCity: str = ""
    targetAudience: str = ""
    conversionGoal: str = ""
    knowledgeBaseId: str | None = None
    knowledgeBaseSummary: "KnowledgeBaseSummary | None" = None


@dataclass
class KnowledgeBaseSummary:
    id: str
    name: str
    productName: str


@dataclass
class KnowledgeBase:
    id: str
    name: str
    productName: str
    industry: str
    productIntro: str
    brandStory: str
    price: str
    logoUrl: str
    imageMaterials: list[str]
    contactInfo: str
    websiteUrl: str
    enabledFields: dict[str, bool]
    createdAt: str
    updatedAt: str


@dataclass
class Dashboard:
    views: str
    changeCount: int
    creation: int
    tools: int
    competitorCount: int
    competitorPosts: int
    materialCount: int


@dataclass
class Report:
    competitors: str
    prohibitedWords: str
    targetUsers: str
    hotContent: str
    topBloggers: str
    similarAccounts: list[dict[str, Any]] = field(default_factory=list)
    complianceRules: list[dict[str, Any]] = field(default_factory=list)
    targetUserProfile: dict[str, Any] = field(default_factory=dict)
    hotContents: list[dict[str, Any]] = field(default_factory=list)
    topBloggerDetails: list[dict[str, Any]] = field(default_factory=list)
    contentStrategy: dict[str, Any] = field(default_factory=dict)
    sourceMeta: dict[str, Any] = field(default_factory=dict)
    reportVersion: int = 0
    generatedAt: datetime | None = None
