import asyncio
import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import (
    AccountRecord,
    KnowledgeBaseRecord,
    TopicRecord,
    UserRecord,
    WorkflowRecord,
    WorkflowStepRecord,
)
from app.services.workflow import WorkflowService
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.workflow.workflow_store import WorkflowStore
from app.services.workflow.workflows.base import WorkflowRegister
from app.services.workflow.workflows.generation_helpers import GENERATION_JOB_TYPES
from app.services.workflow.workflows.video_script_contract import (
    ALLOWED_CONTENT_GOALS,
    ALLOWED_DURATIONS,
    ALLOWED_TONE_STYLES,
    ALLOWED_VIDEO_FORMATS,
    APPLIED_PRINCIPLES,
    normalize_video_script_result,
)
from app.services.workflow.workflows.video_script_prompts import (
    build_video_script_system_prompt,
    build_video_script_user_prompt,
)


CONTEXT = {
    "account": {
        "name": "星耀职场",
        "industry": "职业教育",
        "purpose": "获取精准咨询",
        "targetAudience": "工作三年仍没有晋升方向的职场人",
        "productService": "职业规划咨询",
    },
    "knowledgeContext": "仅可使用：提供一对一职业规划咨询。",
    "topic": {"title": "为什么努力工作却总得不到晋升"},
}
PREFERENCES = {
    "durationSeconds": 30,
    "contentGoal": "acquisition",
    "videoFormat": "list_talking_head",
    "toneStyle": "professional",
}

DIRECTOR_FIELDS = {
    "purpose": "用痛点建立注意力",
    "visual": "人物近景直视镜头",
    "shotSizeCamera": "近景 / 平视机位",
    "shootingTechnique": "固定机位，结尾轻推",
    "subtitle": "努力却没晋升？",
    "bgmSound": "轻快鼓点，问题句加入提示音",
}

VALID_RAW = {
    "title": "努力工作却不晋升，可能缺的是这三步",
    "contentGoal": "acquisition",
    "contentGoalReason": "用具体问题吸引有职业规划需求的人咨询",
    "targetAudience": "工作三年仍没有晋升方向的职场人",
    "coreNeed": "找到晋升受阻的原因",
    "coreSolution": "按目标、反馈和复盘三步检查",
    "draftScript": ["开场指出痛点", "给出三步清单", "邀请进一步咨询"],
    "finalScript": [
        {"timeRange": "00:00-00:05", "text": "努力工作却一直没晋升？先别只怪自己。", **DIRECTOR_FIELDS},
        {"timeRange": "00:05-00:15", "text": "第一看目标是否清楚，第二看反馈是否及时。", **DIRECTOR_FIELDS},
        {"timeRange": "00:15-00:25", "text": "第三看每次复盘有没有变成下一步行动。", **DIRECTOR_FIELDS},
        {"timeRange": "00:25-00:30", "text": "想系统梳理方向，可以预约职业规划咨询。", **DIRECTOR_FIELDS},
    ],
    "publishCopy": "晋升卡住时，先检查目标、反馈和复盘。",
    "hashtags": ["#职场成长", "职业规划", "#职场成长", ""],
    "bgmSuggestion": "节奏清晰、不过度煽情的轻音乐",
    "hookSuggestion": "前 3 秒直接说出晋升痛点",
    "rhythmNote": "三段清单逐步加速，结尾放慢",
    "callToAction": "预约职业规划咨询",
}

UNCOVERED_RAW = {
    **VALID_RAW,
    "finalScript": [
        {"timeRange": "00:00-00:05", "text": "开场", **DIRECTOR_FIELDS},
        {"timeRange": "00:10-01:00", "text": "中间缺了五秒", **DIRECTOR_FIELDS},
    ],
}


def test_manual_prompt_contains_required_principles():
    prompt = build_video_script_user_prompt(CONTEXT, PREFERENCES)
    for text in (
        "唯一核心目的",
        "具体种子用户",
        "需求",
        "解决方案",
        "清单式原子结构",
        "3-5 秒",
        "不得编造",
        "行动入口",
    ):
        assert text in prompt
    assert "IP定位与内容支点落地手册" in prompt
    assert "短视频选题结构与标签化创作落地手册" in prompt
    assert "短视频内容分类与客户新账号落地手册" in prompt


def test_prompt_serializes_inputs_and_exact_json_shape():
    system_prompt = build_video_script_system_prompt()
    user_prompt = build_video_script_user_prompt(CONTEXT, PREFERENCES)

    assert "只输出一个 JSON 对象" in system_prompt
    assert "星耀职场" in user_prompt
    assert "一对一职业规划咨询" in user_prompt
    assert "为什么努力工作却总得不到晋升" in user_prompt
    assert '"durationSeconds": 30' in user_prompt
    for key in VALID_RAW:
        assert f'"{key}"' in user_prompt


