import asyncio
from types import SimpleNamespace

from app.db.models import AccountRecord
from app.services.own_content_analytics import refresh_jobs
from app.services.own_content_analytics.refresh_jobs import (
    DashboardRefreshJobService,
)
from tests.db_test_utils import db_session


def _configure_xhs_account(session):
    account = session.get(AccountRecord, "acc1")
    account.platforms = ["小红书"]
    account.platform_accounts = {"小红书": "red-id"}
    session.commit()


def test_enqueue_deduplicates_active_dashboard_refresh():
    with db_session() as session:
        _configure_xhs_account(session)
        service = DashboardRefreshJobService(
            session,
            runtime_settings=SimpleNamespace(
                social_retrieval_provider="mediaspider"
            ),
        )

        first = service.enqueue(
            user_id="u_001", account_id="acc1", platform_name="小红书"
        )
        second = service.enqueue(
            user_id="u_001", account_id="acc1", platform_name="小红书"
        )

        assert first.refreshId == second.refreshId
        assert first.status == "pending"
        assert first.provider == "mediaspider"


def test_claimed_dashboard_refresh_completes_and_reports_item_count(monkeypatch):
    class FakeAnalytics:
        def __init__(self, session, *, runtime_settings):  # noqa: ARG002
            pass

        async def refresh(self, *, user_id, account_id, platform_name):
            assert (user_id, account_id, platform_name) == (
                "u_001",
                "acc1",
                "小红书",
            )
            return 6

    monkeypatch.setattr(refresh_jobs, "OwnContentAnalyticsService", FakeAnalytics)

    with db_session() as session:
        _configure_xhs_account(session)
        service = DashboardRefreshJobService(
            session,
            runtime_settings=SimpleNamespace(
                social_retrieval_provider="mediaspider"
            ),
        )
        created = service.enqueue(
            user_id="u_001", account_id="acc1", platform_name="小红书"
        )

        assert service.claim_pending(10) == [created.refreshId]
        running = service.get(
            user_id="u_001",
            account_id="acc1",
            refresh_id=created.refreshId,
        )
        assert running.status == "running"
        assert running.progress == 15

        asyncio.run(service.execute_claimed(created.refreshId))
        completed = service.get(
            user_id="u_001",
            account_id="acc1",
            refresh_id=created.refreshId,
        )

        assert completed.status == "succeeded"
        assert completed.stage == "completed"
        assert completed.progress == 100
        assert completed.itemCount == 6


def test_dashboard_refresh_failure_is_terminal_and_retryable(monkeypatch):
    class FailingAnalytics:
        def __init__(self, session, *, runtime_settings):  # noqa: ARG002
            pass

        async def refresh(self, **kwargs):  # noqa: ARG002
            raise RuntimeError("平台暂时不可用")

    monkeypatch.setattr(
        refresh_jobs, "OwnContentAnalyticsService", FailingAnalytics
    )

    with db_session() as session:
        _configure_xhs_account(session)
        service = DashboardRefreshJobService(session)
        created = service.enqueue(
            user_id="u_001", account_id="acc1", platform_name="小红书"
        )
        service.claim_pending(1)
        asyncio.run(service.execute_claimed(created.refreshId))

        failed = service.get(
            user_id="u_001",
            account_id="acc1",
            refresh_id=created.refreshId,
        )
        assert failed.status == "failed"
        assert failed.message == "平台暂时不可用"

        retried = service.enqueue(
            user_id="u_001", account_id="acc1", platform_name="小红书"
        )
        assert retried.refreshId != created.refreshId
        assert retried.status == "pending"
