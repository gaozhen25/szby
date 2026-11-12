"""add durable job sub tasks

Revision ID: 20260629_000011
Revises: 20260626_000010
Create Date: 2026-06-29 00:00:11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260629_000011"
down_revision = "20260626_000010"
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
    if "job_sub_tasks" in existing_tables:
        return

    op.create_table(
        "job_sub_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("parent_job_id", sa.String(length=36), nullable=False),
        sa.Column("parent_job_kind", sa.String(length=32), nullable=False),
        sa.Column("parent_job_type", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("sub_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
    op.create_index("ix_job_sub_tasks_parent_job_id", "job_sub_tasks", ["parent_job_id"], unique=False)
    op.create_index("ix_job_sub_tasks_parent_job_kind", "job_sub_tasks", ["parent_job_kind"], unique=False)
    op.create_index("ix_job_sub_tasks_parent_job_type", "job_sub_tasks", ["parent_job_type"], unique=False)
    op.create_index("ix_job_sub_tasks_user_id", "job_sub_tasks", ["user_id"], unique=False)
    op.create_index("ix_job_sub_tasks_account_id", "job_sub_tasks", ["account_id"], unique=False)
    op.create_index("ix_job_sub_tasks_asset_id", "job_sub_tasks", ["asset_id"], unique=False)
    op.create_index("ix_job_sub_tasks_sub_type", "job_sub_tasks", ["sub_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_sub_tasks_sub_type", table_name="job_sub_tasks")
    op.drop_index("ix_job_sub_tasks_asset_id", table_name="job_sub_tasks")
    op.drop_index("ix_job_sub_tasks_account_id", table_name="job_sub_tasks")
    op.drop_index("ix_job_sub_tasks_user_id", table_name="job_sub_tasks")
    op.drop_index("ix_job_sub_tasks_parent_job_type", table_name="job_sub_tasks")
    op.drop_index("ix_job_sub_tasks_parent_job_kind", table_name="job_sub_tasks")
    op.drop_index("ix_job_sub_tasks_parent_job_id", table_name="job_sub_tasks")
    op.drop_table("job_sub_tasks")
