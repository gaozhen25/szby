from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260716_000023_knowledge_base_industry.py"
)


def _load_migration():
    spec = spec_from_file_location("knowledge_base_industry_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_knowledge_base_industry_migration_metadata():
    assert MIGRATION_PATH.exists()
    migration = _load_migration()
    assert migration.revision == "20260716_000023"
    assert migration.down_revision == "20260716_000022"


def test_knowledge_base_industry_migration_round_trip(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'knowledge-base-industry.db'}")
    metadata = sa.MetaData()
    knowledge_bases = sa.Table(
        "knowledge_bases",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            knowledge_bases.insert().values(id="kb-existing", name="既有知识库")
        )
        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

    columns = {
        column["name"]: column
        for column in sa.inspect(engine).get_columns("knowledge_bases")
    }
    assert columns["industry"]["nullable"] is False
    assert isinstance(columns["industry"]["type"], sa.String)
    assert columns["industry"]["type"].length == 64

    upgraded = sa.Table("knowledge_bases", sa.MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        assert connection.execute(
            sa.select(upgraded.c.industry).where(upgraded.c.id == "kb-existing")
        ).scalar_one() == ""
        connection.execute(
            upgraded.insert().values(id="kb-default", name="缺省行业知识库")
        )
        assert connection.execute(
            sa.select(upgraded.c.industry).where(upgraded.c.id == "kb-default")
        ).scalar_one() == ""
        connection.execute(
            upgraded.update()
            .where(upgraded.c.id == "kb-existing")
            .values(industry="美妆护肤")
        )

        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()

    downgraded_columns = {
        column["name"] for column in sa.inspect(engine).get_columns("knowledge_bases")
    }
    assert "industry" not in downgraded_columns
    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT name FROM knowledge_bases WHERE id = 'kb-existing'")
        ).scalar_one() == "既有知识库"
    engine.dispose()
