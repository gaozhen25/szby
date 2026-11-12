from datetime import UTC, datetime
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_service
from app.api.routes.topics import get_topic_refresh_scheduler, get_topic_workflow_service
from app.db.models import (
    AccountRecord,
    FavoriteTopicRecord,
    KnowledgeBaseRecord,
    ReportRecord,
    TopicRecord,
    WorkflowRecord,
    WorkflowStepRecord,
)
from app.main import app
from app.services.workflow import WorkflowService
from app.services.db_service import DBService
from app.services.workflow.workflows.topic_recommendation import (
    build_topic_recommendation_system_prompt,
    build_topic_recommendation_user_prompt,
    normalize_recommended_topics,
)
from app.services.workflow.workflow_store import WorkflowStore
from tests.db_test_utils import db_session


def _auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": "demo@starx.ai", "password": "demo123"})
    token = login.json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


def test_topics_response_includes_recommendation_fields():
    with db_session() as session:
        first = session.get(TopicRecord, "acc1_t1")
        first.reason = "通勤妆和账号定位高度匹配"
        first.platforms = ["小红书"]
        first.sort_order = 2
        first.batch_id = "wf_topic_generated"
        session.commit()

        app.dependency_overrides[get_service] = lambda: DBService(session)
        try:
            client = TestClient(app)
            headers = _auth_headers(client)

            response = client.get("/api/v1/accounts/acc1/topics", headers=headers)

            assert response.status_code == 200
            payload = response.json()
            topic = next(item for item in payload if item["id"] == "t1")
            assert topic["reason"] == "通勤妆和账号定位高度匹配"
            assert topic["platforms"] == ["小红书"]
        finally:
            app.dependency_overrides.clear()


def test_list_topics_orders_by_sort_order_then_id():
    with db_session() as session:
        session.get(TopicRecord, "acc1_t1").sort_order = 1
        session.get(TopicRecord, "acc1_t1").batch_id = "wf_topic_generated"
        session.get(TopicRecord, "acc1_t2").sort_order = 0
        session.get(TopicRecord, "acc1_t2").batch_id = "wf_topic_generated"
        session.get(TopicRecord, "acc1_t3").sort_order = 1
        session.get(TopicRecord, "acc1_t3").batch_id = "wf_topic_generated"
        session.commit()

        service = DBService(session)

        topics = service.list_topics("u_001", "acc1")

        assert [topic.id for topic in topics] == ["t2", "t1", "t3"]


def test_list_topics_is_empty_before_first_topic_generation():
    with db_session() as session:
        service = DBService(session)

        topics = service.list_topics("u_001", "acc1")

        assert topics == []


def test_refresh_topics_updates_timestamp_and_preserves_marker_behavior():
    with db_session() as session:
        before = datetime(2026, 1, 1)
        first = session.get(TopicRecord, "acc1_t1")
        second = session.get(TopicRecord, "acc1_t2")
        first.title = "早八通勤妆5分钟搞定"
        second.title = "黄皮显白口红合集推荐 ✨"
        first.updated_at = before
        second.updated_at = before
        session.commit()

        service = DBService(session)

        topics = service.refresh_topics("u_001", "acc1")
        session.refresh(first)
        session.refresh(second)

        assert next(topic for topic in topics if topic.id == "t1").title == "早八通勤妆5分钟搞定 ✨"
        assert next(topic for topic in topics if topic.id == "t2").title == "黄皮显白口红合集推荐 ✨"
        assert first.updated_at > before
        assert second.updated_at > before


def test_favorite_topic_snapshot_survives_recommendation_replacement_and_can_create():
    with db_session() as session:
        service = DBService(session)
        original = session.get(TopicRecord, "acc1_t1")
        original_title = original.title

        favorite = service.favorite_topic("u_001", "acc1", "t1")
        session.delete(original)
        session.commit()

        saved = service.list_favorite_topics("u_001", "acc1")
        creation = service.generate_creation("u_001", "acc1", favorite.id, "小红书")

        assert [item.id for item in saved] == [favorite.id]
        assert saved[0].title == original_title
        assert creation.topicId == favorite.id
        assert creation.topicTitle == original_title


def test_favorite_topic_api_lists_idempotently_and_deletes_snapshot():
    with db_session() as session:
        app.dependency_overrides[get_service] = lambda: DBService(session)
        try:
            client = TestClient(app)
            headers = _auth_headers(client)

            first = client.post("/api/v1/accounts/acc1/favorite-topics/t1", headers=headers)
            duplicate = client.post("/api/v1/accounts/acc1/favorite-topics/t1", headers=headers)
            listed = client.get("/api/v1/accounts/acc1/favorite-topics", headers=headers)

            assert first.status_code == 200
            assert duplicate.status_code == 200
            assert duplicate.json()["id"] == first.json()["id"]
            assert len(listed.json()) == 1
            assert listed.json()[0]["sourceTopicId"] == "t1"

            deleted = client.delete(
                f"/api/v1/accounts/acc1/favorite-topics/{first.json()['id']}",
                headers=headers,
            )
            assert deleted.status_code == 204
            assert session.get(FavoriteTopicRecord, first.json()["id"]) is None
        finally:
            app.dependency_overrides.clear()


def test_topic_recommendation_prompt_uses_account_platforms_in_schema_example():
    prompt = build_topic_recommendation_user_prompt(
        {
            "account": {
                "name": "视频号增长号",
                "platforms": ["抖音"],
            },
            "knowledgeContext": "无",
            "existingTopicTitles": [],
        }
    )

    assert '"platforms": ["抖音"]' in prompt
    assert '"platforms": ["小红书"]' not in prompt
    assert "只允许输出一个 JSON 对象" in prompt
    assert "图文选题只能绑定 contentType=image 的 contentId" in prompt
    assert "视频选题只能绑定 contentType=video 的 contentId" in prompt
    assert "尽量全部返回适合口播的视频选题" in prompt
    assert "当前没有有效图文爆款参考，禁止生成 contentType=image" in prompt


