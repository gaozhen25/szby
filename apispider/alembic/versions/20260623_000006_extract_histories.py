"""extract histories

Revision ID: 20260623_000006
Revises: 20260617_000005
Create Date: 2026-06-23 00:00:06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260623_000006"
down_revision = "20260617_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extract_histories",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("resolved_url", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("images", sa.JSON(), nullable=False),
        sa.Column("videos", sa.JSON(), nullable=False),
        sa.Column("cover", sa.Text(), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_extract_histories_user_id", "extract_histories", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_extract_histories_user_id", table_name="extract_histories")
    op.drop_table("extract_histories")
