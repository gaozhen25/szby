from app.core.config import Settings


def test_sync_database_url_keeps_psycopg_url():
    settings = Settings(database_url="postgresql+psycopg://user:pass@localhost:5432/starx")

    assert settings.sync_database_url == "postgresql+psycopg://user:pass@localhost:5432/starx"


def test_sync_database_url_converts_asyncpg_url_for_alembic():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost:5432/starx")

    assert settings.sync_database_url == "postgresql+psycopg://user:pass@localhost:5432/starx"