def _generated_report(session: Session, account_id: str = "acc1") -> ReportRecord:
    report = session.get(ReportRecord, account_id)
    report.report_version = 2
    report.generated_at = datetime(2026, 7, 14, 8, 30, tzinfo=UTC)
    report.target_user_profile = {
        "assumption": "假设用户购买中价位底妆。",
        "categories": [
            {
                "categoryName": name,
                "purchaseMotivation": "通过真实对比解决通勤持妆问题。",
                "maleProfile": {"applicable": True, "description": "重要会面前需要快速改善状态的男性。"},
                "femaleProfile": {"applicable": True, "description": "25-35 岁、需要快速完妆的通勤女性。"},
                "internalNote": "不应外传",
            }
            for name in ("高压通勤者", "状态重建者", "重要场合准备者")
        ],
        "priorityRanking": {
            "rankedCategories": [
                {
                    "categoryName": name,
                    "contentAttraction": "high",
                    "trustDifficulty": "medium",
                    "paymentLikelihood": "high",
                    "repurchaseLikelihood": "medium",
                    "reason": "通勤场景明确。",
                }
                for name in ("高压通勤者", "状态重建者", "重要场合准备者")
            ],
            "priorityCategory": "高压通勤者",
            "priorityReason": "高频问题更适合持续内容服务。",
        },
        "positioningReminder": {
            "commonMisjudgment": "把泛美妆兴趣误判成底妆购买意向。",
            "hypothesisToValidate": "真实对比是否能增加咨询。",
        },
        "privateNote": "不应外传",
    }
    report.hot_contents = [
        {
            "platform": "小红书",
            "contentId": f"hot-{index}",
            "title": f"通勤底妆实测 {index}",
            "selectionReason": "收藏与评论表现突出",
            "publicUrl": f"https://example.test/hot-{index}",
            "contentType": "image",
            "metrics": {
                "likedCount": index * 100,
                "commentCount": index * 10,
                "fansCount": 999999,
                "viewCount": "sensitive-string",
                "shareCount": True,
                "engagementScore": {"cookie": "sensitive"},
            },
            "cookie": "sensitive",
        }
        for index in range(1, 13)
    ]
    report.similar_accounts = [
        {
            "platform": "小红书",
            "creatorHash": f"creator-{index}",
            "name": f"通勤美妆号 {index}",
            "similarityReason": "关注通勤底妆",
            "metrics": {
                "fansCount": index * 1000,
                "worksCount": index * 10,
                "likedCount": 999999,
                "interactionCount": "sensitive-string",
                "hitContentCount": False,
            },
            "representativeContents": ["底妆对比"],
            "contact": "sensitive",
        }
        for index in range(1, 13)
    ]
    report.compliance_rules = [
        {
            "riskLevel": "high",
            "expression": f"避免绝对化功效 {index}",
            "reason": "容易构成夸大宣传",
            "suggestion": "使用个人体验表达",
            "platforms": ["小红书"],
            "credential": "sensitive",
        }
        for index in range(1, 21)
    ]
    report.source_meta = {
        "platforms": ["小红书"],
        "keywords": ["通勤妆", "底妆实测", "持妆"],
        "sampleCount": 24,
        "topicReferencePool": [
            {
                "platform": "小红书",
                "contentId": f"hot-{index}",
                "title": f"通勤底妆实测 {index}",
                "summary": f"围绕通勤底妆痛点展开的爆款结构 {index}",
                "selectionReason": "收藏与评论表现突出",
                "publicUrl": f"https://example.test/hot-{index}",
                "coverUrl": f"https://img.example.test/pool-{index}.jpg",
                # 前 10 条留给报告展示；11+ 留给选题原文，保证两侧互斥仍够量
                "contentType": "image" if index <= 20 else "video",
                "sourceKeyword": "通勤妆",
                "sourceSort": "popularity_descending",
                "publishedAt": "2026-07-01",
                "hotScore": index / 40,
                "metrics": {
                    "likedCount": index * 200,
                    "commentCount": index * 20,
                    "hotScore": index / 40,
                    "cookie": "sensitive",
                },
                "raw": {"cookie": "sensitive"},
            }
            for index in range(1, 31)
        ],
        "failedPlatforms": [
            {"platform": "抖音", "reason": "cookie=secret", "cookie": "sensitive"},
        ],
        "unsupportedPlatforms": ["视频号"],
        "rawCookie": "sensitive",
    }
    session.commit()
    return report


def test_topic_recommendation_context_uses_only_generated_report_and_truncates_evidence():
    with db_session() as session:
        _generated_report(session)

        context = WorkflowStore(sessionmaker(bind=session.bind)).topic_recommendation_context("acc1")

        report = context["accountReport"]
        assert report["targetUserProfile"]["categories"][0]["categoryName"] == "高压通勤者"
        assert "privateNote" not in report["targetUserProfile"]
        assert "internalNote" not in report["targetUserProfile"]["categories"][0]
        assert "contentStrategy" not in report
        assert len(report["hotContents"]) == 10
        assert len(report["topicReferencePool"]) == 20
        assert len(report["similarAccounts"]) == 10
        assert len(report["complianceRules"]) == 20
        assert report["complianceRules"][0]["expression"] == "避免绝对化功效 1"
        assert report["hotContents"][0]["metrics"] == {"likedCount": 100, "commentCount": 10}
        assert report["similarAccounts"][0]["metrics"] == {"fansCount": 1000, "worksCount": 10}
        assert report["hotContents"][0]["contentId"] == "hot-1"
        assert report["hotContents"][0]["publicUrl"] == "https://example.test/hot-1"
        # 选题池与展示爆款互斥：展示 hot-1..10，池中从剩余原文按点赞优选
        assert "hot-1" not in {item["contentId"] for item in report["topicReferencePool"]}
        assert report["topicReferencePool"][0]["contentId"] == "hot-30"
        assert "围绕通勤底妆痛点展开的爆款结构" in report["topicReferencePool"][0]["summary"]
        assert report["topicReferencePool"][0]["coverUrl"].startswith("https://img.example.test/pool-")
        assert report["topicReferencePool"][0]["hotScore"] == 30 / 40
        assert report["topicReferencePool"][0]["metrics"] == {
            "likedCount": 6000,
            "commentCount": 600,
            "hotScore": 30 / 40,
        }
        assert "creatorHash" not in report["similarAccounts"][0]
        assert report["sourceMeta"] == {
            "platforms": ["小红书"],
            "keywords": ["通勤妆", "底妆实测", "持妆"],
            "sampleCount": 24,
            "unsupportedPlatforms": ["视频号"],
            "failedPlatforms": ["抖音"],
            "reportVersion": 2,
            "generatedAt": "2026-07-14T08:30:00+00:00",
        }
        assert "cookie" not in report["hotContents"][0]
        assert "cookie" not in report["topicReferencePool"][0]["metrics"]
        assert "raw" not in report["topicReferencePool"][0]
        assert "contact" not in report["similarAccounts"][0]
        assert "credential" not in report["complianceRules"][0]
        assert "rawCookie" not in report["sourceMeta"]


