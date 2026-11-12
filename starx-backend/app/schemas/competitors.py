"""竞品监控 API schema。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.schemas.generation import WorkflowSchema
from app.schemas.social_accounts import PlatformName


class CompetitorSchema(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )

    id: str
    account_id: str
    platform: str
    delta_metrics: dict[str, int] = Field(default_factory=dict)
    refresh_status: str
    refresh_error_code: str = ""
    refresh_error_message: str = ""
    active_workflow_id: str | None = None
    last_attempted_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    next_refresh_at: datetime
    created_at: datetime
    updated_at: datetime


class CompetitorAccountSchema(CompetitorSchema):
    profile_url: str
    sec_user_id: str = ""
    name: str = ""
    bio: str = ""
    avatar_url: str = ""
    followers: int | None = None
    following: int | None = None
    works: int | None = None
    liked: int | None = None
    latest_videos: list[dict] = Field(default_factory=list)
    new_videos: list[dict] = Field(default_factory=list)


class CompetitorVideoSchema(CompetitorSchema):
    content_url: str
    platform_content_id: str = ""
    competitor_account_id: str | None = None
    title: str = ""
    description: str = ""
    cover_url: str = ""
    author_name: str = ""
    author_profile_url: str = ""
    published_at: datetime | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    plays: int | None = None
    collects: int | None = None


class AddCompetitorAccountRequest(BaseModel):
    """竞品账号引用；兼容旧字段，并支持由后端判断统一输入的类型。"""

    platform: PlatformName | None = None
    reference: str = Field(default="", max_length=2048)
    accountId: str = Field(default="", max_length=255)
    profileUrl: str = Field(default="", max_length=2048)

    @model_validator(mode="after")
    def validate_reference(self) -> "AddCompetitorAccountRequest":
        self.reference = self.reference.strip()
        self.accountId = self.accountId.strip()
        self.profileUrl = self.profileUrl.strip()
        supplied = sum(bool(value) for value in (
            self.reference,
            self.accountId,
            self.profileUrl,
        ))
        if supplied != 1:
            raise ValueError("reference、accountId 和 profileUrl 必须且只能提供一个")
        if (self.reference or self.accountId) and self.platform is None:
            raise ValueError("使用统一账号输入或 accountId 时必须提供 platform")
        return self


class AddCompetitorVideoRequest(BaseModel):
    contentUrl: str = Field(min_length=1, max_length=2048)


class CreateCompetitorAccountResponse(BaseModel):
    target: CompetitorAccountSchema
    workflow: WorkflowSchema


class CreateCompetitorVideoResponse(BaseModel):
    target: CompetitorVideoSchema
    workflow: WorkflowSchema


class CompetitorBatchRefreshResponse(BaseModel):
    workflows: list[WorkflowSchema] = Field(default_factory=list)


class CompetitorContentTrendPoint(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    captured_at: datetime
    metrics: dict[str, int | None] = Field(default_factory=dict)


class CompetitorContentTrend(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    platform_content_id: str = ""
    title: str = ""
    content_url: str = ""
    published_at: datetime | None = None
    points: list[CompetitorContentTrendPoint] = Field(default_factory=list)


class CompetitorAccountTrendPoint(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    captured_at: datetime
    metrics: dict[str, int | None] = Field(default_factory=dict)
