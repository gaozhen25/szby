"""generation jobs assets

Revision ID: 20260617_000005
Revises: 20260616_000004
Create Date: 2026-06-17 00:00:05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260617_000005"
down_revision = "20260616_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("target_platform", sa.String(length=32), nullable=False),
        sa.Column("topic_title", sa.String(length=255), nullable=True),
        sa.Column("copy_text", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("ratio", sa.String(length=16), nullable=True),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("parent_job_id", sa.String(length=36), sa.ForeignKey("generation_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("id", "account_id", name="uq_generation_jobs_id_account_id"),
    )
    op.create_index("ix_generation_jobs_account_id", "generation_jobs", ["account_id"], unique=False)
    op.create_index("ix_generation_jobs_user_id", "generation_jobs", ["user_id"], unique=False)
    op.create_index("ix_generation_jobs_parent_job_id", "generation_jobs", ["parent_job_id"], unique=False)

    op.create_table(
        "generation_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("analysis", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id", "account_id"],
            ["generation_jobs.id", "generation_jobs.account_id"],
            name="fk_generation_assets_job_account",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_generation_assets_job_id", "generation_assets", ["job_id"], unique=False)
    op.create_index("ix_generation_assets_account_id", "generation_assets", ["account_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_generation_assets_account_id", table_name="generation_assets")
    op.drop_index("ix_generation_assets_job_id", table_name="generation_assets")
    op.drop_table("generation_assets")
    op.drop_index("ix_generation_jobs_parent_job_id", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_user_id", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_account_id", table_name="generation_jobs")
    op.drop_table("generation_jobs")