def test_topic_recommendation_context_keeps_topic_pool_disjoint_from_displayed_hot():
    with db_session() as session:
        report = _generated_report(session)
        source_meta = dict(report.source_meta)
        source_meta["topicReferencePool"] = [
            item
            for item in source_meta["topicReferencePool"]
            if item["contentId"] != "hot-1"
        ] + [
            {
                "platform": "小红书",
                "contentId": f"extra-{index}",
                "title": f"补充候选 {index}",
                "publicUrl": f"https://example.test/extra-{index}",
                "contentType": "video",
            }
            for index in range(13, 31)
        ]
        report.source_meta = source_meta
        session.commit()

        context = WorkflowStore(sessionmaker(bind=session.bind)).topic_recommendation_context("acc1")

        reference_pool = context["accountReport"]["topicReferencePool"]
        reference_ids = {item["contentId"] for item in reference_pool}
        hot_ids = {
            item["contentId"]
            for item in context["accountReport"]["hotContents"]
        }
        assert len(reference_pool) == 20
        assert "hot-1" not in reference_ids
        assert hot_ids.isdisjoint(reference_ids)
        assert "hot-11" in reference_ids


def test_topic_recommendation_context_ignores_initialized_or_missing_report():
    with db_session() as session:
        store = WorkflowStore(sessionmaker(bind=session.bind))

        assert store.topic_recommendation_context("acc1")["accountReport"] is None
        assert store.topic_recommendation_context("missing-account") == {}

        report = session.get(ReportRecord, "acc1")
        report.report_version = 1
        report.generated_at = None
        session.commit()
        assert store.topic_recommendation_context("acc1")["accountReport"] is None


def test_topic_recommendation_context_keeps_reports_isolated_by_account():
    with db_session() as session:
        _generated_report(session, "acc1")
        second = _generated_report(session, "acc2")
        second.target_user_profile = {
            **second.target_user_profile,
            "categories": [
                {
                    **item,
                    "categoryName": "本地探店决策者" if index == 0 else item["categoryName"],
                }
                for index, item in enumerate(second.target_user_profile["categories"])
            ],
        }
        session.commit()

        store = WorkflowStore(sessionmaker(bind=session.bind))

        assert store.topic_recommendation_context("acc1")["accountReport"]["targetUserProfile"]["categories"][0]["categoryName"] == "高压通勤者"
        assert store.topic_recommendation_context("acc2")["accountReport"]["targetUserProfile"]["categories"][0]["categoryName"] == "本地探店决策者"


def test_topic_prompt_uses_report_evidence_and_compliance_rules():
    prompt = build_topic_recommendation_user_prompt(
        {
            "account": {"name": "通勤美妆号", "platforms": ["小红书"]},
            "accountReport": {
                "targetUserProfile": {"summary": "25-35 岁通勤女性"},
                "hotContents": [{"title": "通勤底妆实测"}],
                "topicReferencePool": [{"title": "参考池底妆实测"}],
                "similarAccounts": [{"name": "通勤美妆研究所"}],
                "complianceRules": [{"expression": "避免绝对化功效"}],
                "sourceMeta": {"platforms": ["小红书"]},
            },
        }
    )

    assert "目标用户画像" in prompt
    assert "通勤底妆实测" in prompt
    assert "参考池底妆实测" in prompt
    assert "选题参考爆款池" in prompt
    assert "相似账号:" in prompt
    assert "内容策略" not in prompt
    assert "避免绝对化功效" in prompt
    assert "可参考选题参考爆款池提炼方向" in prompt
    assert "遵守合规限制" in prompt


def test_topic_prompt_requires_topics_to_differ_from_hot_content_reference():
    system_prompt = build_topic_recommendation_system_prompt()
    prompt = build_topic_recommendation_user_prompt(
        {
            "account": {"name": "通勤美妆号", "platforms": ["小红书"]},
            "accountReport": {
                "hotContents": [
                    {
                        "contentId": "hot-1",
                        "title": "早八通勤底妆实测",
                        "contentType": "image",
                        "publicUrl": "https://example.test/hot-1",
                    }
                ]
            },
        }
    )

    assert "必须与爆款参考明显不同" in system_prompt or "禁止复刻" in system_prompt
    assert "原文参考" in system_prompt or "referenceContentId" in system_prompt
    assert "换一批必须避开" in prompt
    assert "必须换切口" in prompt or "换了什么切口" in prompt or "切口必须与爆款明显不同" in prompt
    assert "前端“原文”" in prompt or "referenceContentId" in prompt
    assert "选题参考爆款池" in prompt
    assert "互斥" in prompt or "禁止绑定这些 contentId" in prompt


def test_normalize_skips_titles_similar_to_existing_or_hot():
    topics, fallbacks = normalize_recommended_topics(
        [
            {"title": "早八通勤底妆实测完整版", "contentType": "video"},
            {"title": "晚八派对妆容教程", "contentType": "video"},
            {"title": "昨日已推选题A", "contentType": "video"},
        ],
        ["抖音"],
        "抖音",
        avoid_titles=["昨日已推选题A"],
        hot_titles=["早八通勤底妆实测"],
    )

    assert [item["title"] for item in topics] == ["晚八派对妆容教程"]
    assert any("skipped similar" in item for item in fallbacks)

