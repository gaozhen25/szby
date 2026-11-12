from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.services.db_service import DBService
from app.db.models import (
    AccountRecord,
    CompetitorAccountRecord,
    CompetitorVideoRecord,
    ContentCreationRecord,
    DashboardAccountSnapshotRecord,
    DashboardContentSnapshotRecord,
    TaskRecord,
)
from tests.db_test_utils import db_session


def structured_report_payload() -> dict[str, object]:
    return {
        "competitors": "结构化竞品摘要",
        "prohibitedWords": "结构化合规摘要",
        "targetUsers": "结构化用户摘要",
        "hotContent": "结构化爆款摘要",
        "similarAccounts": [
            {
                "name": "通勤美妆研究所",
                "profileUrl": "https://www.xiaohongshu.com/user/profile/peer",
            }
        ],
        "complianceRules": [{"riskLevel": "high", "expression": "最有效"}],
        "targetUserProfile": {"summary": "一线城市通勤女性"},
        "hotContents": [{"title": "通勤底妆实测"}],
        "sourceMeta": {"platforms": ["小红书"]},
    }


def test_dashboard_uses_real_competitor_account_and_video_counts():
    with db_session() as session:
        now = datetime.now(UTC)
        session.add_all([
            CompetitorAccountRecord(
                id="ca_dashboard",
                account_id="acc1",
                user_id="u_001",
                platform="dy",
                profile_url="https://www.douyin.com/user/dashboard",
                next_refresh_at=now,
            ),
            CompetitorVideoRecord(
                id="cv_dashboard",
                account_id="acc1",
                user_id="u_001",
                platform="dy",
                content_url="https://www.douyin.com/video/dashboard",
                next_refresh_at=now,
            ),
        ])
        session.commit()

        dashboard = DBService(session).get_dashboard("u_001", "acc1")

        assert dashboard.competitorCount == 1
        assert dashboard.competitorPosts == 1


def test_create_account_initializes_an_empty_report_for_first_workflow():
    with db_session() as session:
        service = DBService(session)
        account = service.create_account(
            "u_001",
            "新账号",
            "咖啡\n探店",
            "获客",
            "普通号",
            account_links={"小红书": "https://example.test/account"},
        )

        report = service.get_report("u_001", account.id)

        assert report.competitors == ""
        assert report.prohibitedWords == ""
        assert report.targetUsers == ""
        assert report.hotContent == ""
        assert report.reportVersion == 0
        assert report.generatedAt is None


def test_create_account_accepts_platform_handles_without_profile_links():
    with db_session() as session:
        account = DBService(session).create_account(
            "u_001",
            "双平台账号",
            "咖啡探店",
            "获客",
            "普通号",
            platforms=["小红书", "抖音"],
            platform_accounts={"小红书": "red_123", "抖音": "douyin_456"},
        )

        assert account.accountLinks == {}
        assert account.platformAccounts == {
            "小红书": "red_123",
            "抖音": "douyin_456",
        }
        assert account.platformAccountIdentities == {}


def test_updating_platform_handle_invalidates_only_changed_identity_cache():
    with db_session() as session:
        service = DBService(session)
        account = service.create_account(
            "u_001",
            "双平台账号",
            "咖啡探店",
            "获客",
            "普通号",
            platforms=["小红书", "抖音"],
            platform_accounts={"小红书": "red_old", "抖音": "douyin_same"},
        )
        record = session.get(AccountRecord, account.id)
        record.platform_account_identities = {
            "小红书": {"input": "red_old", "userId": "xhs_user"},
            "抖音": {"input": "douyin_same", "userId": "dy_user"},
        }
        session.add_all(
            [
                DashboardAccountSnapshotRecord(
                    account_id=account.id,
                    platform=platform,
                    observed_date=date.today(),
                )
                for platform in ("小红书", "抖音")
            ]
        )
        session.add_all(
            [
                DashboardContentSnapshotRecord(
                    account_id=account.id,
                    platform=platform,
                    content_id=f"{platform}_content",
                    observed_date=date.today(),
                )
                for platform in ("小红书", "抖音")
            ]
        )
        session.commit()

        updated = service.update_account(
            "u_001",
            account.id,
            "双平台账号",
            "咖啡探店",
            "获客",
            "普通号",
            platforms=["小红书", "抖音"],
            platform_accounts={"小红书": "red_new", "抖音": "douyin_same"},
        )

        assert updated.platformAccountIdentities == {
            "抖音": {"input": "douyin_same", "userId": "dy_user"}
        }
        assert session.scalars(
            select(DashboardAccountSnapshotRecord.platform).where(
                DashboardAccountSnapshotRecord.account_id == account.id
            )
        ).all() == ["抖音"]
        assert session.scalars(
            select(DashboardContentSnapshotRecord.platform).where(
                DashboardContentSnapshotRecord.account_id == account.id
            )
        ).all() == ["抖音"]


