from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictBool, field_validator

from app.services.account_report.similar_accounts import with_configuration_metadata


class CreateAccountReportWorkflowRequest(BaseModel):
    referenceComments: StrictBool = False
    sectionKey: Literal[
        "similarAccounts",
        "complianceRules",
        "targetUserProfile",
        "hotContents",
    ] | None = None


class CreateAccountReportSectionWorkflowRequest(BaseModel):
    referenceComments: StrictBool = False


class ReportSchema(BaseModel):
    competitors: str
    prohibitedWords: str
    targetUsers: str
    hotContent: str
    topBloggers: str
    similarAccounts: list[dict[str, Any]] = Field(default_factory=list)
    complianceRules: list[dict[str, Any]] = Field(default_factory=list)
    targetUserProfile: dict[str, Any] = Field(default_factory=dict)
    hotContents: list[dict[str, Any]] = Field(default_factory=list)
    topBloggerDetails: list[dict[str, Any]] = Field(default_factory=list)
    contentStrategy: dict[str, Any] = Field(default_factory=dict)
    sourceMeta: dict[str, Any] = Field(default_factory=dict)
    reportVersion: int = 0
    generatedAt: datetime | None = None

    @field_validator("similarAccounts", mode="after")
    @classmethod
    def add_similar_account_configuration_metadata(
        cls, values: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [with_configuration_metadata(value) for value in values]


class UpdateReportSectionRequest(BaseModel):
    content: str


class AddSimilarAccountRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    platform: Literal["小红书", "抖音", "快手"]
    profileUrl: str = Field(min_length=1, max_length=500)
    similarityReason: str = Field(default="用户手动添加", min_length=1, max_length=500)
    avatarUrl: str = Field(default="", max_length=1000)
    description: str = Field(default="", max_length=1000)
    followers: int = Field(default=0, ge=0)
    follows: int = Field(default=0, ge=0)
    contentCount: int = Field(default=0, ge=0)
    totalLikes: int = Field(default=0, ge=0)
    ipLocation: str = Field(default="", max_length=100)

    @field_validator("name", "profileUrl", "similarityReason")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("avatarUrl", "description", "ipLocation")
    @classmethod
    def strip_optional_text(cls, value: str) -> str:
        return value.strip()


class ResolveSimilarAccountRequest(BaseModel):
    profileUrl: str = Field(min_length=1, max_length=1000)

    @field_validator("profileUrl")
    @classmethod
    def strip_profile_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("账号链接不能为空")
        return value


class ResolvedSimilarAccountSchema(BaseModel):
    name: str
    platform: Literal["小红书", "抖音", "快手"]
    profileUrl: str
    avatarUrl: str = ""
    description: str = ""
    followers: int = 0
    follows: int = 0
    contentCount: int = 0
    totalLikes: int = 0
    ipLocation: str = ""