def test_topic_prompt_still_works_without_report():
    prompt = build_topic_recommendation_user_prompt(
        {"account": {"name": "通勤美妆号", "platforms": ["小红书"]}, "accountReport": None}
    )

    assert "账号档案" in prompt
    assert "无已生成账号报告" in prompt


def test_topic_recommendation_truncates_database_bounded_text_fields():
    topics, fallbacks = normalize_recommended_topics(
        [
            {
                "title": "选" * 256,
                "category": "分类" * 33,
                "contentType": "video",
                "platforms": ["抖音"],
            }
        ],
        ["抖音"],
        "抖音",
    )

    assert topics[0]["title"] == "选" * 255
    assert topics[0]["category"] == ("分类" * 32)
    assert len(topics[0]["category"]) == 64
    assert any("title truncated to 255 characters" in item for item in fallbacks)
    assert any("category truncated to 64 characters" in item for item in fallbacks)


class TopicAIService:
    token = "test-token"

    def __init__(self, response: str) -> None:
        self.response = response
        self.chat_completion_inputs: list[str] = []
        self.chat_completion_models: list[str | None] = []

    async def chat_completion(self, messages, system_prompt=None, temperature=0.7, **kwargs):  # noqa: ANN001, ARG002
        self.chat_completion_inputs.append(str(messages[0]["content"]))
        self.chat_completion_models.append(kwargs.get("model"))
        return self.response


class SequenceTopicAIService(TopicAIService):
    def __init__(self, responses: list[str]) -> None:
        super().__init__(responses[-1])
        self.responses = iter(responses)

    async def chat_completion(self, messages, system_prompt=None, temperature=0.7, **kwargs):  # noqa: ANN001, ARG002
        self.chat_completion_inputs.append(str(messages[0]["content"]))
        self.chat_completion_models.append(kwargs.get("model"))
        return next(self.responses)


class InlineTopicScheduler:
    def __init__(self, service: WorkflowService) -> None:
        self.service = service
        self.submissions: list[tuple[str, str]] = []

    def submit(self, workflow_type: str, workflow_id: str, context=None) -> None:  # noqa: ANN001, ARG002
        self.submissions.append((workflow_type, workflow_id))
        self.service.run_job(workflow_type, workflow_id)


class FailingTopicScheduler:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, str]] = []

    def submit(self, workflow_type: str, workflow_id: str, context=None) -> None:  # noqa: ANN001, ARG002
        self.submissions.append((workflow_type, workflow_id))
        raise RuntimeError("scheduler submit failed")


