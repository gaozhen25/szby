from datetime import UTC, datetime

from fastapi.testclient import TestClient
from jose import jwt

from app.api.deps import get_service
from app.core.config import settings
from app.main import app
from app.services.db_service import DBService
from tests.db_test_utils import db_session


def test_login_returns_expiring_jwt_and_me_accepts_it():
    with db_session() as session:
        service = DBService(session)
        app.dependency_overrides[get_service] = lambda: service
        try:
            client = TestClient(app)

            login = client.post("/api/v1/auth/login", json={"email": "demo@starx.ai", "password": "demo123"})

            assert login.status_code == 200
            token = login.json()["accessToken"]
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            assert payload["sub"] == "u_001"
            assert datetime.fromtimestamp(payload["exp"], tz=UTC) > datetime.now(UTC)

            me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert me.status_code == 200
            assert me.json()["email"] == "demo@starx.ai"
        finally:
            app.dependency_overrides.clear()


def test_me_rejects_invalid_jwt():
    with db_session() as session:
        service = DBService(session)
        app.dependency_overrides[get_service] = lambda: service
        try:
            client = TestClient(app)

            me = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})

            assert me.status_code == 401
            assert me.json()["detail"] == "Invalid authorization token"
        finally:
            app.dependency_overrides.clear()
