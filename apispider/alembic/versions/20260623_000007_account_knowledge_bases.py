"""add account knowledge base schema

Revision ID: 20260623_000007
Revises: 20260623_000006
Create Date: 2026-06-23 20:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260623_000007"
down_revision = "20260623_000006"
branch_labels = None
depends_on = None


def _json_empty_object_sql(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "'{}'::json"
    return "'{}'"


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    json_empty_object = _json_empty_object_sql(dialect_name)
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "knowledge_bases" not in existing_tables:
        op.create_table(
            "knowledge_bases",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("product_name", sa.String(length=128), nullable=False),
            sa.Column("product_intro", sa.Text(), nullable=False),
            sa.Column("brand_story", sa.Text(), nullable=False),
            sa.Column("price", sa.String(length=128), nullable=False),
            sa.Column("logo_url", sa.Text(), nullable=False),
            sa.Column("image_materials", sa.JSON(), nullable=False),
            sa.Column("contact_info", sa.String(length=255), nullable=False),
            sa.Column("website_url", sa.Text(), nullable=False),
            sa.Column("enabled_fields", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        existing_tables.add("knowledge_bases")

    knowledge_base_indexes = {index["name"] for index in inspector.get_indexes("knowledge_bases")}
    if "ix_knowledge_bases_user_id" not in knowledge_base_indexes:
        op.create_index("ix_knowledge_bases_user_id", "knowledge_bases", ["user_id"], unique=False)

    account_columns = {column["name"] for column in inspector.get_columns("accounts")}
    with op.batch_alter_table("accounts") as batch_op:
        if "account_links" not in account_columns:
            batch_op.add_column(sa.Column("account_links", sa.JSON(), nullable=True))
        if "industry" not in account_columns:
            batch_op.add_column(sa.Column("industry", sa.String(length=64), nullable=True))
        if "product_service" not in account_columns:
            batch_op.add_column(sa.Column("product_service", sa.String(length=128), nullable=True))
        if "target_city" not in account_columns:
            batch_op.add_column(sa.Column("target_city", sa.String(length=64), nullable=True))
        if "target_audience" not in account_columns:
            batch_op.add_column(sa.Column("target_audience", sa.String(length=255), nullable=True))
        if "conversion_goal" not in account_columns:
            batch_op.add_column(sa.Column("conversion_goal", sa.String(length=128), nullable=True))
        if "knowledge_base_id" not in account_columns:
            batch_op.add_column(sa.Column("knowledge_base_id", sa.String(length=36), nullable=True))

    refreshed_account_columns = {column["name"] for column in sa.inspect(bind).get_columns("accounts")}
    if "account_links" in refreshed_account_columns:
        op.execute(f"UPDATE accounts SET account_links = {json_empty_object} WHERE account_links IS NULL")
    if "industry" in refreshed_account_columns:
        op.execute("UPDATE accounts SET industry = '' WHERE industry IS NULL")
    if "product_service" in refreshed_account_columns:
        op.execute("UPDATE accounts SET product_service = '' WHERE product_service IS NULL")
    if "target_city" in refreshed_account_columns:
        op.execute("UPDATE accounts SET target_city = '' WHERE target_city IS NULL")
    if "target_audience" in refreshed_account_columns:
        op.execute("UPDATE accounts SET target_audience = '' WHERE target_audience IS NULL")
    if "conversion_goal" in refreshed_account_columns:
        op.execute("UPDATE accounts SET conversion_goal = '' WHERE conversion_goal IS NULL")

    with op.batch_alter_table("accounts") as batch_op:
        if "account_links" in refreshed_account_columns:
            batch_op.alter_column("account_links", existing_type=sa.JSON(), nullable=False)
        if "industry" in refreshed_account_columns:
            batch_op.alter_column("industry", existing_type=sa.String(length=64), nullable=False)
        if "product_service" in refreshed_account_columns:
            batch_op.alter_column("product_service", existing_type=sa.String(length=128), nullable=False)
        if "target_city" in refreshed_account_columns:
            batch_op.alter_column("target_city", existing_type=sa.String(length=64), nullable=False)
        if "target_audience" in refreshed_account_columns:
            batch_op.alter_column("target_audience", existing_type=sa.String(length=255), nullable=False)
        if "conversion_goal" in refreshed_account_columns:
            batch_op.alter_column("conversion_goal", existing_type=sa.String(length=128), nullable=False)

        account_foreign_keys = {foreign_key["name"] for foreign_key in sa.inspect(bind).get_foreign_keys("accounts")}
        if "knowledge_base_id" in refreshed_account_columns and "fk_accounts_knowledge_base_id" not in account_foreign_keys:
            batch_op.create_foreign_key(
                "fk_accounts_knowledge_base_id",
                "knowledge_bases",
                ["knowledge_base_id"],
                ["id"],
            )

    account_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("accounts")}
    if "knowledge_base_id" in refreshed_account_columns and "ix_accounts_knowledge_base_id" not in account_indexes:
        op.create_index("ix_accounts_knowledge_base_id", "accounts", ["knowledge_base_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_accounts_knowledge_base_id", table_name="accounts")

    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_constraint("fk_accounts_knowledge_base_id", type_="foreignkey")
        batch_op.drop_column("knowledge_base_id")
        batch_op.drop_column("conversion_goal")
        batch_op.drop_column("target_audience")
        batch_op.drop_column("target_city")
        batch_op.drop_column("product_service")
        batch_op.drop_column("industry")
        batch_op.drop_column("account_links")

    op.drop_index("ix_knowledge_bases_user_id", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
