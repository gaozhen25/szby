"""replace jobs with unified workflows

Revision ID: 20260701_000014
Revises: 20260630_000013
Create Date: 2026-07-01 00:00:14
"""

from alembic import op
import sqlalchemy as sa


revision = "20260701_000014"
down_revision = "20260630_000013"
branch_labels = None
depends_on = None


def _json_empty_object_sql(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "'{}'::json"
    return "'{}'"


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "job_sub_tasks" in existing_tables:
        op.drop_table("job_sub_tasks")
    if "generation_assets" in existing_tables:
        op.drop_table("generation_assets")
    if "video_analysis_jobs" in existing_tables:
        op.drop_table("video_analysis_jobs")
    if "generation_jobs" in existing_tables:
        op.drop_table("generation_jobs")

    if "workflows" not in existing_tables:
        op.create_table(
            "workflows",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("type", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("current_stage", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("creation_id", sa.String(length=64), nullable=True),
            sa.Column("target_platform", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("topic_title", sa.String(length=255), nullable=True),
            sa.Column("copy_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
            sa.Column("ratio", sa.String(length=16), nullable=True),
            sa.Column("requested_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("video_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("cover_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("platform", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("error", sa.Text(), nullable=False, server_default=""),
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
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("id", "account_id", name="uq_workflows_id_account_id"),
        )
        op.create_index("ix_workflows_account_id", "workflows", ["account_id"])
        op.create_index("ix_workflows_user_id", "workflows", ["user_id"])
        op.create_index("ix_workflows_type", "workflows", ["type"])
        op.create_index("ix_workflows_creation_id", "workflows", ["creation_id"])

    op.create_table(
        "generation_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("analysis", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "meta",
            sa.JSON(),
            nullable=False,
            server_default=sa.text(_json_empty_object_sql(dialect_name)),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id", "account_id"],
            ["workflows.id", "workflows.account_id"],
            name="fk_generation_assets_workflow_account",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_generation_assets_workflow_id", "generation_assets", ["workflow_id"])
    op.create_index("ix_generation_assets_account_id", "generation_assets", ["account_id"])

    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("group_key", sa.String(length=64), nullable=False, server_default=""),
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
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_workflow_steps_workflow_id", "workflow_steps", ["workflow_id"])
    op.create_index("ix_workflow_steps_user_id", "workflow_steps", ["user_id"])
    op.create_index("ix_workflow_steps_account_id", "workflow_steps", ["account_id"])
    op.create_index("ix_workflow_steps_asset_id", "workflow_steps", ["asset_id"])
    op.create_index("ix_workflow_steps_type", "workflow_steps", ["type"])


def downgrade() -> None:
    op.drop_table("workflow_steps")
    op.drop_table("generation_assets")
    op.drop_table("workflows")
