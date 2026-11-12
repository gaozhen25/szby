from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.db.models import (
    CompetitorAccountRecord,
    CompetitorSnapshotRecord,
    CompetitorVideoRecord,
)
from tests.db_test_utils import db_session


def test_competitor_account_and_video_persist_for_an_operating_account():
    now = datetime.now(UTC)
    with db_session() as session:
        account = CompetitorAccountRecord(
            id="ca_1",
            account_id="acc1",
            user_id="u_001",
            platform="dy",
            profile_url="https://www.douyin.com/user/a",
            next_refresh_at=now,
        )
        video = CompetitorVideoRecord(
            id="cv_1",
            account_id="acc1",
            user_id="u_001",
            platform="dy",
            content_url="https://www.douyin.com/video/1",
            next_refresh_at=now,
        )
        session.add_all([account, video])
        session.commit()

        assert session.get(CompetitorAccountRecord, "ca_1").profile_url.endswith("/a")
        assert session.get(CompetitorVideoRecord, "cv_1").content_url.endswith("/1")


@pytest.mark.parametrize("target_type", ["account", "video"])
def test_deleting_competitor_target_cascades_its_snapshots(target_type):
    now = datetime.now(UTC)
    with db_session() as session:
        if target_type == "account":
            target = CompetitorAccountRecord(
                id="ca_cascade",
                account_id="acc1",
                user_id="u_001",
                platform="dy",
                profile_url="https://www.douyin.com/user/cascade",
                next_refresh_at=now,
            )
            snapshot = CompetitorSnapshotRecord(
                target_type="account",
                target_id=target.id,
                competitor_account_id=target.id,
                workflow_id="wf_account_snapshot",
                metrics={"followers": 10},
                captured_at=now,
            )
        else:
            target = CompetitorVideoRecord(
                id="cv_cascade",
                account_id="acc1",
                user_id="u_001",
                platform="dy",
                content_url="https://www.douyin.com/video/cascade",
                next_refresh_at=now,
            )
            snapshot = CompetitorSnapshotRecord(
                target_type="video",
                target_id=target.id,
                competitor_video_id=target.id,
                workflow_id="wf_video_snapshot",
                metrics={"likes": 10},
                captured_at=now,
            )
        session.add_all([target, snapshot])
        session.commit()
        snapshot_id = snapshot.id

        session.delete(target)
        session.commit()

        assert session.get(CompetitorSnapshotRecord, snapshot_id) is None


def test_competitor_scheduler_settings_have_safe_defaults():
    configured = Settings(_env_file=None)

    assert configured.COMPETITOR_REFRESH_INTERVAL_SECONDS == 21600
    assert configured.COMPETITOR_SCHEDULER_SCAN_SECONDS == 60
    assert configured.COMPETITOR_SCHEDULER_BATCH_SIZE == 20
    assert configured.COMPETITOR_WORKFLOW_HEARTBEAT_SECONDS == 60
    assert configured.COMPETITOR_WORKFLOW_STALE_SECONDS == 7200
    assert configured.COMPETITOR_CRAWL_MAX_ATTEMPTS == 3
    assert configured.COMPETITOR_CRAWL_RETRY_BACKOFF_SECONDS == 1.0


def test_competitor_heartbeat_must_be_shorter_than_stale_lease(monkeypatch):
    monkeypatch.setenv("STARX_COMPETITOR_WORKFLOW_STALE_SECONDS", "300")
    monkeypatch.setenv("STARX_COMPETITOR_WORKFLOW_HEARTBEAT_SECONDS", "101")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("STARX_COMPETITOR_REFRESH_INTERVAL_SECONDS", "59"),
        ("STARX_COMPETITOR_SCHEDULER_SCAN_SECONDS", "0"),
        ("STARX_COMPETITOR_SCHEDULER_BATCH_SIZE", "0"),
        ("STARX_COMPETITOR_SCHEDULER_BATCH_SIZE", "101"),
        ("STARX_COMPETITOR_CRAWL_MAX_ATTEMPTS", "0"),
        ("STARX_COMPETITOR_CRAWL_MAX_ATTEMPTS", "6"),
        ("STARX_COMPETITOR_CRAWL_RETRY_BACKOFF_SECONDS", "-1"),
    ],
)
def test_competitor_scheduler_settings_reject_unsafe_values(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
