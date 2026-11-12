import string

from app.core.security import verify_password
from app.db.models import UserRecord
from scripts.create_user import PASSWORD_SYMBOLS, create_user, generate_password
from tests.db_test_utils import db_session


def test_generate_password_contains_required_character_groups():
    password = generate_password()

    assert len(password) == 16
    assert any(character in string.ascii_lowercase for character in password)
    assert any(character in string.ascii_uppercase for character in password)
    assert any(character in string.digits for character in password)
    assert any(character in PASSWORD_SYMBOLS for character in password)


def test_create_user_returns_generated_credentials_and_stores_only_hash():
    with db_session() as session:
        credentials = create_user(
            session,
            email="Generated-User@StarX.ai ",
            nickname="",
            user_id="u_generated",
        )

        persisted = session.get(UserRecord, "u_generated")
        assert persisted is not None
        assert credentials.account == "generated-user@starx.ai"
        assert credentials.nickname == "generated-user"
        assert credentials.password != persisted.password_hash
        assert verify_password(credentials.password, persisted.password_hash)


def test_create_user_returns_explicit_password():
    with db_session() as session:
        credentials = create_user(
            session,
            email="specified@starx.ai",
            nickname="Specified",
            password="initial88",
            user_id="u_specified",
        )

        assert credentials.account == "specified@starx.ai"
        assert credentials.password == "initial88"
