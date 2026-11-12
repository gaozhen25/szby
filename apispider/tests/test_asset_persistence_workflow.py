import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.init_db import init_database
from app.db.models import (
    ContentCreationRecord,
    ExtractHistoryRecord,
    MaterialRecord,
    WorkflowRecord,
)
from app.services.extract_service.asset_persistence import AssetPersistenceResult
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.workflow.workflow_store import WorkflowStore
from app.services.workflow.workflows.base import WorkflowRegister

SOURCE_IMAGE = "https://source.example.test/cover.webp"
SOURCE_VIDEO = "https://source.example.test/video.mp4"
OSS_IMAGE = "https://oss.example.test/extract/cover.webp"
OSS_VIDEO = "https://oss.example.test/extract/video.mp4"
GENERATED_IMAGE = "https://oss.example.test/generated/final.png"


class FakePersistenceService:
    def __init__(self, result):
        self.result = result
        self.snapshots = []

    def persist(self, snapshot):
        self.snapshots.append(snapshot)
        return self.result


def _media(url, kind, status="external"):
    return {
        "sourceUrl": url,
        "url": url,
        "contentType": "",
        "kind": kind,
        "storageStatus": status,
    }


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_database(engine)
    return engine, sessionmaker(bind=engine)


def _seed(session_factory):
    now = datetime.now(UTC)
    images = [_media(SOURCE_IMAGE, "image")]
    videos = [_media(SOURCE_VIDEO, "video")]
    with session_factory() as session:
        session.add(
            ExtractHistoryRecord(
                id="eh_workflow",
                user_id="u_001",
                account_id="acc1",
                creation_id="creation_workflow",
                url="https://v.douyin.com/source/",
                resolved_url="https://www.douyin.com/video/1",
                platform="douyin",
                content_type="mixed",
                title="测试解析",
                description="",
                hashtags=[],
                images=images,
                videos=videos,
                cover=SOURCE_IMAGE,
                raw={},
                persistence_status="pending",
                persistence_job_id="wf_persist",
                persistence_error="",
                media_url_map={},
                created_at=now,
            )
        )
        session.add(
            ContentCreationRecord(
                id="creation_workflow",
                account_id="acc1",
                user_id="u_001",
                topic_id="",
                topic_title="测试解析",
                title="测试创作",
                content_type="video",
                target_platform="抖音",
                body="正文",
                assets=[
                    {"url": GENERATED_IMAGE, "kind": "image", "assetType": "generated"},
                    *images,
                    *videos,
                ],
                cover={"fileId": "", "url": SOURCE_IMAGE},
                creation_state={
                    "linkReference": {"images": images, "videos": videos, "cover": SOURCE_IMAGE},
                    "assetPersistence": {"jobId": "wf_persist", "status": "pending"},
                },
            )
        )
        session.add(
            MaterialRecord(
                id="material_workflow",
                account_id="acc1",
                name="测试脚本",
                material_type="script",
                tags=[],
                material_date="2026-07-14",
                thumb="📝",
                assets=[*images, *videos],
            )
        )
        session.add(
            WorkflowRecord(
                id="wf_persist",
                account_id="acc1",
                user_id="u_001",
                type="asset_persistence",
                status="pending",
                creation_id="creation_workflow",
                input_payload={"historyId": "eh_workflow", "materialIds": ["material_workflow"]},
                result_payload={},
            )
        )
        session.add(
            WorkflowRecord(
                id="wf_video_analysis",
                account_id="acc1",
                user_id="u_001",
                type="video_analysis",
                status="completed",
                creation_id="creation_workflow",
                video_url=SOURCE_VIDEO,
                cover_url=SOURCE_IMAGE,
                input_payload={"images": images, "videos": videos},
                result_payload={},
            )
        )
        session.commit()


