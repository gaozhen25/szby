"""创建竞品账号、视频和指标快照表。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_000021"
down_revision: str | None = "20260714_000020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _target_columns(url_name: str) -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column(url_name, sa.Text(), nullable=False),
    ]


def _refresh_columns() -> list[sa.Column]:
    return [
        sa.Column("delta_metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("refresh_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("refresh_error_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("refresh_error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "active_workflow_id",
            sa.String(36),
            sa.ForeignKey("workflows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "competitor_accounts",
        *_target_columns("profile_url"),
        sa.Column("name", sa.String(128), nullable=False, server_default=""),
        sa.Column("bio", sa.Text(), nullable=False, server_default=""),
        sa.Column("avatar_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("followers", sa.BigInteger(), nullable=True),
        sa.Column("following", sa.BigInteger(), nullable=True),
        sa.Column("works", sa.BigInteger(), nullable=True),
        sa.Column("liked", sa.BigInteger(), nullable=True),
        *_refresh_columns(),
        sa.UniqueConstraint(
            "account_id", "profile_url", name="uq_competitor_accounts_account_url"
        ),
    )
    op.create_index("ix_competitor_accounts_user_id", "competitor_accounts", ["user_id"])
    op.create_index("ix_competitor_accounts_account_id", "competitor_accounts", ["account_id"])
    op.create_index("ix_competitor_accounts_active_workflow_id", "competitor_accounts", ["active_workflow_id"])
    op.create_index(
        "ix_competitor_accounts_due",
        "competitor_accounts",
        ["next_refresh_at", "active_workflow_id"],
    )

    op.create_table(
        "competitor_videos",
        *_target_columns("content_url"),
        sa.Column("platform_content_id", sa.String(128), nullable=False, server_default=""),
        sa.Column(
            "competitor_account_id",
            sa.String(36),
            sa.ForeignKey("competitor_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("author_profile_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("likes", sa.BigInteger(), nullable=True),
        sa.Column("comments", sa.BigInteger(), nullable=True),
        sa.Column("shares", sa.BigInteger(), nullable=True),
        sa.Column("plays", sa.BigInteger(), nullable=True),
        sa.Column("collects", sa.BigInteger(), nullable=True),
        *_refresh_columns(),
        sa.UniqueConstraint(
            "account_id", "content_url", name="uq_competitor_videos_account_url"
        ),
    )
    op.create_index("ix_competitor_videos_user_id", "competitor_videos", ["user_id"])
    op.create_index("ix_competitor_videos_account_id", "competitor_videos", ["account_id"])
    op.create_index("ix_competitor_videos_competitor_account_id", "competitor_videos", ["competitor_account_id"])
    op.create_index("ix_competitor_videos_active_workflow_id", "competitor_videos", ["active_workflow_id"])
    op.create_index(
        "ix_competitor_videos_due",
        "competitor_videos",
        ["next_refresh_at", "active_workflow_id"],
    )

    op.create_table(
        "competitor_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column(
            "competitor_account_id",
            sa.String(36),
            sa.ForeignKey("competitor_accounts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "competitor_video_id",
            sa.String(36),
            sa.ForeignKey("competitor_videos.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "target_type",
            "target_id",
            "workflow_id",
            name="uq_competitor_snapshot_workflow",
        ),
        sa.CheckConstraint(
            "(target_type = 'account' AND competitor_account_id IS NOT NULL AND competitor_video_id IS NULL) "
            "OR (target_type = 'video' AND competitor_video_id IS NOT NULL AND competitor_account_id IS NULL)",
            name="ck_competitor_snapshot_owner",
        ),
    )
    op.create_index("ix_competitor_snapshots_target_id", "competitor_snapshots", ["target_id"])


def downgrade() -> None:
    op.drop_table("competitor_snapshots")
    op.drop_table("competitor_videos")
    op.drop_table("competitor_accounts")