def _bind_demo_knowledge_base(session: Session) -> None:
    knowledge = KnowledgeBaseRecord(
        id="kb_topic",
        user_id="u_001",
        name="美妆基础库",
        product_name="星颜精华",
        product_intro="主打抗氧修护和通勤场景。",
        brand_story="实验室护肤品牌。",
        price="299元",
        logo_url="https://cdn.example.test/logo.png",
        image_materials=["https://cdn.example.test/kv.png"],
        contact_info="VX: starx",
        website_url="https://brand.example.test",
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
    session.add(knowledge)
    account = session.get(AccountRecord, "acc1")
    account.knowledge_base_id = knowledge.id
    account.industry = "美妆护肤"
    account.product_service = "抗氧精华"
    account.target_audience = "25-35 岁职场女性"
    account.conversion_goal = "留资转化"
    session.commit()


def _topic_response(count: int = 8, platform: str = "小红书") -> str:
    topics = [
        {
            "title": f"抗氧通勤选题 {index}",
            "reason": "贴合职场女性通勤护肤场景",
            "platforms": [platform],
            "category": "护肤种草",
            "contentType": "image" if index % 2 else "video",
            # 使用展示爆款之外的候选，保证选题原文与报告爆款互斥
            **({"referenceContentId": f"hot-{index + 10}"} if index % 2 else {}),
        }
        for index in range(1, count + 1)
    ]
    import json

    return json.dumps({"topics": topics}, ensure_ascii=False)


def _mixed_topic_response(image_count: int, video_count: int, platform: str = "小红书") -> str:
    topics = [
        {
            "title": f"图文抗氧选题 {index}",
            "reason": "贴合职场女性通勤护肤场景",
            "platforms": [platform],
            "category": "护肤种草",
            "contentType": "image",
            "referenceContentId": f"hot-{index + 10}",
        }
        for index in range(1, image_count + 1)
    ]
    topics.extend(
        {
            "title": f"视频抗氧选题 {index}",
            "reason": "适合用短视频展示护肤步骤",
            "platforms": [platform],
            "category": "护肤视频",
            "contentType": "video",
            "referenceContentId": f"hot-{index + 20}",
        }
        for index in range(1, video_count + 1)
    )
    import json

    return json.dumps({"topics": topics}, ensure_ascii=False)


def _make_report_video_only(session: Session, account_id: str = "acc1") -> None:
    report = _generated_report(session, account_id)
    report.hot_contents = [
        {
            "platform": "抖音",
            "contentId": f"video-{index}",
            "title": f"通勤护肤视频 {index}",
            "selectionReason": "播放与评论表现突出",
            "publicUrl": f"https://example.test/video-{index}",
            "contentType": "video",
            "metrics": {"likedCount": index * 100},
        }
        for index in range(1, 9)
    ]
    report.source_meta = {
        **dict(report.source_meta or {}),
        "platforms": ["抖音"],
        "topicReferencePool": [
            {
                "platform": "抖音",
                "contentId": f"video-{index}",
                "title": f"通勤护肤视频 {index}",
                "publicUrl": f"https://example.test/video-{index}",
                "contentType": "video",
                "metrics": {"likedCount": index * 100},
            }
            for index in range(1, 21)
        ],
    }
    account = session.get(AccountRecord, account_id)
    account.platform = "抖音"
    account.platforms = ["抖音"]
    session.commit()


def test_topic_recommendation_workflow_replaces_topics_and_records_step():
    with db_session() as session:
        _bind_demo_knowledge_base(session)
        _generated_report(session)
        expected_report_context = WorkflowStore(sessionmaker(bind=session.bind)).topic_recommendation_context(
            "acc1"
        )["accountReport"]
        knowledge = session.get(KnowledgeBaseRecord, "kb_topic")
        knowledge.enabled_fields = {
            **dict(knowledge.enabled_fields or {}),
            "logoUrl": True,
            "imageMaterials": True,
        }
        session.commit()
        ai = TopicAIService(_topic_response())
        service = WorkflowService(session, ai_service=ai)

        created, is_new = service.create_topic_recommendation_job("u_001", "acc1")
        completed = service.run_job("topic_recommendation", created.id)

        rows = (
            session.query(TopicRecord)
            .filter(TopicRecord.account_id == "acc1")
            .order_by(TopicRecord.sort_order)
            .all()
        )
        step = session.query(WorkflowStepRecord).filter(WorkflowStepRecord.workflow_id == created.id).one()

        assert is_new is True
        assert completed.status == "completed"
        assert len(rows) == 8
        assert rows[0].title == "抗氧通勤选题 1"
        assert rows[0].reason == "贴合职场女性通勤护肤场景"
        assert rows[0].platforms == ["小红书"]
        assert rows[0].reference_note == {
            "contentId": "hot-11",
            "platform": "小红书",
            "title": "通勤底妆实测 11",
            "summary": "围绕通勤底妆痛点展开的爆款结构 11",
            "selectionReason": "收藏与评论表现突出",
            "publicUrl": "https://example.test/hot-11",
            "coverUrl": "https://img.example.test/pool-11.jpg",
            "contentType": "image",
            "sourceKeyword": "通勤妆",
            "sourceSort": "popularity_descending",
            "publishedAt": "2026-07-01",
            "hotScore": 11 / 40,
            "metrics": {"likedCount": 2200, "commentCount": 220, "hotScore": 11 / 40},
        }
        assert all(row.reference_note for row in rows if row.content_type == "image")
        assert rows[0].batch_id == created.id
        assert step.type == "topic_recommendation"
        assert step.status == "completed"
        assert "星颜精华" in ai.chat_completion_inputs[0]
        assert "https://cdn.example.test/logo.png" in ai.chat_completion_inputs[0]
        assert "https://cdn.example.test/kv.png" in ai.chat_completion_inputs[0]
        assert "实验室护肤品牌" not in ai.chat_completion_inputs[0]
        assert "VX: starx" not in ai.chat_completion_inputs[0]
        assert "25-35 岁、需要快速完妆的通勤女性" in ai.chat_completion_inputs[0]
        assert ai.chat_completion_models == ["qwen-flash"]
        assert completed.resultPayload["accountReport"]["hotContents"][0]["title"] == "通勤底妆实测 1"
        assert len(completed.resultPayload["accountReport"]["hotContents"]) == 10
        assert "cookie" not in completed.resultPayload["accountReport"]["hotContents"][0]
        assert completed.resultPayload["accountReport"] == expected_report_context


def test_topic_recommendation_normalizes_out_of_scope_platform():
    with db_session() as session:
        _generated_report(session)
        account = session.get(AccountRecord, "acc1")
        account.platform = "抖音"
        account.platforms = ["小红书", "抖音"]
        session.commit()
        ai = TopicAIService(_topic_response(platform="抖音"))
        service = WorkflowService(session, ai_service=ai)

        created, _ = service.create_topic_recommendation_job("u_001", "acc1")
        ai.response = _topic_response(platform="视频号")
        service.run_job("topic_recommendation", created.id)

        rows = session.query(TopicRecord).filter(TopicRecord.account_id == "acc1").all()
        assert {tuple(row.platforms) for row in rows} == {("抖音",)}


def test_topic_recommendation_persists_only_first_eight_valid_topics():
    with db_session() as session:
        _generated_report(session)
        ai = TopicAIService(_topic_response(count=10))
        service = WorkflowService(session, ai_service=ai)

        created, _ = service.create_topic_recommendation_job("u_001", "acc1")
        completed = service.run_job("topic_recommendation", created.id)
        step = session.query(WorkflowStepRecord).filter(WorkflowStepRecord.workflow_id == created.id).one()

        rows = (
            session.query(TopicRecord)
            .filter(TopicRecord.account_id == "acc1")
            .order_by(TopicRecord.sort_order)
            .all()
        )

        assert completed.status == "completed"
        assert len(rows) == 8
        assert [row.title for row in rows] == [f"抗氧通勤选题 {index}" for index in range(1, 9)]
        assert len(completed.resultPayload["topics"]) == 8
        assert len(step.result_payload["topics"]) == 8


def test_topic_recommendation_fills_short_ai_batch_from_reference_pool():
    """AI 有效选题不足 8 条时，用参考池原文补齐，不再直接失败。"""

    with db_session() as session:
        _generated_report(session)
        original_titles = [
            row.title
            for row in session.query(TopicRecord)
            .filter(TopicRecord.account_id == "acc1")
            .order_by(TopicRecord.sort_order)
            .all()
        ]
        ai = TopicAIService(_mixed_topic_response(image_count=4, video_count=0))
        service = WorkflowService(session, ai_service=ai)

        created, _ = service.create_topic_recommendation_job("u_001", "acc1")
        completed = service.run_job("topic_recommendation", created.id)
        after_titles = [
            row.title
            for row in session.query(TopicRecord)
            .filter(TopicRecord.account_id == "acc1")
            .order_by(TopicRecord.sort_order)
            .all()
        ]

        assert completed.status == "completed"
        assert len(after_titles) == 8
        assert after_titles != original_titles
        assert len(ai.chat_completion_inputs) == 1


def test_topic_recommendation_retries_invalid_json_then_persists_valid_correction():
    with db_session() as session:
        _generated_report(session)
        correction = json.loads(_mixed_topic_response(image_count=10, video_count=0))
        ai = SequenceTopicAIService(
            [
                "not-json",
                json.dumps(correction, ensure_ascii=False),
            ]
        )
        service = WorkflowService(session, ai_service=ai)

        created, _ = service.create_topic_recommendation_job("u_001", "acc1")
        completed = service.run_job("topic_recommendation", created.id)

        rows = (
            session.query(TopicRecord)
            .filter(TopicRecord.account_id == "acc1")
            .order_by(TopicRecord.sort_order)
            .all()
        )
        step = session.query(WorkflowStepRecord).filter(
            WorkflowStepRecord.workflow_id == created.id
        ).one()

        assert completed.status == "completed"
        assert step.status == "completed"
        assert len(rows) == 8
        assert len(ai.chat_completion_inputs) == 2
        assert "上一次结果未通过校验" in ai.chat_completion_inputs[1]


def test_topic_recommendation_accepts_any_image_video_ratio():
    with db_session() as session:
        _generated_report(session)
        ai = TopicAIService(_mixed_topic_response(image_count=6, video_count=4))
        service = WorkflowService(session, ai_service=ai)

        created, _ = service.create_topic_recommendation_job("u_001", "acc1")
        completed = service.run_job("topic_recommendation", created.id)

        rows = (
            session.query(TopicRecord)
            .filter(TopicRecord.account_id == "acc1")
            .order_by(TopicRecord.sort_order)
            .all()
        )

        assert completed.status == "completed"
        assert len(rows) == 8
        assert [row.content_type for row in rows].count("image") == 6
        assert [row.content_type for row in rows].count("video") == 2
        assert [topic["contentType"] for topic in completed.resultPayload["topics"]].count("image") == 6
        assert [topic["contentType"] for topic in completed.resultPayload["topics"]].count("video") == 2


def test_topic_recommendation_accepts_imbalanced_batch_without_retyping_topics():
    with db_session() as session:
        _generated_report(session)
        original_titles = [
            row.title
            for row in session.query(TopicRecord)
            .filter(TopicRecord.account_id == "acc1")
            .order_by(TopicRecord.sort_order)
            .all()
        ]
        ai = TopicAIService(_mixed_topic_response(image_count=3, video_count=5))
        service = WorkflowService(session, ai_service=ai)

        created, _ = service.create_topic_recommendation_job("u_001", "acc1")
        completed = service.run_job("topic_recommendation", created.id)
        after_titles = [
            row.title
            for row in session.query(TopicRecord)
            .filter(TopicRecord.account_id == "acc1")
            .order_by(TopicRecord.sort_order)
            .all()
        ]

        assert completed.status == "completed"
        assert completed.error == ""
        assert after_titles != original_titles
        assert len(after_titles) == 8


def test_topic_recommendation_allows_video_only_batch_when_refreshing():
    with db_session() as session:
        _generated_report(session)
        original_titles = [
            row.title
            for row in session.query(TopicRecord)
            .filter(TopicRecord.account_id == "acc1")
            .order_by(TopicRecord.sort_order)
            .all()
        ]
        ai = TopicAIService(_mixed_topic_response(image_count=0, video_count=8))
        service = WorkflowService(session, ai_service=ai)

        created, _ = service.create_topic_recommendation_job("u_001", "acc1")
        completed = service.run_job("topic_recommendation", created.id)
        after_titles = [
            row.title
            for row in session.query(TopicRecord)
            .filter(TopicRecord.account_id == "acc1")
            .order_by(TopicRecord.sort_order)
            .all()
        ]

        assert completed.status == "completed"
        assert completed.error == ""
        assert after_titles != original_titles
        assert len(after_titles) == 8


def test_topic_recommendation_accepts_video_only_batch_when_report_has_no_image_reference():
    with db_session() as session:
        _make_report_video_only(session)
        ai = TopicAIService(_mixed_topic_response(image_count=0, video_count=8, platform="抖音"))
        service = WorkflowService(session, ai_service=ai)

        created, _ = service.create_topic_recommendation_job("u_001", "acc1")
        completed = service.run_job("topic_recommendation", created.id)

        rows = (
            session.query(TopicRecord)
            .filter(TopicRecord.account_id == "acc1")
            .order_by(TopicRecord.sort_order)
            .all()
        )

        assert completed.status == "completed"
        assert len(rows) == 8
        assert {row.content_type for row in rows} == {"video"}
        assert all(row.reference_note for row in rows)
        assert all((row.reference_note or {}).get("contentType") == "video" for row in rows)
        assert "尽量全部返回适合口播的视频选题" in ai.chat_completion_inputs[0]
        assert "禁止生成 contentType=image，必须全部为口播视频" in ai.chat_completion_inputs[0]


def test_topic_normalization_converts_image_topics_to_video_without_image_references():
    raw_topics = [
        {
            "title": f"误报图文选题 {index}",
            "reason": "模型误报为图文",
            "platforms": ["抖音"],
            "category": "短视频",
            "contentType": "image",
            "referenceContentId": "missing",
        }
        for index in range(1, 9)
    ]

    topics, fallbacks = normalize_recommended_topics(
        raw_topics,
        ["抖音"],
        "抖音",
        [
            {
                "contentId": "video-1",
                "publicUrl": "https://example.test/video-1",
                "contentType": "video",
            }
        ],
    )

    assert len(topics) == 1
    assert {topic["contentType"] for topic in topics} == {"video"}
    referenced = [
        topic["referenceNote"].get("contentId")
        for topic in topics
        if topic.get("referenceNote")
    ]
    assert referenced == ["video-1"]
    assert sum(1 for topic in topics if topic.get("referenceNote")) == 1
    assert any("referenceNote backfilled" in item or "converted to video" in item for item in fallbacks)
    assert any(
        "no unused reference left" in item or "dropped without unique reference" in item
        for item in fallbacks
    )


def test_topic_normalization_keeps_reference_notes_unique():
    raw_topics = [
        {
            "title": f"选题{index}",
            "reason": "借鉴爆款结构换切口",
            "platforms": ["小红书"],
            "category": "留学",
            "contentType": "image",
            "referenceContentId": "note-1" if index <= 4 else "note-1",
        }
        for index in range(1, 5)
    ]
    references = [
        {
            "contentId": f"note-{index}",
            "title": f"爆款{index}",
            "publicUrl": f"https://example.test/note-{index}",
            "contentType": "image",
        }
        for index in range(1, 5)
    ]

    topics, fallbacks = normalize_recommended_topics(
        raw_topics,
        ["小红书"],
        "小红书",
        references,
    )

    ids = [
        str((topic.get("referenceNote") or {}).get("contentId") or "")
        for topic in topics
    ]
    assert len(ids) == 4
    assert len(set(ids)) == 4
    assert set(ids) == {"note-1", "note-2", "note-3", "note-4"}
    assert any("duplicate" in item for item in fallbacks)


def test_fill_topics_from_reference_pool_reaches_eight_unique_notes():
    topics = [
        {
            "title": "已有选题",
            "source": "AI推荐",
            "category": "留学",
            "contentType": "image",
            "topicPattern": "痛点避坑",
            "reason": "模型产出",
            "platforms": ["小红书"],
            "referenceNote": {
                "contentId": "note-1",
                "publicUrl": "https://example.test/note-1",
                "contentType": "image",
                "title": "爆款1",
            },
        }
    ]
    references = [
        {
            "contentId": f"note-{index}",
            "title": f"爆款原文{index}",
            "publicUrl": f"https://example.test/note-{index}",
            "contentType": "image",
            "sourceKeyword": "留学申请",
        }
        for index in range(1, 10)
    ]

    filled, fallbacks = fill_topics_from_reference_pool(
        topics,
        references,
        allowed_platforms=["小红书"],
        canonical_platform="小红书",
        need=8,
    )

    assert len(filled) == 8
    ids = [
        str((item.get("referenceNote") or {}).get("contentId") or "")
        for item in filled
    ]
    assert len(set(ids)) == 8
    assert ids[0] == "note-1"
    assert any("filled from general search pool" in item for item in fallbacks)


def test_topic_recommendation_accepts_top_level_topic_array():
    with db_session() as session:
        _generated_report(session)
        ai = TopicAIService(_mixed_topic_response(image_count=4, video_count=4))
        ai.response = ai.response.removeprefix('{"topics": ').removesuffix("}")
        service = WorkflowService(session, ai_service=ai)

        created, _ = service.create_topic_recommendation_job("u_001", "acc1")
        completed = service.run_job("topic_recommendation", created.id)

        rows = session.query(TopicRecord).filter(TopicRecord.account_id == "acc1").all()

        assert completed.status == "completed"
        assert len(rows) == 8


def test_create_topic_recommendation_job_reuses_pending_workflow():
    with db_session() as session:
        service = WorkflowService(session, ai_service=TopicAIService(_topic_response()))

        first, is_new = service.create_topic_recommendation_job("u_001", "acc1")
        second, reused = service.create_topic_recommendation_job("u_001", "acc1")

        assert is_new is True
        assert reused is False
        assert second.id == first.id


def test_get_topic_recommendation_job_validates_account_and_presence():
    with db_session() as session:
        service = WorkflowService(session, ai_service=TopicAIService(_topic_response()))
        created, _ = service.create_topic_recommendation_job("u_001", "acc1")

        fetched = service.get_topic_recommendation_job("u_001", "acc1", created.id)

        assert fetched.id == created.id

        with pytest.raises(StopIteration):
            service.get_topic_recommendation_job("u_001", "missing-account", created.id)

        with pytest.raises(StopIteration):
            service.get_topic_recommendation_job("u_001", "acc1", "wf_missing")


def test_topic_recommendation_failure_keeps_existing_topics():
    with db_session() as session:
        original_titles = [row.title for row in session.query(TopicRecord).filter(TopicRecord.account_id == "acc1").all()]
        ai = TopicAIService("not a json payload")
        service = WorkflowService(session, ai_service=ai)

        created, _ = service.create_topic_recommendation_job("u_001", "acc1")
        completed = service.run_job("topic_recommendation", created.id)
        after_titles = [row.title for row in session.query(TopicRecord).filter(TopicRecord.account_id == "acc1").all()]

        assert completed.status == "failed"
        assert "invalid JSON" in completed.error
        assert after_titles == original_titles


def test_image_topics_with_non_image_reference_are_rejected_instead_of_randomly_rebound():
    topics, fallbacks = normalize_recommended_topics(
        [{"title": "图文选题", "contentType": "image", "referenceContentId": "video-1"}],
        ["小红书"],
        "小红书",
        [
            {
                "contentId": "video-1",
                "platform": "小红书",
                "title": "视频爆款",
                "publicUrl": "https://example.test/video-1",
                "contentType": "video",
            },
            {
                "contentId": "image-1",
                "platform": "小红书",
                "title": "图文爆款",
                "publicUrl": "https://example.test/image-1",
                "contentType": "image",
            },
        ],
    )

    assert topics == []
    assert "图文选题: skipped invalid image reference" in fallbacks


def test_image_topic_without_any_report_reference_is_converted_to_video():
    topics, fallbacks = normalize_recommended_topics(
        [{"title": "无引用图文", "contentType": "image"}],
        ["小红书"],
        "小红书",
        [],
    )

    assert len(topics) == 1
    assert topics[0]["contentType"] == "video"
    assert topics[0]["referenceNote"] == {}
    assert "无引用图文: image topic converted to video without reference" in fallbacks


def test_image_topic_reason_replaces_reference_content_id_with_title():
    topics, _ = normalize_recommended_topics(
        [
            {
                "title": "新手选车避坑",
                "reason": "高度复刻爆款笔记6904b89a000000000302264f的核心主题和选车技巧",
                "contentType": "image",
                "referenceContentId": "6904b89a000000000302264f",
            }
        ],
        ["小红书"],
        "小红书",
        [
            {
                "contentId": "6904b89a000000000302264f",
                "platform": "小红书",
                "title": "新手第一次买车必看的 6 个避坑技巧",
                "publicUrl": "https://example.test/note",
                "contentType": "image",
            }
        ],
    )

    assert topics[0]["reason"] == "高度复刻爆款笔记《新手第一次买车必看的 6 个避坑技巧》的核心主题和选车技巧"
    assert topics[0]["referenceNote"]["contentId"] == "6904b89a000000000302264f"
    assert topics[0]["referenceNote"]["publicUrl"] == "https://example.test/note"
    assert "6904b89a000000000302264f" not in topics[0]["reason"]


def test_refresh_topics_api_creates_workflow_and_reloads_topics():
    with db_session() as session:
        _generated_report(session)
        ai = TopicAIService(_topic_response())
        service = WorkflowService(session, ai_service=ai)
        scheduler = InlineTopicScheduler(service)
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_topic_workflow_service] = lambda: service
        app.dependency_overrides[get_topic_refresh_scheduler] = lambda: scheduler
        try:
            client = TestClient(app)
            headers = _auth_headers(client)

            created = client.post("/api/v1/accounts/acc1/topics/refresh-batch", headers=headers)
            listed = client.get("/api/v1/accounts/acc1/topics", headers=headers)
            status = client.get(f"/api/v1/accounts/acc1/topics/refresh-workflows/{created.json()['id']}", headers=headers)

            assert created.status_code == 200
            assert created.json()["type"] == "topic_recommendation"
            assert scheduler.submissions == [("topic_recommendation", created.json()["id"])]
            assert status.json()["status"] == "completed"
            assert listed.json()[0]["reason"] == "贴合职场女性通勤护肤场景"
            assert listed.json()[0]["platforms"] == ["小红书"]
        finally:
            app.dependency_overrides.clear()


