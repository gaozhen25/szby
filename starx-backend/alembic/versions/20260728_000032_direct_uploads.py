"""增加浏览器直传 OSS 授权与审计记录。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_000032"
down_revision: str | None = "20260727_000031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "direct_uploads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=True),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("object_url", sa.Text(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("declared_content_type", sa.String(length=128), nullable=False),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("actual_content_type", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("actual_size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("etag", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("consumed_by_type", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("consumed_by_id", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
        sa.UniqueConstraint("object_url"),
    )
    for column in ("user_id", "account_id", "purpose", "status", "expires_at"):
        op.create_index(op.f(f"ix_direct_uploads_{column}"), "direct_uploads", [column])


def downgrade() -> None:
    op.drop_table("direct_uploads")
