"""新增持久化选题收藏快照。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260719_000026"
down_revision: str | None = "20260717_000025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "favorite_topics",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("source_topic_id", sa.String(length=64), nullable=False),
        sa.Column("source_batch_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("platforms", sa.JSON(), nullable=False),
        sa.Column("reference_note", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "source_topic_id",
            "source_batch_id",
            name="uq_favorite_topics_source_batch",
        ),
    )
    op.create_index(op.f("ix_favorite_topics_account_id"), "favorite_topics", ["account_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_favorite_topics_account_id"), table_name="favorite_topics")
    op.drop_table("favorite_topics")
