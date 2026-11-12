from fastapi.testclient import TestClient

from app.api import deps
from app.api.deps import get_service
from app.main import app
from app.services.db_service import DBService
from tests.db_test_utils import db_session


class StubAIService:
    async def analyze_report_section(self, *, section_key: str, account_context: dict[str, object]) -> str:
        return f"AI generated {section_key} for {account_context['name']}"


def test_report_analysis_updates_database_backed_section():
    with db_session() as session:
        service = DBService(session)
        app.dependency_overrides[get_service] = lambda: service
        app.dependency_overrides[deps.get_ai_service] = lambda: StubAIService()
        try:
            client = TestClient(app)
            login = client.post("/api/v1/auth/login", json={"email": "demo@starx.ai", "password": "demo123"})
            headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}
            account_id = client.get("/api/v1/accounts", headers=headers).json()[0]["id"]

            response = client.post(
                f"/api/v1/accounts/{account_id}/report/sections/competitors/analyze",
                headers=headers,
            )

            assert response.status_code == 200
            assert response.json()["competitors"] == "AI generated competitors for 美妆号_01"
            assert service.get_report("u_001", account_id).competitors == "AI generated competitors for 美妆号_01"
        finally:
            app.dependency_overrides.clear()