def test_structured_report_defaults_and_atomic_replace():
    with db_session() as session:
        service = DBService(session)

        report = service.get_report("u_001", "acc1")
        assert report.similarAccounts == []
        assert report.complianceRules == []
        assert report.targetUserProfile == {}
        assert report.hotContents == []
        assert report.sourceMeta == {}
        assert report.reportVersion == 0
        assert report.generatedAt is None

        updated = service.replace_structured_report("u_001", "acc1", structured_report_payload())

        assert updated.competitors == "结构化竞品摘要"
        assert updated.prohibitedWords == "结构化合规摘要"
        assert updated.targetUsers == "结构化用户摘要"
        assert updated.hotContent == "结构化爆款摘要"
        assert updated.similarAccounts == [
            {
                "name": "通勤美妆研究所",
                "profileUrl": "https://www.xiaohongshu.com/user/profile/peer",
            }
        ]
        assert updated.complianceRules == [{"riskLevel": "high", "expression": "最有效"}]
        assert updated.targetUserProfile == {"summary": "一线城市通勤女性"}
        assert updated.hotContents == [{"title": "通勤底妆实测"}]
        assert updated.sourceMeta == {"platforms": ["小红书"]}
        assert updated.reportVersion == 1
        assert isinstance(updated.generatedAt, datetime)

        session.expire_all()
        reloaded = service.get_report("u_001", "acc1")
        assert reloaded.generatedAt is not None
        assert reloaded.generatedAt.utcoffset() == timedelta(0)

        replacement = structured_report_payload()
        replacement.update(
            {
                "similarAccounts": [],
                "complianceRules": [],
                "targetUserProfile": {},
                "hotContents": [],
                "sourceMeta": {},
            }
        )
        replaced = service.replace_structured_report("u_001", "acc1", replacement)
        assert replaced.similarAccounts == []
        assert replaced.complianceRules == []
        assert replaced.targetUserProfile == {}
        assert replaced.hotContents == []
        assert replaced.sourceMeta == {}
        assert replaced.reportVersion == 2


def test_structured_report_section_update_preserves_other_published_sections():
    with db_session() as session:
        service = DBService(session)
        original = service.replace_structured_report("u_001", "acc1", structured_report_payload())

        updated = service.update_structured_report_sections(
            "u_001",
            "acc1",
            {
                "targetUserProfile": {"summary": "重新生成的用户画像"},
                "targetUsers": "重新生成的用户摘要",
                "sourceMeta": {"platforms": ["抖音"], "sampleCount": 12},
            },
        )

        assert updated.targetUserProfile == {"summary": "重新生成的用户画像"}
        assert updated.targetUsers == "重新生成的用户摘要"
        assert updated.sourceMeta == {"platforms": ["抖音"], "sampleCount": 12}
        assert updated.similarAccounts == original.similarAccounts
        assert updated.complianceRules == original.complianceRules
        assert updated.hotContents == original.hotContents
        assert updated.reportVersion == original.reportVersion + 1


def test_manual_similar_accounts_survive_report_regeneration_and_generated_deletions():
    with db_session() as session:
        service = DBService(session)
        service.replace_structured_report("u_001", "acc1", structured_report_payload())

        configured = service.add_report_similar_account(
            "u_001",
            "acc1",
            {
                "name": "手动配置账号",
                "platform": "抖音",
                "profileUrl": "https://www.douyin.com/user/manual-peer?secret=removed",
                "similarityReason": "用户指定的长期对标账号",
                "avatarUrl": "https://example.test/manual-peer.png",
                "description": "公开简介",
                "followers": 12345,
                "contentCount": 67,
                "totalLikes": 89000,
                "ipLocation": "上海",
            },
        )

        assert [item["name"] for item in configured.similarAccounts] == [
            "手动配置账号",
            "通勤美妆研究所",
        ]
        manual = configured.similarAccounts[0]
        assert manual["profileUrl"] == "https://www.douyin.com/user/manual-peer"
        assert manual["creatorHash"].startswith("manual_")
        assert manual["avatarUrl"] == "https://example.test/manual-peer.png"
        assert manual["description"] == "公开简介"
        assert manual["metrics"] == {
            "fansCount": 12345,
            "worksCount": 67,
            "likedCount": 89000,
        }

        replacement = structured_report_payload()
        replacement["similarAccounts"] = [
            {
                "creatorHash": "generated_new",
                "name": "新一轮推荐账号",
                "platform": "小红书",
                "profileUrl": "https://www.xiaohongshu.com/user/profile/new-peer",
                "similarityReason": "新一轮公开证据",
            }
        ]
        regenerated = service.replace_structured_report("u_001", "acc1", replacement)
        assert [item["name"] for item in regenerated.similarAccounts] == [
            "手动配置账号",
            "新一轮推荐账号",
        ]

        without_generated = service.delete_report_similar_account(
            "u_001", "acc1", "generated_new"
        )
        assert [item["name"] for item in without_generated.similarAccounts] == ["手动配置账号"]

        without_manual = service.delete_report_similar_account(
            "u_001", "acc1", manual["creatorHash"]
        )
        assert without_manual.similarAccounts == []