def test_prompt_requires_manual_backed_director_fields_to_align_per_segment():
    user_prompt = build_video_script_user_prompt(CONTEXT, PREFERENCES)

    for field in ("narration", *DIRECTOR_FIELDS):
        assert f'"{field}"' in user_prompt
    assert "逐段对齐" in user_prompt


@pytest.mark.parametrize(
    ("duration_seconds", "expected_end"),
    [(30, "00:30"), (60, "01:00"), (90, "01:30"), (180, "03:00")],
)
def test_prompt_example_ends_at_requested_duration(duration_seconds, expected_end):
    preferences = {**PREFERENCES, "durationSeconds": duration_seconds}

    prompt = build_video_script_user_prompt(CONTEXT, preferences)

    assert f'"timeRange": "00:05-{expected_end}"' in prompt
    if duration_seconds != 30:
        assert '"timeRange": "00:05-00:30"' not in prompt


def test_allowed_value_constants_are_exact():
    assert ALLOWED_DURATIONS == {30, 60, 90, 180}
    assert ALLOWED_CONTENT_GOALS == {"auto", "exposure", "acquisition", "conversion", "persona"}
    assert ALLOWED_VIDEO_FORMATS == {
        "auto",
        "list_talking_head",
        "knowledge_explainer",
        "vlog_workday",
        "story_case",
        "product_service_showcase",
        "interview_dialogue",
    }
    assert ALLOWED_TONE_STYLES == {
        "auto",
        "professional",
        "conversational",
        "sharp",
        "humorous",
        "empathetic_story",
    }
    assert APPLIED_PRINCIPLES == [
        "single_goal",
        "seed_user",
        "need_solution",
        "atomic_list",
        "three_second_hook",
        "real_resources",
        "no_fabrication",
        "goal_cta",
    ]


def test_normalize_video_script_result_adds_backend_metadata():
    result = normalize_video_script_result(VALID_RAW, duration_seconds=30)

    assert result["schemaVersion"] == 1
    assert result["manualVersion"] == "2026-07-10.v1"
    assert "single_goal" in result["appliedPrinciples"]
    assert result["finalScript"][0]["timeRange"] == "00:00-00:05"
    assert result["hashtags"] == ["#职场成长", "#职业规划"]


def test_normalize_video_script_result_preserves_complete_director_fields_and_text_fallbacks():
    raw = {
        **VALID_RAW,
        "finalScript": [
            {
                "timeRange": "00:00-00:05",
                "text": "兼容口播",
                **DIRECTOR_FIELDS,
            },
            {
                "timeRange": "00:05-00:30",
                "narration": "标准口播",
                **DIRECTOR_FIELDS,
            },
        ],
    }

    result = normalize_video_script_result(raw, duration_seconds=30)

    assert result["finalScript"] == [
        {
            "timeRange": "00:00-00:05",
            "text": "兼容口播",
            "narration": "兼容口播",
            **DIRECTOR_FIELDS,
        },
        {
            "timeRange": "00:05-00:30",
            "text": "标准口播",
            "narration": "标准口播",
            **DIRECTOR_FIELDS,
        },
    ]


@pytest.mark.parametrize("missing_field", list(DIRECTOR_FIELDS))
def test_normalize_video_script_result_rejects_missing_director_fields(missing_field):
    segment = {
        "timeRange": "00:00-00:30",
        "narration": "完整口播",
        **DIRECTOR_FIELDS,
    }
    segment.pop(missing_field)

    with pytest.raises(ValueError, match=missing_field):
        normalize_video_script_result(
            {**VALID_RAW, "finalScript": [segment]},
            duration_seconds=30,
        )


def test_normalize_video_script_result_rejects_structured_director_text():
    segment = {
        "timeRange": "00:00-00:30",
        "narration": "完整口播",
        **DIRECTOR_FIELDS,
        "shotSizeCamera": {"shot": "近景"},
    }

    with pytest.raises(ValueError, match="shotSizeCamera"):
        normalize_video_script_result(
            {**VALID_RAW, "finalScript": [segment]},
            duration_seconds=30,
        )


def test_normalize_video_script_result_accepts_fenced_json_object():
    raw = f"```json\n{json.dumps(VALID_RAW, ensure_ascii=False)}\n```"

    result = normalize_video_script_result(raw, duration_seconds=30)

    assert result["title"] == VALID_RAW["title"]


@pytest.mark.parametrize("raw", ["这是一段原始文案", "[]", [VALID_RAW]])
def test_normalize_video_script_result_rejects_non_object_json(raw):
    with pytest.raises(ValueError, match="格式异常"):
        normalize_video_script_result(raw, duration_seconds=30)


def test_normalize_video_script_result_rejects_uncovered_duration():
    with pytest.raises(ValueError, match="cover requested duration"):
        normalize_video_script_result(UNCOVERED_RAW, duration_seconds=60)


