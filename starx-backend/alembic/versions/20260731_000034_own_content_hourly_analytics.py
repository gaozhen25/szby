"""增加自有作品小时级互动快照。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_000034"
down_revision: str | None = "20260731_000033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "own_social_contents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("platform_content_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_type", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "platform", "platform_content_id",
            name="uq_own_social_content_platform_id",
        ),
    )
    for column in ("account_id", "platform", "platform_content_id"):
        op.create_index(op.f(f"ix_own_social_contents_{column}"), "own_social_contents", [column])

    op.create_table(
        "own_content_metric_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("captured_hour", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("likes", sa.BigInteger(), nullable=True),
        sa.Column("comments", sa.BigInteger(), nullable=True),
        sa.Column("favorites", sa.BigInteger(), nullable=True),
        sa.Column("shares", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["content_id"], ["own_social_contents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "content_id", "captured_hour",
            name="uq_own_content_metric_snapshot_hour",
        ),
    )
    op.create_index(op.f("ix_own_content_metric_snapshots_content_id"), "own_content_metric_snapshots", ["content_id"])
    op.create_index(op.f("ix_own_content_metric_snapshots_captured_hour"), "own_content_metric_snapshots", ["captured_hour"])

    op.create_table(
        "own_dashboard_sync_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("last_error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "platform",
            name="uq_own_dashboard_sync_account_platform",
        ),
    )
    for column in ("account_id", "platform", "next_refresh_at"):
        op.create_index(op.f(f"ix_own_dashboard_sync_states_{column}"), "own_dashboard_sync_states", [column])


def downgrade() -> None:
    op.drop_table("own_dashboard_sync_states")
    op.drop_table("own_content_metric_snapshots")
    op.drop_table("own_social_contents")
