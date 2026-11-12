"""账号报告采集进度的快照模型与平台累计状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.mediaspider.models import CrawlerFailure
from app.services.mediaspider.progress_safety import sanitize_public_text


ActivityStatus = Literal["pending", "running", "completed", "failed", "skipped"]
SummaryStatus = Literal[
    "pending", "running", "completed", "partial", "failed", "skipped"
]


@dataclass(frozen=True)
class CrawlTarget:
    platform_name: str
    platform_code: str


@dataclass
class PlatformState:
    target: CrawlTarget
    observed_content_count: int = 0
    observed_creator_count: int = 0
    observed_comment_count: int = 0
    current_content_count: int = 0
    current_creator_count: int = 0
    current_comment_count: int = 0
    successful_runs: int = 0
    failures: dict[str, CrawlerFailure] = field(default_factory=dict)
    notices: dict[str, CrawlerFailure] = field(default_factory=dict)
    active: bool = False

    @property
    def status(self) -> SummaryStatus:
        if self.active:
            return "running"
        if self.failures and self.successful_runs:
            return "partial"
        if self.failures:
            if all(item.code == "credentials_missing" for item in self.failures.values()):
                return "skipped"
            return "failed"
        if self.successful_runs:
            return "completed"
        return "pending"

    @property
    def latest_failure(self) -> CrawlerFailure | None:
        return next(reversed(self.failures.values()), None)

    @property
    def latest_notice(self) -> CrawlerFailure | None:
        return next(reversed(self.notices.values()), None)

    def settle_current_counts(
        self,
        *,
        content_count: int = 0,
        creator_count: int = 0,
        comment_count: int = 0,
    ) -> None:
        self.observed_content_count += max(
            self.current_content_count, max(0, int(content_count))
        )
        self.observed_creator_count += max(
            self.current_creator_count, max(0, int(creator_count))
        )
        self.observed_comment_count += max(
            self.current_comment_count, max(0, int(comment_count))
        )
        self.current_content_count = 0
        self.current_creator_count = 0
        self.current_comment_count = 0


class CrawlActivity(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sequence: int
    stage: str
    status: ActivityStatus
    platform: str
    platform_name: str = Field(alias="platformName")
    action: str
    message: str
    subject: str = ""
    content_title: str = Field(default="", alias="contentTitle")
    content_count: int = Field(default=0, alias="contentCount")
    creator_count: int = Field(default=0, alias="creatorCount")
    comment_count: int = Field(default=0, alias="commentCount")
    occurred_at: str = Field(alias="occurredAt")


class PlatformCrawlSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    platform: str
    platform_name: str = Field(alias="platformName")
    status: SummaryStatus
    content_count: int = Field(default=0, alias="contentCount")
    creator_count: int = Field(default=0, alias="creatorCount")
    comment_count: int = Field(default=0, alias="commentCount")
    failure_code: str | None = Field(default=None, alias="failureCode")
    failure_message: str | None = Field(default=None, alias="failureMessage")
    failure_suggestion: str | None = Field(default=None, alias="failureSuggestion")
    notice_code: str | None = Field(default=None, alias="noticeCode")
    notice_message: str | None = Field(default=None, alias="noticeMessage")
    notice_suggestion: str | None = Field(default=None, alias="noticeSuggestion")


class CrawlProgressSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current: CrawlActivity | None = None
    activities: list[CrawlActivity] = Field(default_factory=list, max_length=30)
    platform_summaries: list[PlatformCrawlSummary] = Field(
        default_factory=list, alias="platformSummaries"
    )


def platform_summary(state: PlatformState) -> PlatformCrawlSummary:
    failure = state.latest_failure
    notice = state.latest_notice
    return PlatformCrawlSummary(
        platform=sanitize_public_text(state.target.platform_code, limit=20),
        platformName=sanitize_public_text(state.target.platform_name, limit=20),
        status=state.status,
        contentCount=state.observed_content_count + state.current_content_count,
        creatorCount=state.observed_creator_count + state.current_creator_count,
        commentCount=state.observed_comment_count + state.current_comment_count,
        failureCode=failure.code if failure else None,
        failureMessage=(
            sanitize_public_text(failure.message, limit=120) if failure else None
        ),
        failureSuggestion=(
            sanitize_public_text(failure.suggestion, limit=160) if failure else None
        ),
        noticeCode=notice.code if notice else None,
        noticeMessage=(
            sanitize_public_text(notice.message, limit=120) if notice else None
        ),
        noticeSuggestion=(
            sanitize_public_text(notice.suggestion, limit=160) if notice else None
        ),
    )


def snapshot_dict(
    activities: list[CrawlActivity], states: dict[str, PlatformState]
) -> dict[str, Any]:
    snapshot = CrawlProgressSnapshot(
        current=activities[-1] if activities else None,
        activities=activities,
        platformSummaries=[platform_summary(state) for state in states.values()],
    )
    return snapshot.model_dump(mode="json", by_alias=True)
