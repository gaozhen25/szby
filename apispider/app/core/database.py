from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, settings
from app.db.base import Base


def configure_connection_search_path(dbapi_connection: Any, search_path: str) -> None:
    with dbapi_connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, %s, false)", ("search_path", search_path))


def create_app_engine(database_url: str | None = None, config: Settings = settings) -> Engine:
    resolved_url = database_url or config.sync_database_url
    engine_options = {"pool_pre_ping": config.db_pool_pre_ping}
    if not resolved_url.startswith("sqlite"):
        engine_options.update(
            {
                "pool_size": config.db_pool_size,
                "max_overflow": config.db_max_overflow,
                "pool_timeout": config.db_pool_timeout,
                "pool_recycle": config.db_pool_recycle,
            }
        )
    engine = create_engine(resolved_url, **engine_options)
    if not resolved_url.startswith("sqlite") and config.db_search_path.strip():
        search_path = config.db_search_path.strip()

        @event.listens_for(engine, "connect")
        def _set_search_path(dbapi_connection: Any, connection_record: Any) -> None:  # noqa: ARG001
            configure_connection_search_path(dbapi_connection, search_path)

    return engine


engine = create_app_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
