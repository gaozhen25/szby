"""add video analysis jobs

Revision ID: 20260626_000010
Revises: 20260625_000009
Create Date: 2026-06-26 00:00:10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260626_000010"
down_revision = "20260625_000009"
branch_labels = None
depends_on = None


def _json_empty_object_sql(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "'{}'::json"
    return "'{}'"


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "video_analysis_jobs" in existing_tables:
        return

    op.create_table(
        "video_analysis_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("creation_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("video_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("platform", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "input_payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text(_json_empty_object_sql(dialect_name)),
        ),
        sa.Column(
            "result_payload",
            sa.JSON(),
            nullable=False,
            server_default=sa.text(_json_empty_object_sql(dialect_name)),
        ),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_video_analysis_jobs_user_id", "video_analysis_jobs", ["user_id"], unique=False)
    op.create_index("ix_video_analysis_jobs_account_id", "video_analysis_jobs", ["account_id"], unique=False)
    op.create_index("ix_video_analysis_jobs_creation_id", "video_analysis_jobs", ["creation_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_video_analysis_jobs_creation_id", table_name="video_analysis_jobs")
    op.drop_index("ix_video_analysis_jobs_account_id", table_name="video_analysis_jobs")
    op.drop_index("ix_video_analysis_jobs_user_id", table_name="video_analysis_jobs")
    op.drop_table("video_analysis_jobs")