def test_manual_similar_account_rejects_duplicates_and_mismatched_platform_urls():
    with db_session() as session:
        service = DBService(session)
        service.replace_structured_report("u_001", "acc1", structured_report_payload())

        with pytest.raises(ValueError, match="已存在"):
            service.add_report_similar_account(
                "u_001",
                "acc1",
                {
                    "name": "已有账号",
                    "platform": "小红书",
                    "profileUrl": "https://www.xiaohongshu.com/user/profile/peer?xsec_token=ignored",
                },
            )

        with pytest.raises(ValueError, match="有效的抖音"):
            service.add_report_similar_account(
                "u_001",
                "acc1",
                {
                    "name": "错误链接",
                    "platform": "抖音",
                    "profileUrl": "https://www.xiaohongshu.com/user/profile/wrong-platform",
                },
            )


def test_structured_report_section_update_rejects_unknown_or_empty_payloads():
    with db_session() as session:
        service = DBService(session)
        with pytest.raises(ValueError, match="不支持更新账号报告字段"):
            service.update_structured_report_sections(
                "u_001", "acc1", {"contentStrategy": {}}
            )
        with pytest.raises(ValueError, match="板块更新不能为空"):
            service.update_structured_report_sections(
                "u_001", "acc1", {"sourceMeta": {}}
            )


def test_replace_structured_report_rolls_back_all_fields_on_commit_failure(monkeypatch):
    with db_session() as session:
        service = DBService(session)
        original = service.get_report("u_001", "acc1")
        rollback_calls = 0
        real_rollback = session.rollback
        commit_error = RuntimeError("database unavailable")

        def fail_commit() -> None:
            raise commit_error

        def track_rollback() -> None:
            nonlocal rollback_calls
            rollback_calls += 1
            real_rollback()

        monkeypatch.setattr(session, "commit", fail_commit)
        monkeypatch.setattr(session, "rollback", track_rollback)

        with pytest.raises(RuntimeError, match="database unavailable") as exc_info:
            service.replace_structured_report("u_001", "acc1", structured_report_payload())

        session.expire_all()
        persisted = service.get_report("u_001", "acc1")
        assert exc_info.value is commit_error
        assert rollback_calls == 1
        assert persisted.competitors == original.competitors
        assert persisted.similarAccounts == []
        assert persisted.reportVersion == 0


def test_replace_structured_report_rolls_back_when_account_is_not_owned(monkeypatch):
    with db_session() as session:
        service = DBService(session)
        rollback_calls = 0
        real_rollback = session.rollback

        def track_rollback() -> None:
            nonlocal rollback_calls
            rollback_calls += 1
            real_rollback()

        monkeypatch.setattr(session, "rollback", track_rollback)

        with pytest.raises(StopIteration):
            service.replace_structured_report("u_002", "acc1", structured_report_payload())

        assert rollback_calls == 1


def test_replace_structured_report_rolls_back_when_payload_is_incomplete(monkeypatch):
    with db_session() as session:
        service = DBService(session)
        rollback_calls = 0
        real_rollback = session.rollback
        payload = structured_report_payload()
        del payload["sourceMeta"]

        def track_rollback() -> None:
            nonlocal rollback_calls
            rollback_calls += 1
            real_rollback()

        monkeypatch.setattr(session, "rollback", track_rollback)

        with pytest.raises(KeyError, match="sourceMeta"):
            service.replace_structured_report("u_001", "acc1", payload)

        assert rollback_calls == 1
        assert service.get_report("u_001", "acc1").reportVersion == 0


def test_workflow_store_delegates_report_replacement_to_db_service(monkeypatch):
    from app.services.workflow import workflow_store as workflow_store_module

    calls: list[tuple[object, str, str, dict[str, object]]] = []
    expected = object()

    class SessionContext:
        def __init__(self) -> None:
            self.session = object()

        def __enter__(self) -> object:
            return self.session

        def __exit__(self, *_args: object) -> None:
            return None

    context = SessionContext()

    class TrackingDBService:
        def __init__(self, session: object) -> None:
            self.session = session

        def replace_structured_report(self, user_id: str, account_id: str, payload: dict[str, object]) -> object:
            calls.append((self.session, user_id, account_id, payload))
            return expected

    monkeypatch.setattr(workflow_store_module, "DBService", TrackingDBService, raising=False)
    store = workflow_store_module.WorkflowStore(session_factory=lambda: context)
    payload = structured_report_payload()

    result = store.replace_account_report("u_001", "acc1", payload)

    assert result is expected
    assert calls == [(context.session, "u_001", "acc1", payload)]


