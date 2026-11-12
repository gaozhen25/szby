from sqlalchemy.pool import QueuePool

from app.core.config import Settings
from app.core.database import configure_connection_search_path, create_app_engine


def test_create_app_engine_uses_configured_postgres_pool():
    config = Settings(
        database_url="postgresql+psycopg://user:pass@localhost:5432/starx",
        db_pool_size=3,
        db_max_overflow=4,
        db_pool_timeout=5,
        db_pool_recycle=6,
        db_pool_pre_ping=True,
    )

    engine = create_app_engine(config=config)

    assert isinstance(engine.pool, QueuePool)
    assert engine.pool.size() == 3
    assert engine.pool._max_overflow == 4
    assert engine.pool._timeout == 5
    assert engine.pool._recycle == 6


def test_create_app_engine_skips_queue_pool_options_for_sqlite():
    config = Settings(database_url="sqlite:///:memory:")

    engine = create_app_engine(config=config)

    assert engine.url.drivername == "sqlite"


class FakeCursor:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, statement, parameters):
        self.calls.append((statement, parameters))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()

    def cursor(self):
        return self.cursor_instance


def test_configure_connection_search_path_uses_parameterized_set_config():
    connection = FakeConnection()

    configure_connection_search_path(connection, "public")

    assert connection.cursor_instance.calls == [
        ("SELECT set_config(%s, %s, false)", ("search_path", "public"))
    ]
