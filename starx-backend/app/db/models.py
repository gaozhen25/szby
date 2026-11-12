from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.db.base import Base


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    accounts: Mapped[list["AccountRecord"]] = relationship(back_populates="user")
    knowledge_bases: Mapped[list["KnowledgeBaseRecord"]] = relationship(back_populates="user")
    workflows: Mapped[list["WorkflowRecord"]] = relationship(back_populates="user")
    digital_human_profiles: Mapped[list["DigitalHumanProfileRecord"]] = relationship(
        back_populates="user"
    )
    prompt_templates: Mapped[list["GenerationPromptTemplateRecord"]] = relationship(back_populates="user")
    prompt_tag_categories: Mapped[list["GenerationPromptTagCategoryRecord"]] = relationship(back_populates="user")
    prompt_tags: Mapped[list["GenerationPromptTagRecord"]] = relationship(back_populates="user")
    workflow_steps: Mapped[list["WorkflowStepRecord"]] = relationship(back_populates="user")
    extract_histories: Mapped[list["ExtractHistoryRecord"]] = relationship(back_populates="user")
    generation_jobs = synonym("workflows")
    job_sub_tasks = synonym("workflow_steps")
    video_analysis_jobs = synonym("workflows")


class AccountRecord(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    avatar: Mapped[str] = mapped_column(String(8), nullable=False)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="小红书")
    platforms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    account_links: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    platform_accounts: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    platform_account_identities: Mapped[dict[str, dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    publish_settings: Mapped[dict[str, dict[str, str]]] = mapped_column(JSON, nullable=False, default=dict)
    industry: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    product_service: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    target_city: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    target_audience: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    conversion_goal: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    knowledge_base_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    user: Mapped[UserRecord] = relationship(back_populates="accounts")
    knowledge_base: Mapped["KnowledgeBaseRecord | None"] = relationship(back_populates="bound_accounts")
    quotas: Mapped[list["AccountQuotaRecord"]] = relationship(back_populates="account")
    topics: Mapped[list["TopicRecord"]] = relationship(back_populates="account")
    favorite_topics: Mapped[list["FavoriteTopicRecord"]] = relationship(back_populates="account")
    dashboard: Mapped["DashboardRecord"] = relationship(back_populates="account")
    dashboard_account_snapshots: Mapped[list["DashboardAccountSnapshotRecord"]] = (
        relationship(back_populates="account", cascade="all, delete-orphan")
    )
    dashboard_content_snapshots: Mapped[list["DashboardContentSnapshotRecord"]] = (
        relationship(back_populates="account", cascade="all, delete-orphan")
    )
    own_social_contents: Mapped[list["OwnSocialContentRecord"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    own_dashboard_sync_states: Mapped[list["OwnDashboardSyncStateRecord"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    own_dashboard_refresh_jobs: Mapped[list["OwnDashboardRefreshJobRecord"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    report: Mapped["ReportRecord"] = relationship(back_populates="account")
    tasks: Mapped[list["TaskRecord"]] = relationship(back_populates="account")
    materials: Mapped[list["MaterialRecord"]] = relationship(back_populates="account")
    creations: Mapped[list["ContentCreationRecord"]] = relationship(back_populates="account")
    workflows: Mapped[list["WorkflowRecord"]] = relationship(back_populates="account")
    prompt_templates: Mapped[list["GenerationPromptTemplateRecord"]] = relationship(back_populates="account")
    prompt_tag_categories: Mapped[list["GenerationPromptTagCategoryRecord"]] = relationship(back_populates="account")
    prompt_tags: Mapped[list["GenerationPromptTagRecord"]] = relationship(back_populates="account")
    generation_assets: Mapped[list["GenerationAssetRecord"]] = relationship(back_populates="account")
    workflow_steps: Mapped[list["WorkflowStepRecord"]] = relationship(back_populates="account")
    digital_human_profiles: Mapped[list["DigitalHumanProfileRecord"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    generation_jobs = synonym("workflows")
    job_sub_tasks = synonym("workflow_steps")
    video_analysis_jobs = synonym("workflows")


class KnowledgeBaseRecord(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    product_name: Mapped[str] = mapped_column(String(128), nullable=False)
    industry: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    product_intro: Mapped[str] = mapped_column(Text, nullable=False, default="")
    brand_story: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    logo_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_materials: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    contact_info: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    website_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled_fields: Mapped[dict[str, bool]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    user: Mapped[UserRecord] = relationship(back_populates="knowledge_bases")
    bound_accounts: Mapped[list[AccountRecord]] = relationship(back_populates="knowledge_base")


class DirectUploadRecord(Base):
    __tablename__ = "direct_uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    object_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actual_content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    actual_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    etag: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    consumed_by_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    consumed_by_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class AccountQuotaRecord(Base):
    __tablename__ = "account_quotas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    quota_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    change_batch_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    change_batch_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    change_single_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    change_single_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_image_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    ai_image_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    account: Mapped[AccountRecord] = relationship(back_populates="quotas")


class TopicRecord(Base):
    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    platforms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reference_note: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    account: Mapped[AccountRecord] = relationship(back_populates="topics")


class FavoriteTopicRecord(Base):
    """A durable topic snapshot that survives recommendation batch replacement."""

    __tablename__ = "favorite_topics"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "source_topic_id",
            "source_batch_id",
            name="uq_favorite_topics_source_batch",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    source_topic_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_batch_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    platforms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reference_note: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    account: Mapped[AccountRecord] = relationship(back_populates="favorite_topics")


class DashboardRecord(Base):
    __tablename__ = "dashboards"

    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    views: Mapped[str] = mapped_column(String(32), nullable=False)
    change_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    creation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tools: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    competitor_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    competitor_posts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    material_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    account: Mapped[AccountRecord] = relationship(back_populates="dashboard")


class DashboardAccountSnapshotRecord(Base):
    __tablename__ = "dashboard_account_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "platform",
            "observed_date",
            name="uq_dashboard_account_snapshot_day",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    observed_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    followers: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    follows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    content_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_likes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    account: Mapped[AccountRecord] = relationship(
        back_populates="dashboard_account_snapshots"
    )


class DashboardContentSnapshotRecord(Base):
    __tablename__ = "dashboard_content_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "platform",
            "content_id",
            "observed_date",
            name="uq_dashboard_content_snapshot_day",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    content_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    observed_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    published_at: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    likes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    comments: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    favorites: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    account: Mapped[AccountRecord] = relationship(
        back_populates="dashboard_content_snapshots"
    )


class OwnSocialContentRecord(Base):
    __tablename__ = "own_social_contents"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "platform",
            "platform_content_id",
            name="uq_own_social_content_platform_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    platform_content_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    account: Mapped[AccountRecord] = relationship(back_populates="own_social_contents")
    metric_snapshots: Mapped[list["OwnContentMetricSnapshotRecord"]] = relationship(
        back_populates="content", cascade="all, delete-orphan"
    )


class OwnContentMetricSnapshotRecord(Base):
    __tablename__ = "own_content_metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "content_id",
            "captured_hour",
            name="uq_own_content_metric_snapshot_hour",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(
        ForeignKey("own_social_contents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    captured_hour: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    likes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comments: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    favorites: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    content: Mapped[OwnSocialContentRecord] = relationship(back_populates="metric_snapshots")


class OwnDashboardSyncStateRecord(Base):
    __tablename__ = "own_dashboard_sync_states"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "platform",
            name="uq_own_dashboard_sync_account_platform",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_refresh_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    account: Mapped[AccountRecord] = relationship(back_populates="own_dashboard_sync_states")


class OwnDashboardRefreshJobRecord(Base):
    """数据看板的轻量、可恢复异步刷新任务。"""

    __tablename__ = "own_dashboard_refresh_jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
    stage: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued"
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    account: Mapped[AccountRecord] = relationship(
        back_populates="own_dashboard_refresh_jobs"
    )


class ReportRecord(Base):
    __tablename__ = "reports"

    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    competitors: Mapped[str] = mapped_column(Text, nullable=False)
    prohibited_words: Mapped[str] = mapped_column(Text, nullable=False)
    target_users: Mapped[str] = mapped_column(Text, nullable=False)
    hot_content: Mapped[str] = mapped_column(Text, nullable=False)
    top_bloggers: Mapped[str] = mapped_column(Text, nullable=False)
    similar_accounts: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    manual_similar_accounts: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    excluded_similar_account_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    compliance_rules: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    target_user_profile: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    hot_contents: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    top_blogger_details: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    content_strategy: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    source_meta: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    report_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    account: Mapped[AccountRecord] = relationship(back_populates="report")


class ContentCreationRecord(Base):
    __tablename__ = "content_creations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    topic_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    topic_title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_platform: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    script_original: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    script_rewritten: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    hashtags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cover: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    bgm_suggestion: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sensitive_check: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    image_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    assets: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    creation_state: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    account: Mapped[AccountRecord] = relationship(back_populates="creations")
    user: Mapped[UserRecord] = relationship()
    workflow_tasks: Mapped[list["TaskRecord"]] = relationship(back_populates="creation")
    publish_attempts: Mapped[list["CreationPublishAttemptRecord"]] = relationship(
        back_populates="creation",
        cascade="all, delete-orphan",
    )


class CreationPublishAttemptRecord(Base):
    __tablename__ = "creation_publish_attempts"
    __table_args__ = (
        UniqueConstraint("creation_id", "attempt", name="uq_creation_publish_attempt_number"),
        UniqueConstraint("external_id", name="uq_creation_publish_attempt_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    creation_id: Mapped[str] = mapped_column(
        ForeignKey("content_creations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    history: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    creation: Mapped[ContentCreationRecord] = relationship(back_populates="publish_attempts")


class TaskRecord(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("creation_id", name="uq_tasks_creation_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    creation_id: Mapped[str | None] = mapped_column(ForeignKey("content_creations.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    updated: Mapped[str] = mapped_column(String(32), nullable=False)
    target_platform: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    assignee: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    due_date: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    handoff_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    account: Mapped[AccountRecord] = relationship(back_populates="tasks")
    creation: Mapped[ContentCreationRecord | None] = relationship(back_populates="workflow_tasks")


class MaterialRecord(Base):
    __tablename__ = "materials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    material_type: Mapped[str] = mapped_column(String(32), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    material_date: Mapped[str] = mapped_column(String(32), nullable=False)
    thumb: Mapped[str] = mapped_column(String(32), nullable=False)
    assets: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)

    account: Mapped[AccountRecord] = relationship(back_populates="materials")


class WorkflowRecord(Base):
    __tablename__ = "workflows"
    __table_args__ = (UniqueConstraint("id", "account_id", name="uq_workflows_id_account_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_stage: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    creation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    target_platform: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    topic_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    copy_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ratio: Mapped[str | None] = mapped_column(String(16), nullable=True)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    video_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    result_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    account: Mapped[AccountRecord | None] = relationship(back_populates="workflows")
    user: Mapped[UserRecord] = relationship(back_populates="workflows")
    assets: Mapped[list["GenerationAssetRecord"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="GenerationAssetRecord.workflow_id",
    )
    steps: Mapped[list["WorkflowStepRecord"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    external_task: Mapped["WorkflowExternalTaskRecord | None"] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        uselist=False,
    )

    job_type = synonym("type")

    @property
    def parent_job_id(self) -> None:
        return None


class GenerationAssetRecord(Base):
    __tablename__ = "generation_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "account_id"],
            ["workflows.id", "workflows.account_id"],
            name="fk_generation_assets_workflow_account",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    analysis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    workflow: Mapped[WorkflowRecord] = relationship(back_populates="assets", foreign_keys=[workflow_id])
    account: Mapped[AccountRecord] = relationship(back_populates="generation_assets")
    job_id = synonym("workflow_id")
    job = synonym("workflow")


class DigitalHumanProfileRecord(Base):
    __tablename__ = "digital_human_profiles"
    __table_args__ = (
        UniqueConstraint("id", "account_id", name="uq_digital_human_profile_account"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="validating", index=True)
    source_video_storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_video_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_audio_storage_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_audio_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover_storage_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    training_script_version: Mapped[str] = mapped_column(String(32), nullable=False)
    training_script_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    training_script_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_report: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    voice_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="dashscope")
    provider_voice_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    voice_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    voice_preview_storage_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    voice_preview_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enrollment_workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    error_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    consent_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    consent_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    user: Mapped[UserRecord] = relationship(back_populates="digital_human_profiles")
    account: Mapped[AccountRecord] = relationship(back_populates="digital_human_profiles")


class WorkflowExternalTaskRecord(Base):
    __tablename__ = "workflow_external_tasks"

    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider_task_id: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    provider_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    next_poll_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    poll_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_poll_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    consecutive_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sanitized_request: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    last_response: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    workflow: Mapped[WorkflowRecord] = relationship(back_populates="external_task")


class GenerationPromptTemplateRecord(Base):
    __tablename__ = "generation_prompt_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    selected_tag_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    negative_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    params: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    preview_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    account: Mapped[AccountRecord] = relationship(back_populates="prompt_templates")
    user: Mapped[UserRecord] = relationship(back_populates="prompt_templates")


class GenerationPromptTagCategoryRecord(Base):
    __tablename__ = "generation_prompt_tag_categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    account: Mapped[AccountRecord] = relationship(back_populates="prompt_tag_categories")
    user: Mapped[UserRecord] = relationship(back_populates="prompt_tag_categories")
    tags: Mapped[list["GenerationPromptTagRecord"]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class GenerationPromptTagRecord(Base):
    __tablename__ = "generation_prompt_tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    category_id: Mapped[str] = mapped_column(
        ForeignKey("generation_prompt_tag_categories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    category: Mapped[GenerationPromptTagCategoryRecord] = relationship(back_populates="tags")
    account: Mapped[AccountRecord] = relationship(back_populates="prompt_tags")
    user: Mapped[UserRecord] = relationship(back_populates="prompt_tags")


class WorkflowStepRecord(Base):
    __tablename__ = "workflow_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), nullable=True, index=True)
    asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    group_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    input_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    result_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    workflow: Mapped[WorkflowRecord] = relationship(back_populates="steps")
    user: Mapped[UserRecord] = relationship(back_populates="workflow_steps")
    account: Mapped[AccountRecord | None] = relationship(back_populates="workflow_steps")

    parent_job_id = synonym("workflow_id")
    parent_job_type = synonym("type")
    sub_type = synonym("type")


class ExtractHistoryRecord(Base):
    __tablename__ = "extract_histories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    account_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    creation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_url: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hashtags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    images: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    videos: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    cover: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    persistence_status: Mapped[str] = mapped_column(String(16), nullable=False, default="external")
    persistence_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    persistence_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    persisted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    media_url_map: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)

    user: Mapped[UserRecord] = relationship(back_populates="extract_histories")


class CompetitorAccountRecord(Base):
    __tablename__ = "competitor_accounts"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "profile_url", name="uq_competitor_accounts_account_url"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    profile_url: Mapped[str] = mapped_column(Text, nullable=False)
    sec_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    bio: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    followers: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    following: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    works: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    liked: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    latest_videos: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    new_videos: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    video_snapshot_ready: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    delta_metrics: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    refresh_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )
    refresh_error_code: Mapped[str] = mapped_column(
        String(64), nullable=False, default=""
    )
    refresh_error_message: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )
    active_workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_refresh_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    account: Mapped[AccountRecord] = relationship(foreign_keys=[account_id])
    user: Mapped[UserRecord] = relationship(foreign_keys=[user_id])
    snapshots: Mapped[list["CompetitorSnapshotRecord"]] = relationship(
        back_populates="competitor_account",
        cascade="all, delete-orphan",
        foreign_keys="CompetitorSnapshotRecord.competitor_account_id",
    )


class CompetitorVideoRecord(Base):
    __tablename__ = "competitor_videos"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "content_url", name="uq_competitor_videos_account_url"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    content_url: Mapped[str] = mapped_column(Text, nullable=False)
    platform_content_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default=""
    )
    competitor_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("competitor_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    author_profile_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    likes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comments: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    plays: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    collects: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delta_metrics: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    refresh_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending"
    )
    refresh_error_code: Mapped[str] = mapped_column(
        String(64), nullable=False, default=""
    )
    refresh_error_message: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )
    active_workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_refresh_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    account: Mapped[AccountRecord] = relationship(foreign_keys=[account_id])
    user: Mapped[UserRecord] = relationship(foreign_keys=[user_id])
    competitor_account: Mapped[CompetitorAccountRecord | None] = relationship(
        foreign_keys=[competitor_account_id]
    )
    snapshots: Mapped[list["CompetitorSnapshotRecord"]] = relationship(
        back_populates="competitor_video",
        cascade="all, delete-orphan",
        foreign_keys="CompetitorSnapshotRecord.competitor_video_id",
    )


class CompetitorSnapshotRecord(Base):
    __tablename__ = "competitor_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "target_type",
            "target_id",
            "workflow_id",
            name="uq_competitor_snapshot_workflow",
        ),
        CheckConstraint(
            "(target_type = 'account' AND competitor_account_id IS NOT NULL "
            "AND competitor_video_id IS NULL) OR "
            "(target_type = 'video' AND competitor_video_id IS NOT NULL "
            "AND competitor_account_id IS NULL)",
            name="ck_competitor_snapshot_owner",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    competitor_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("competitor_accounts.id", ondelete="CASCADE"), nullable=True
    )
    competitor_video_id: Mapped[str | None] = mapped_column(
        ForeignKey("competitor_videos.id", ondelete="CASCADE"), nullable=True
    )
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False)
    metrics: Mapped[dict[str, int | None]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    items: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    competitor_account: Mapped[CompetitorAccountRecord | None] = relationship(
        back_populates="snapshots", foreign_keys=[competitor_account_id]
    )
    competitor_video: Mapped[CompetitorVideoRecord | None] = relationship(
        back_populates="snapshots", foreign_keys=[competitor_video_id]
    )