def test_refresh_topics_api_reuses_running_workflow_without_resubmitting():
    with db_session() as session:
        service = WorkflowService(session, ai_service=TopicAIService(_topic_response()))
        existing, _ = service.create_topic_recommendation_job("u_001", "acc1")
        record = session.get(WorkflowRecord, existing.id)
        record.status = "running"
        session.commit()
        scheduler = InlineTopicScheduler(service)
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_topic_workflow_service] = lambda: service
        app.dependency_overrides[get_topic_refresh_scheduler] = lambda: scheduler
        try:
            client = TestClient(app)
            headers = _auth_headers(client)

            response = client.post("/api/v1/accounts/acc1/topics/refresh-batch", headers=headers)

            assert response.status_code == 200
            assert response.json()["id"] == existing.id
            assert scheduler.submissions == []
        finally:
            app.dependency_overrides.clear()


def test_refresh_topics_api_reuses_pending_workflow_without_resubmitting():
    with db_session() as session:
        service = WorkflowService(session, ai_service=TopicAIService(_topic_response()))
        existing, _ = service.create_topic_recommendation_job("u_001", "acc1")
        scheduler = InlineTopicScheduler(service)
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_topic_workflow_service] = lambda: service
        app.dependency_overrides[get_topic_refresh_scheduler] = lambda: scheduler
        try:
            client = TestClient(app)
            headers = _auth_headers(client)

            response = client.post("/api/v1/accounts/acc1/topics/refresh-batch", headers=headers)

            assert response.status_code == 200
            assert response.json()["id"] == existing.id
            assert scheduler.submissions == []
        finally:
            app.dependency_overrides.clear()


