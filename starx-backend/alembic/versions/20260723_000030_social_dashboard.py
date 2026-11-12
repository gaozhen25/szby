"""为平台账号号与社媒数据看板增加持久化结构。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_000030"
down_revision: str | None = "20260722_000029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "platform_accounts",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "platform_account_identities",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )

    op.create_table(
        "dashboard_account_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("observed_date", sa.Date(), nullable=False),
        sa.Column("followers", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("follows", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("content_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_likes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "platform",
            "observed_date",
            name="uq_dashboard_account_snapshot_day",
        ),
    )
    op.create_index(
        op.f("ix_dashboard_account_snapshots_account_id"),
        "dashboard_account_snapshots",
        ["account_id"],
    )
    op.create_index(
        op.f("ix_dashboard_account_snapshots_platform"),
        "dashboard_account_snapshots",
        ["platform"],
    )
    op.create_index(
        op.f("ix_dashboard_account_snapshots_observed_date"),
        "dashboard_account_snapshots",
        ["observed_date"],
    )

    op.create_table(
        "dashboard_content_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("content_id", sa.String(length=255), nullable=False),
        sa.Column("observed_date", sa.Date(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_type", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("published_at", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("views", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("likes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("comments", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("shares", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("favorites", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "platform",
            "content_id",
            "observed_date",
            name="uq_dashboard_content_snapshot_day",
        ),
    )
    for column in ("account_id", "platform", "content_id", "observed_date"):
        op.create_index(
            op.f(f"ix_dashboard_content_snapshots_{column}"),
            "dashboard_content_snapshots",
            [column],
        )


def downgrade() -> None:
    op.drop_table("dashboard_content_snapshots")
    op.drop_table("dashboard_account_snapshots")
    op.drop_column("accounts", "platform_account_identities")
    op.drop_column("accounts", "platform_accounts")
