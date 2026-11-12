from app.core.security import verify_password
from app.db.models import UserRecord
from scripts.reset_password import reset_password
from tests.db_test_utils import db_session


def test_reset_password_generates_password_and_updates_hash():
    with db_session() as session:
        before = session.get(UserRecord, "u_001")
        assert before is not None
        previous_hash = before.password_hash

        credentials = reset_password(session, email=" DEMO@STARX.AI ")

        persisted = session.get(UserRecord, "u_001")
        assert persisted is not None
        assert credentials.account == "demo@starx.ai"
        assert credentials.user_id == "u_001"
        assert len(credentials.password) == 16
        assert persisted.password_hash != previous_hash
        assert credentials.password != persisted.password_hash
        assert verify_password(credentials.password, persisted.password_hash)


def test_reset_password_uses_explicit_password():
    with db_session() as session:
        credentials = reset_password(
            session,
            email="demo@starx.ai",
            password="newsecret88",
        )

        persisted = session.get(UserRecord, "u_001")
        assert persisted is not None
        assert credentials.password == "newsecret88"
        assert verify_password("newsecret88", persisted.password_hash)
