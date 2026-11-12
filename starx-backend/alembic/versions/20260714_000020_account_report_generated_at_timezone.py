"""统一账号报告生成时间的 PostgreSQL 时区类型。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260714_000020"
down_revision: str | None = "20260714_000019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    generated_at = next(
        (column for column in inspect(bind).get_columns("reports") if column["name"] == "generated_at"),
        None,
    )
    if generated_at is None or getattr(generated_at["type"], "timezone", False):
        return
    op.alter_column(
        "reports",
        "generated_at",
        existing_type=sa.DateTime(timezone=False),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using="generated_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    generated_at = next(
        (column for column in inspect(bind).get_columns("reports") if column["name"] == "generated_at"),
        None,
    )
    if generated_at is None or not getattr(generated_at["type"], "timezone", False):
        return
    op.alter_column(
        "reports",
        "generated_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(timezone=False),
        existing_nullable=True,
        postgresql_using="generated_at AT TIME ZONE 'UTC'",
    )
