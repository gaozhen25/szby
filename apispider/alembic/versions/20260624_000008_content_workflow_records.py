"""add content workflow records

Revision ID: 20260624_000008
Revises: 20260623_000007
Create Date: 2026-06-24 10:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260624_000008"
down_revision = "20260623_000007"
branch_labels = None
depends_on = None


def _json_empty_array_sql(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "'[]'::json"
    return "'[]'"


def _json_empty_object_sql(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "'{}'::json"
    return "'{}'"


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "content_creations" not in existing_tables:
        op.create_table(
            "content_creations",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("account_id", sa.String(length=36), sa.ForeignKey("accounts.id"), nullable=False),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("topic_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("topic_title", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("content_type", sa.String(length=32), nullable=False),
            sa.Column("target_platform", sa.String(length=32), nullable=False),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("script_original", sa.JSON(), nullable=False, server_default=sa.text(_json_empty_array_sql(dialect_name))),
            sa.Column("script_rewritten", sa.JSON(), nullable=False, server_default=sa.text(_json_empty_array_sql(dialect_name))),
            sa.Column("hashtags", sa.JSON(), nullable=False, server_default=sa.text(_json_empty_array_sql(dialect_name))),
            sa.Column("cover", sa.JSON(), nullable=False, server_default=sa.text(_json_empty_object_sql(dialect_name))),
            sa.Column("bgm_suggestion", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("sensitive_check", sa.JSON(), nullable=False, server_default=sa.text(_json_empty_object_sql(dialect_name))),
            sa.Column("image_prompt", sa.Text(), nullable=False, server_default=""),
            sa.Column("assets", sa.JSON(), nullable=False, server_default=sa.text(_json_empty_array_sql(dialect_name))),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_content_creations_account_id", "content_creations", ["account_id"], unique=False)
        op.create_index("ix_content_creations_user_id", "content_creations", ["user_id"], unique=False)

    task_columns = {column["name"] for column in inspector.get_columns("tasks")}
    with op.batch_alter_table("tasks") as batch_op:
        if "creation_id" not in task_columns:
            batch_op.add_column(sa.Column("creation_id", sa.String(length=36), nullable=True))
        if "body" not in task_columns:
            batch_op.add_column(sa.Column("body", sa.Text(), nullable=False, server_default=""))
        if "tags" not in task_columns:
            batch_op.add_column(sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text(_json_empty_array_sql(dialect_name))))
        if "assignee" not in task_columns:
            batch_op.add_column(sa.Column("assignee", sa.String(length=64), nullable=False, server_default=""))
        if "due_date" not in task_columns:
            batch_op.add_column(sa.Column("due_date", sa.String(length=32), nullable=False, server_default=""))
        if "priority" not in task_columns:
            batch_op.add_column(sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"))
        if "handoff_note" not in task_columns:
            batch_op.add_column(sa.Column("handoff_note", sa.Text(), nullable=False, server_default=""))

    refreshed_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("tasks")}
    if "ix_tasks_creation_id" not in refreshed_indexes:
        op.create_index("ix_tasks_creation_id", "tasks", ["creation_id"], unique=False)

    refreshed_columns = {column["name"] for column in sa.inspect(bind).get_columns("tasks")}
    if "creation_id" in refreshed_columns:
        foreign_keys = {foreign_key["name"] for foreign_key in sa.inspect(bind).get_foreign_keys("tasks")}
        if "fk_tasks_creation_id" not in foreign_keys:
            with op.batch_alter_table("tasks") as batch_op:
                batch_op.create_foreign_key("fk_tasks_creation_id", "content_creations", ["creation_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_constraint("fk_tasks_creation_id", type_="foreignkey")
        batch_op.drop_column("handoff_note")
        batch_op.drop_column("priority")
        batch_op.drop_column("due_date")
        batch_op.drop_column("assignee")
        batch_op.drop_column("tags")
        batch_op.drop_column("body")
        batch_op.drop_column("creation_id")

    op.drop_index("ix_content_creations_user_id", table_name="content_creations")
    op.drop_index("ix_content_creations_account_id", table_name="content_creations")
    op.drop_table("content_creations")