def test_normalize_video_script_result_rejects_invalid_goal():
    with pytest.raises(ValueError, match="无效内容目的"):
        normalize_video_script_result({**VALID_RAW, "contentGoal": "auto"}, duration_seconds=30)


def test_normalize_video_script_result_rejects_missing_required_text():
    with pytest.raises(ValueError, match="publishCopy"):
        normalize_video_script_result({**VALID_RAW, "publishCopy": ""}, duration_seconds=30)


def test_normalize_video_script_result_rejects_empty_script_line():
    with pytest.raises(ValueError, match="draftScript"):
        normalize_video_script_result({**VALID_RAW, "draftScript": []}, duration_seconds=30)


def test_normalize_video_script_result_rejects_overlapping_time_ranges():
    raw = {
        **VALID_RAW,
        "finalScript": [
            {"timeRange": "00:00-00:10", "text": "开场", **DIRECTOR_FIELDS},
            {"timeRange": "00:09-00:30", "text": "时间重叠", **DIRECTOR_FIELDS},
        ],
    }

    with pytest.raises(ValueError, match="cover requested duration"):
        normalize_video_script_result(raw, duration_seconds=30)


def test_normalize_video_script_result_rejects_unsupported_duration():
    with pytest.raises(ValueError, match="unsupported duration"):
        normalize_video_script_result(VALID_RAW, duration_seconds=45)


def _video_workflow_database():
    active_transactions: set[int] = set()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "begin")
    def _track_begin(connection):  # noqa: ANN001
        active_transactions.add(id(connection))

    @event.listens_for(engine, "commit")
    @event.listens_for(engine, "rollback")
    def _track_end(connection):  # noqa: ANN001
        active_transactions.discard(id(connection))

    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine), active_transactions


def _seed_video_workflow(session_factory) -> None:  # noqa: ANN001
    with session_factory() as session:
        session.add(
            UserRecord(
                id="video-user",
                email="video-user@example.test",
                password_hash="not-used",
                nickname="Video User",
                status="active",
            )
        )
        session.add(
            KnowledgeBaseRecord(
                id="video-kb",
                user_id="video-user",
                name="职业规划知识库",
                product_name="职业规划咨询",
                product_intro="提供一对一职业规划咨询。",
                brand_story="创始人曾服务一千名客户。",
                price="首次咨询 299 元",
                logo_url="https://cdn.example.test/disabled-logo.png",
                image_materials=["https://cdn.example.test/disabled-material.png"],
                contact_info="VX: disabled-contact",
                website_url="https://career.example.test",
                enabled_fields={
                    "productIntro": True,
                    "brandStory": False,
                    "price": True,
                    "logoUrl": False,
                    "imageMaterials": False,
                    "contactInfo": False,
                    "websiteUrl": True,
                },
                status="active",
            )
        )
        session.add(
            AccountRecord(
                id="video-account",
                user_id="video-user",
                name="星耀职场",
                avatar="星",
                account_type="专业号",
                platform="小红书",
                platforms=["小红书", "抖音"],
                description="分享可执行的职场成长方法",
                purpose="获取精准咨询",
                industry="职业教育",
                product_service="职业规划咨询",
                target_city="上海",
                target_audience="工作三年仍没有晋升方向的职场人",
                conversion_goal="预约职业规划咨询",
                knowledge_base_id="video-kb",
                status="active",
            )
        )
        session.add(
            TopicRecord(
                id="video-account_video-topic",
                account_id="video-account",
                title="为什么努力工作却总得不到晋升",
                source="AI推荐",
                category="职场成长",
                content_type="video",
                reason="适合用三步清单解释晋升阻力",
                platforms=["小红书", "抖音"],
                sort_order=1,
            )
        )
        session.add(
            WorkflowRecord(
                id="video-script-job",
                account_id="video-account",
                user_id="video-user",
                type="video_script",
                status="pending",
                target_platform="小红书",
                topic_title="为什么努力工作却总得不到晋升",
                input_payload={
                    "topicId": "video-topic",
                    "targetPlatform": "小红书",
                    **PREFERENCES,
                    "customRequirements": "结尾自然邀请咨询",
                },
            )
        )
        session.commit()


class _TrackingWorkflowStore(WorkflowStore):
    def __init__(self, session_factory):  # noqa: ANN001
        super().__init__(session_factory=session_factory)
        self.progress_stages: list[tuple[int, str | None]] = []

    def update_progress(self, workflow_id, *, progress, current_stage=None, **kwargs):  # noqa: ANN001
        self.progress_stages.append((progress, current_stage))
        return super().update_progress(
            workflow_id,
            progress=progress,
            current_stage=current_stage,
            **kwargs,
        )