def _completed_result():
    return AssetPersistenceResult(
        status="completed",
        assets=[
            {**_media(SOURCE_IMAGE, "image", "persisted"), "url": OSS_IMAGE, "contentType": "image/webp"},
            {**_media(SOURCE_VIDEO, "video", "persisted"), "url": OSS_VIDEO, "contentType": "video/mp4"},
        ],
        url_map={SOURCE_IMAGE: OSS_IMAGE, SOURCE_VIDEO: OSS_VIDEO},
        retry_count=0,
    )


def test_non_ai_asset_workflow_runs_without_ai_token_and_updates_scoped_records():
    engine, session_factory = _database()
    _seed(session_factory)
    persistence_service = FakePersistenceService(_completed_result())
    scheduler = WorkflowScheduler(
        ai_service=SimpleNamespace(token=""),
        store=WorkflowStore(session_factory=session_factory),
        use_default_concurrency=False,
    )

    workflow_class = WorkflowRegister.get("asset_persistence")
    asyncio.run(
        scheduler._execute(
            workflow_class,
            "asset_persistence",
            "wf_persist",
            {"_persistence_service": persistence_service},
        )
    )

    with Session(engine) as session:
        workflow = session.get(WorkflowRecord, "wf_persist")
        history = session.get(ExtractHistoryRecord, "eh_workflow")
        creation = session.get(ContentCreationRecord, "creation_workflow")
        material = session.get(MaterialRecord, "material_workflow")
        video_analysis = session.get(WorkflowRecord, "wf_video_analysis")
        assert workflow.status == "completed"
        assert workflow.result_payload["persistenceStatus"] == "completed"
        assert history.persistence_status == "completed"
        assert history.media_url_map == {SOURCE_IMAGE: OSS_IMAGE, SOURCE_VIDEO: OSS_VIDEO}
        assert [item["url"] for item in creation.assets] == [GENERATED_IMAGE, OSS_IMAGE, OSS_VIDEO]
        assert creation.creation_state["assetPersistence"]["status"] == "completed"
        assert creation.creation_state["linkReference"]["cover"] == OSS_IMAGE
        assert [item["url"] for item in material.assets] == [OSS_IMAGE, OSS_VIDEO]
        assert video_analysis.video_url == OSS_VIDEO
        assert video_analysis.cover_url == OSS_IMAGE
    assert persistence_service.snapshots[0].id == "eh_workflow"
    engine.dispose()


def test_asset_workflow_records_fallback_and_keeps_source_urls():
    engine, session_factory = _database()
    _seed(session_factory)
    fallback = AssetPersistenceResult(
        status="fallback",
        assets=[_media(SOURCE_IMAGE, "image"), _media(SOURCE_VIDEO, "video")],
        url_map={SOURCE_IMAGE: SOURCE_IMAGE, SOURCE_VIDEO: SOURCE_VIDEO},
        retry_count=1,
        error="two rounds failed",
    )
    scheduler = WorkflowScheduler(
        ai_service=SimpleNamespace(token=""),
        store=WorkflowStore(session_factory=session_factory),
        use_default_concurrency=False,
    )

    asyncio.run(
        scheduler._execute(
            WorkflowRegister.get("asset_persistence"),
            "asset_persistence",
            "wf_persist",
            {"_persistence_service": FakePersistenceService(fallback)},
        )
    )

    with Session(engine) as session:
        workflow = session.get(WorkflowRecord, "wf_persist")
        history = session.get(ExtractHistoryRecord, "eh_workflow")
        creation = session.get(ContentCreationRecord, "creation_workflow")
        assert workflow.status == "completed"
        assert workflow.result_payload["persistenceStatus"] == "fallback"
        assert history.persistence_status == "fallback"
        assert history.persistence_error == "two rounds failed"
        assert [item["url"] for item in creation.assets] == [GENERATED_IMAGE, SOURCE_IMAGE, SOURCE_VIDEO]
        assert creation.creation_state["assetPersistence"]["status"] == "fallback"
    engine.dispose()