def test_refresh_topics_api_marks_new_workflow_failed_when_scheduler_submit_fails_and_allows_retry():
    with db_session() as session:
        service = WorkflowService(session, ai_service=TopicAIService(_topic_response()))
        failing_scheduler = FailingTopicScheduler()
        app.dependency_overrides[get_service] = lambda: DBService(session)
        app.dependency_overrides[get_topic_workflow_service] = lambda: service
        app.dependency_overrides[get_topic_refresh_scheduler] = lambda: failing_scheduler
        try:
            client = TestClient(app, raise_server_exceptions=False)
            headers = _auth_headers(client)

            failed_response = client.post("/api/v1/accounts/acc1/topics/refresh-batch", headers=headers)

            failed_records = (
                session.query(WorkflowRecord)
                .filter(
                    WorkflowRecord.account_id == "acc1",
                    WorkflowRecord.user_id == "u_001",
                    WorkflowRecord.type == "topic_recommendation",
                )
                .all()
            )
            assert failed_response.status_code == 500
            assert len(failed_records) == 1
            assert failing_scheduler.submissions == [("topic_recommendation", failed_records[0].id)]
            assert failed_records[0].status == "failed"
            assert "scheduler submit failed" in failed_records[0].error

            retry_scheduler = InlineTopicScheduler(service)
            app.dependency_overrides[get_topic_refresh_scheduler] = lambda: retry_scheduler
            retry_response = client.post("/api/v1/accounts/acc1/topics/refresh-batch", headers=headers)

            assert retry_response.status_code == 200
            assert retry_response.json()["id"] != failed_records[0].id
            assert retry_scheduler.submissions == [("topic_recommendation", retry_response.json()["id"])]
        finally:
            app.dependency_overrides.clear()


def test_topic_recommendation_replacement_failure_marks_step_failed_and_preserves_topics(monkeypatch: pytest.MonkeyPatch):
    def _boom(self, *, workflow_id, user_id, account_id, topics):  # noqa: ANN001
        raise RuntimeError("replace failed")

    monkeypatch.setattr(WorkflowStore, "replace_account_topics", _boom)

    with db_session() as session:
        _generated_report(session)
        original_titles = [row.title for row in session.query(TopicRecord).filter(TopicRecord.account_id == "acc1").all()]
        ai = TopicAIService(_topic_response())
        service = WorkflowService(session, ai_service=ai)

        created, _ = service.create_topic_recommendation_job("u_001", "acc1")
        completed = service.run_job("topic_recommendation", created.id)

        step = session.query(WorkflowStepRecord).filter(WorkflowStepRecord.workflow_id == created.id).one()
        after_titles = [row.title for row in session.query(TopicRecord).filter(TopicRecord.account_id == "acc1").all()]

        assert completed.status == "failed"
        assert "replace failed" in completed.error
        assert step.status == "failed"
        assert "replace failed" in step.error
        assert after_titles == original_titles
