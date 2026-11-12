"""为知识库增加行业字段。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260716_000023"
down_revision: str | None = "20260716_000022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("knowledge_bases")
    }
    if "industry" not in columns:
        op.add_column(
            "knowledge_bases",
            sa.Column(
                "industry",
                sa.String(length=64),
                nullable=False,
                server_default="",
            ),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("knowledge_bases")
    }
    if "industry" in columns:
        with op.batch_alter_table("knowledge_bases") as batch_op:
            batch_op.drop_column("industry")
