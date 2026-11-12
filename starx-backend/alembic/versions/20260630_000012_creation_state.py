"""add creation state snapshot

Revision ID: 20260630_000012
Revises: 20260629_000011
Create Date: 2026-06-30 00:00:12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260630_000012"
down_revision = "20260629_000011"
branch_labels = None
depends_on = None


def _json_empty_object_sql(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "'{}'::json"
    return "'{}'"


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    columns = {column["name"] for column in sa.inspect(bind).get_columns("content_creations")}
    if "creation_state" in columns:
        return
    with op.batch_alter_table("content_creations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "creation_state",
                sa.JSON(),
                nullable=False,
                server_default=sa.text(_json_empty_object_sql(dialect_name)),
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("content_creations")}
    if "creation_state" not in columns:
        return
    with op.batch_alter_table("content_creations") as batch_op:
        batch_op.drop_column("creation_state")
