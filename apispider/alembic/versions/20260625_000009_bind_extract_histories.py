"""bind extract histories to workflow tasks

Revision ID: 20260625_000009
Revises: 20260624_000008
Create Date: 2026-06-25 00:00:09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260625_000009"
down_revision = "20260624_000008"
branch_labels = None
depends_on = None


def _json_empty_array_sql(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "'[]'::jsonb"
    return "'[]'"


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    columns = {column["name"] for column in sa.inspect(bind).get_columns("extract_histories")}

    with op.batch_alter_table("extract_histories") as batch_op:
        if "account_id" not in columns:
            batch_op.add_column(sa.Column("account_id", sa.String(length=36), nullable=True))
        if "creation_id" not in columns:
            batch_op.add_column(sa.Column("creation_id", sa.String(length=64), nullable=True))
        if "task_id" not in columns:
            batch_op.add_column(sa.Column("task_id", sa.String(length=36), nullable=True))
        if "hashtags" not in columns:
            batch_op.add_column(
                sa.Column(
                    "hashtags",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text(_json_empty_array_sql(dialect_name)),
                )
            )

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("extract_histories")}
    if "ix_extract_histories_account_id" not in indexes:
        op.create_index("ix_extract_histories_account_id", "extract_histories", ["account_id"], unique=False)
    if "ix_extract_histories_creation_id" not in indexes:
        op.create_index("ix_extract_histories_creation_id", "extract_histories", ["creation_id"], unique=False)
    if "ix_extract_histories_task_id" not in indexes:
        op.create_index("ix_extract_histories_task_id", "extract_histories", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_extract_histories_task_id", table_name="extract_histories")
    op.drop_index("ix_extract_histories_creation_id", table_name="extract_histories")
    op.drop_index("ix_extract_histories_account_id", table_name="extract_histories")
    with op.batch_alter_table("extract_histories") as batch_op:
        batch_op.drop_column("hashtags")
        batch_op.drop_column("task_id")
        batch_op.drop_column("creation_id")
        batch_op.drop_column("account_id")