def test_db_service_persists_workspace_changes():
    with db_session() as session:
        first = DBService(session)

        account = first.create_account(
            "u_001",
            "新品号",
            "新品测评",
            "涨粉",
            "普通号",
            account_links={"小红书": "https://example.test/account"},
        )
        task = first.create_task("u_001", account.id, "首条内容", "video", "抖音")
        material = first.create_material("u_001", account.id, "脚本.txt", "script", ["抖音"], "T")
        first.update_report_section("u_001", account.id, "competitors", "AI 竞品分析结果")

        second = DBService(session)

        assert any(item.id == account.id and item.name == "新品号" for item in second.list_accounts("u_001"))
        assert any(item.id == task.id and item.title == "首条内容" for item in second.list_tasks("u_001", account.id))
        assert any(item.id == material.id and item.name == "脚本.txt" for item in second.list_materials("u_001", account.id))
        assert second.get_report("u_001", account.id).competitors == "AI 竞品分析结果"


def test_list_tasks_caps_limit():
    with db_session() as session:
        service = DBService(session)
        account = service.create_account(
            "u_001",
            "新品号",
            "新品测评",
            "涨粉",
            "普通号",
            account_links={"小红书": "https://example.test/account"},
        )
        for index in range(105):
            service.create_task("u_001", account.id, f"任务 {index}", "image", "小红书")

        tasks = service.list_tasks("u_001", account.id, limit=1000)

        assert len(tasks) == 100


def test_duplicate_task_copies_creation_and_rebuilds_identity_references():
    with db_session() as session:
        service = DBService(session)
        account = service.create_account(
            "u_001",
            "流程复制账号",
            "验证流程复制",
            "复用内容",
            "普通号",
            account_links={"小红书": "https://example.test/account"},
        )
        source_creation = ContentCreationRecord(
            id="creation_source",
            account_id=account.id,
            user_id="u_001",
            title="夏日防晒实测",
            content_type="image",
            target_platform="小红书",
            body="正文",
            hashtags=["防晒"],
            assets=[{"url": "https://cdn.test/cover.png", "workflowTaskId": "task_source"}],
            creation_state={
                "activeTaskId": "task_source",
                "sourceCreationId": "creation_source",
                "publish": {"status": "completed"},
                "publishHistory": [{"status": "completed"}],
            },
        )
        source_task = TaskRecord(
            id="task_source",
            account_id=account.id,
            creation_id=source_creation.id,
            title="夏日防晒实测",
            content_type="image",
            status="editing",
            updated="昨天",
            target_platform="小红书",
            body="正文",
            tags=["防晒"],
            assignee="小周",
            due_date="2026-08-01T10:00:00Z",
            priority="high",
            handoff_note="保持原调性",
        )
        session.add_all([source_creation, source_task])
        session.commit()

        duplicate = service.duplicate_task("u_001", account.id, source_task.id)
        copied_creation = session.get(ContentCreationRecord, duplicate.creationId)

        assert duplicate.id != source_task.id
        assert duplicate.creationId != source_creation.id
        assert duplicate.title == source_task.title
        assert duplicate.status == source_task.status
        assert duplicate.tags == source_task.tags
        assert duplicate.assignee == source_task.assignee
        assert duplicate.dueDate == source_task.due_date
        assert duplicate.priority == source_task.priority
        assert duplicate.handoffNote == source_task.handoff_note
        assert copied_creation is not None
        assert copied_creation.assets[0]["workflowTaskId"] == duplicate.id
        assert copied_creation.creation_state == {
            "activeTaskId": duplicate.id,
            "sourceCreationId": duplicate.creationId,
        }


def test_duplicate_task_rejects_task_from_another_account():
    with db_session() as session:
        service = DBService(session)
        source = service.create_account(
            "u_001", "来源账号", "", "", "普通号", account_links={"小红书": "https://example.test/source"}
        )
        target = service.create_account(
            "u_001", "目标账号", "", "", "普通号", account_links={"小红书": "https://example.test/target"}
        )
        task = service.create_task("u_001", source.id, "来源流程", "image", "小红书")

        with pytest.raises(StopIteration):
            service.duplicate_task("u_001", target.id, task.id)
