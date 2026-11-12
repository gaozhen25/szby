"""竞品监控 API schema。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.schemas.generation import WorkflowSchema


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
    profileUrl: str = Field(min_length=1, max_length=2048)


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