class _VideoScriptAIService:
    token = "test-token"

    def __init__(self, response, active_transactions):  # noqa: ANN001
        self.response = response
        self.active_transactions = active_transactions
        self.calls: list[dict[str, object]] = []

    async def chat_completion(self, messages, system_prompt=None, temperature=0.7):  # noqa: ANN001
        assert not self.active_transactions, "database transaction remained open during AI call"
        self.calls.append(
            {
                "messages": messages,
                "system_prompt": system_prompt,
                "temperature": temperature,
            }
        )
        return self.response


def test_video_script_context_loads_owned_video_topic_and_enabled_knowledge_fields():
    engine, session_factory, _active_transactions = _video_workflow_database()
    _seed_video_workflow(session_factory)

    context = WorkflowStore(session_factory=session_factory).video_script_context(
        "video-user",
        "video-account",
        "video-topic",
    )

    assert context["account"]["name"] == "星耀职场"
    assert context["account"]["platforms"] == ["小红书", "抖音"]
    assert context["topic"] == {
        "id": "video-topic",
        "title": "为什么努力工作却总得不到晋升",
        "category": "职场成长",
        "reason": "适合用三步清单解释晋升阻力",
        "platforms": ["小红书", "抖音"],
    }
    assert context["knowledgeBaseUsed"] is True
    assert "职业规划咨询" in context["knowledgeContext"]
    assert "首次咨询 299 元" in context["knowledgeContext"]
    assert "https://career.example.test" in context["knowledgeContext"]
    assert "创始人曾服务一千名客户" not in context["knowledgeContext"]
    assert "disabled-logo" not in context["knowledgeContext"]
    assert "disabled-material" not in context["knowledgeContext"]
    assert "disabled-contact" not in context["knowledgeContext"]
    engine.dispose()


def test_video_script_workflow_is_registered_persists_one_step_and_has_no_open_ai_transaction():
    engine, session_factory, active_transactions = _video_workflow_database()
    _seed_video_workflow(session_factory)
    store = _TrackingWorkflowStore(session_factory)
    ai_service = _VideoScriptAIService(json.dumps(VALID_RAW, ensure_ascii=False), active_transactions)
    scheduler = WorkflowScheduler(
        ai_service=ai_service,
        store=store,
        use_default_concurrency=False,
    )

    workflow_class = WorkflowRegister.get("video_script")
    asyncio.run(scheduler._execute(workflow_class, "video_script", "video-script-job", {}))

    with session_factory() as session:
        workflow = session.get(WorkflowRecord, "video-script-job")
        step = (
            session.query(WorkflowStepRecord)
            .filter(WorkflowStepRecord.workflow_id == "video-script-job")
            .one()
        )
        listed_jobs = WorkflowService(session).list_jobs("video-user", "video-account")

        assert workflow is not None
        assert workflow.status == "completed"
        assert workflow.result_payload["schemaVersion"] == 1
        assert workflow.result_payload["manualVersion"] == "2026-07-10.v1"
        assert workflow.result_payload["title"] == VALID_RAW["title"]
        assert step.type == "video_script_generation"
        assert step.status == "completed"
        assert step.result_payload == workflow.result_payload
        assert [job.id for job in listed_jobs] == ["video-script-job"]

    assert workflow_class.type == "video_script"
    assert "video_script" in GENERATION_JOB_TYPES
    assert store.progress_stages == [
        (10, "context_loading"),
        (25, "prompt_building"),
        (40, "ai_generation"),
        (80, "normalization"),
        (100, "completed"),
    ]
    assert len(ai_service.calls) == 1
    assert ai_service.calls[0]["temperature"] == 0.7
    prompt = str(ai_service.calls[0]["messages"][0]["content"])
    assert "职业规划咨询" in prompt
    assert "创始人曾服务一千名客户" not in prompt
    engine.dispose()


def test_video_script_workflow_marks_its_single_step_failed_on_invalid_ai_result():
    engine, session_factory, active_transactions = _video_workflow_database()
    _seed_video_workflow(session_factory)
    ai_service = _VideoScriptAIService("not-json", active_transactions)
    scheduler = WorkflowScheduler(
        ai_service=ai_service,
        store=WorkflowStore(session_factory=session_factory),
        use_default_concurrency=False,
    )

    asyncio.run(
        scheduler._execute(
            WorkflowRegister.get("video_script"),
            "video_script",
            "video-script-job",
            {},
        )
    )

    with session_factory() as session:
        workflow = session.get(WorkflowRecord, "video-script-job")
        step = (
            session.query(WorkflowStepRecord)
            .filter(WorkflowStepRecord.workflow_id == "video-script-job")
            .one()
        )
        assert workflow is not None
        assert workflow.status == "failed"
        assert step.status == "failed"
        assert "格式异常" in step.error
    engine.dispose()
