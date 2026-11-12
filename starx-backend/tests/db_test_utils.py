from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.init_db import init_database


@contextmanager
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        init_database(engine)
        with Session(engine) as session:
            try:
                yield session
            finally:
                session.rollback()
    finally:
        # 业务代码会主动 commit，单纯 rollback 无法清理已经提交的数据。
        # 每个测试结束后删除临时库中的全部表，再释放连接，确保测试数据不残留。
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
