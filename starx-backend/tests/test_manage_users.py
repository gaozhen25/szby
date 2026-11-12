import pytest
from sqlalchemy import select

from app.core.security import verify_password
from app.db.manage_users import add_user, build_parser, change_password
from app.db.models import UserRecord
from tests.db_test_utils import db_session


def test_add_user_creates_active_user_with_hashed_password():
    with db_session() as session:
        user = add_user(
            session,
            email="new-user@starx.ai",
            password="secret88",
            nickname="New User",
            user_id="u_new",
        )

        persisted = session.get(UserRecord, "u_new")
        assert user.id == "u_new"
        assert persisted is not None
        assert persisted.email == "new-user@starx.ai"
        assert persisted.nickname == "New User"
        assert persisted.status == "active"
        assert persisted.password_hash != "secret88"
        assert verify_password("secret88", persisted.password_hash)


def test_add_user_rejects_duplicate_email():
    with db_session() as session:
        with pytest.raises(ValueError, match="user_exists"):
            add_user(session, email="demo@starx.ai", password="secret88", nickname="Duplicate")


def test_change_password_updates_existing_user_hash():
    with db_session() as session:
        before = session.scalar(select(UserRecord).where(UserRecord.email == "demo@starx.ai"))
        assert before is not None
        previous_hash = before.password_hash

        user = change_password(session, email="demo@starx.ai", password="newsecret88")

        assert user.email == "demo@starx.ai"
        assert user.password_hash != previous_hash
        assert verify_password("newsecret88", user.password_hash)


def test_change_password_rejects_unknown_email():
    with db_session() as session:
        with pytest.raises(ValueError, match="user_not_found"):
            change_password(session, email="missing@starx.ai", password="newsecret88")


def test_cli_describes_tob_accounts_without_admin_role():
    help_text = build_parser().format_help()

    assert "toB accounts" in help_text
    assert "admin" not in help_text.lower()
    assert "管理员" not in help_text
