"""为竞品账号保存抖音 sec_user_id。"""

from collections.abc import Sequence
from urllib.parse import urlparse

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_000029"
down_revision: str | None = "20260721_000028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _extract_sec_user_id(profile_url: str) -> str:
    parsed = urlparse(profile_url)
    host = (parsed.hostname or "").lower()
    if host != "douyin.com" and not host.endswith(".douyin.com"):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    return parts[1] if len(parts) >= 2 and parts[0] == "user" else ""


def upgrade() -> None:
    op.add_column(
        "competitor_accounts",
        sa.Column(
            "sec_user_id",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
    )
    op.create_index(
        op.f("ix_competitor_accounts_sec_user_id"),
        "competitor_accounts",
        ["sec_user_id"],
        unique=False,
    )

    accounts = sa.table(
        "competitor_accounts",
        sa.column("id", sa.String()),
        sa.column("profile_url", sa.Text()),
        sa.column("sec_user_id", sa.String()),
    )
    connection = op.get_bind()
    for account_id, profile_url in connection.execute(
        sa.select(accounts.c.id, accounts.c.profile_url)
    ):
        sec_user_id = _extract_sec_user_id(profile_url or "")
        if sec_user_id:
            connection.execute(
                accounts.update()
                .where(accounts.c.id == account_id)
                .values(sec_user_id=sec_user_id)
            )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_competitor_accounts_sec_user_id"),
        table_name="competitor_accounts",
    )
    op.drop_column("competitor_accounts", "sec_user_id")
