"""扩展工作流类型字段长度。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_000028"
down_revision: str | None = "20260721_000027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "workflows",
        "type",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "workflows",
        "type",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
