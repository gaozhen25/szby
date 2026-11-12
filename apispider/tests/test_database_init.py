import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.init_db import init_database
from app.db.models import ExtractHistoryRecord, GenerationAssetRecord, MaterialRecord, WorkflowRecord


def _sqlite_engine_with_foreign_keys():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):  # noqa: ARG001
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def _workflow(workflow_id: str, account_id: str = "acc1", source_prompt_workflow_id: str | None = None) -> WorkflowRecord:
    input_payload = {}
    if source_prompt_workflow_id:
        input_payload["sourcePromptWorkflowId"] = source_prompt_workflow_id
    return WorkflowRecord(
        id=workflow_id,
        account_id=account_id,
        user_id="u_001",
        type="image",
        status="pending",
        target_platform="小红书",
        copy_text="",
        prompt="Generate an image",
        requested_count=1,
        error="",
        input_payload=input_payload,
        result_payload={},
    )


def _asset(asset_id: str, workflow_id: str, account_id: str = "acc1") -> GenerationAssetRecord:
    return GenerationAssetRecord(
        id=asset_id,
        workflow_id=workflow_id,
        account_id=account_id,
        asset_type="image",
        file_name=f"{asset_id}.png",
        mime_type="image/png",
        storage_key=f"generated/{asset_id}.png",
        url=f"https://example.test/{asset_id}.png",
        status="ready",
        analysis="",
        error="",
        meta={},
    )


def test_init_database_creates_core_tables_and_seeds_demo_user():
    engine = create_engine("sqlite:///:memory:")

    init_database(engine)

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert {
        "users",
        "accounts",
        "account_quotas",
        "workflows",
        "workflow_steps",
        "generation_assets",
    }.issubset(tables)

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT email, nickname FROM users WHERE email = 'demo@starx.ai'")
        ).mappings().first()

    assert row is not None
    assert row["nickname"] == "Demo User"


def test_workflow_delete_removes_assets():
    engine = _sqlite_engine_with_foreign_keys()
    init_database(engine)

    with Session(engine) as session:
        workflow = _workflow("workflow_delete")
        workflow.assets = [_asset("asset_delete_1", "workflow_delete"), _asset("asset_delete_2", "workflow_delete")]
        session.add(workflow)
        session.commit()

        session.delete(workflow)
        session.commit()

        assert session.query(GenerationAssetRecord).filter_by(workflow_id="workflow_delete").count() == 0


def test_source_prompt_workflow_id_is_payload_not_parent_relationship():
    engine = _sqlite_engine_with_foreign_keys()
    init_database(engine)

    with Session(engine) as session:
        parent = _workflow("workflow_prompt")
        child = _workflow("workflow_image", source_prompt_workflow_id="workflow_prompt")
        session.add_all([parent, child])
        session.commit()

        session.refresh(child)
        assert child.parent_job_id is None
        assert child.input_payload["sourcePromptWorkflowId"] == parent.id


def test_generation_asset_account_must_match_workflow_account():
    engine = _sqlite_engine_with_foreign_keys()
    init_database(engine)

    with Session(engine) as session:
        session.add(_workflow("workflow_acc1", account_id="acc1"))
        session.commit()

        session.add(_asset("asset_wrong_account", "workflow_acc1", account_id="acc2"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_extract_history_and_material_asset_persistence_defaults():
    engine = create_engine("sqlite:///:memory:")
    init_database(engine)

    with Session(engine) as session:
        history = ExtractHistoryRecord(
            id="eh_defaults",
            user_id="u_001",
            account_id="acc1",
            url="https://example.test/post",
            resolved_url="https://example.test/post",
            platform="rednote",
            content_type="mixed",
            title="",
            description="",
            hashtags=[],
            images=[],
            videos=[],
            cover="",
            raw={},
        )
        material = MaterialRecord(
            id="m_defaults",
            account_id="acc1",
            name="脚本",
            material_type="script",
            tags=[],
            material_date="2026-07-14",
            thumb="📝",
        )
        session.add_all([history, material])
        session.commit()
        session.refresh(history)
        session.refresh(material)

        assert history.persistence_status == "external"
        assert history.persistence_job_id is None
        assert history.persistence_error == ""
        assert history.media_url_map == {}
        assert material.assets == []
