from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.workflow_deps import get_account_report_scheduler
from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.db.models import UserRecord
from app.main import app


class NoopAccountReportScheduler:
    def submit(self, workflow_type: str, workflow_id: str, context=None) -> None:  # noqa: ANN001, ARG002
        return None


@pytest.fixture(autouse=True)
def disable_account_report_background_dispatch():
    previous = app.dependency_overrides.get(get_account_report_scheduler)
    app.dependency_overrides[get_account_report_scheduler] = NoopAccountReportScheduler
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_account_report_scheduler, None)
        else:
            app.dependency_overrides[get_account_report_scheduler] = previous


def auth_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": "demo@starx.ai", "password": "demo123"})
    token = login.json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


def account_and_topic(client: TestClient, headers: dict[str, str]) -> tuple[str, str]:
    accounts = client.get("/api/v1/accounts", headers=headers)
    assert accounts.status_code == 200
    for account in accounts.json():
        topics = client.get(f"/api/v1/accounts/{account['id']}/topics", headers=headers)
        assert topics.status_code == 200
        if topics.json():
            return account["id"], topics.json()[0]["id"]
    raise AssertionError("测试账号中没有可用于内容创作的主题")


def create_isolated_account(client: TestClient, headers: dict[str, str]) -> str:
    unique_id = uuid4().hex[:8]
    created = client.post(
        "/api/v1/accounts",
        json={
            "name": f"隔离测试账号{unique_id}",
            "description": "用于验证账号初始化数据",
            "purpose": "自动化测试",
            "type": "普通号",
            "platforms": ["小红书"],
            "accountLinks": {
                "小红书": f"https://www.xiaohongshu.com/user/profile/{unique_id}"
            },
        },
        headers=headers,
    )
    assert created.status_code == 200
    return created.json()["id"]


def test_accounts_topics_and_creation_flow():
    client = TestClient(app)
    headers = auth_headers(client)
    first_account_id, first_topic_id = account_and_topic(client, headers)

    creation = client.post(
        f"/api/v1/accounts/{first_account_id}/creations/generate",
        json={"topicId": first_topic_id, "targetPlatform": "小红书"},
        headers=headers,
    )
    assert creation.status_code == 200
    assert creation.json()["targetPlatform"] == "小红书"


def test_generate_creation_uses_empty_video_scripts_and_preserves_image_scripts():
    client = TestClient(app)
    headers = auth_headers(client)
    selected_account = None
    video_topic = None
    image_topic = None
    for account in client.get("/api/v1/accounts", headers=headers).json():
        topics = client.get(f"/api/v1/accounts/{account['id']}/topics", headers=headers).json()
        video_topic = next((topic for topic in topics if topic["type"] == "video"), None)
        image_topic = next((topic for topic in topics if topic["type"] == "image"), None)
        if video_topic and image_topic:
            selected_account = account
            break

    assert selected_account is not None
    target_platform = selected_account["platform"]

    video_creation = client.post(
        f"/api/v1/accounts/{selected_account['id']}/creations/generate",
        json={"topicId": video_topic["id"], "targetPlatform": target_platform},
        headers=headers,
    )

    assert video_creation.status_code == 200
    assert video_creation.json()["type"] == "video"
    assert video_creation.json()["content"]["scriptOriginal"] == []
    assert video_creation.json()["content"]["scriptRewritten"] == []

    image_creation = client.post(
        f"/api/v1/accounts/{selected_account['id']}/creations/generate",
        json={"topicId": image_topic["id"], "targetPlatform": target_platform},
        headers=headers,
    )

    assert image_creation.status_code == 200
    assert image_creation.json()["type"] == "image"
    assert image_creation.json()["content"]["scriptOriginal"]
    assert image_creation.json()["content"]["scriptRewritten"]


def test_creation_submit_persists_editable_content_and_links_workflow_task():
    client = TestClient(app)
    headers = auth_headers(client)
    account_id, topic_id = account_and_topic(client, headers)

    creation = client.post(
        f"/api/v1/accounts/{account_id}/creations/generate",
        json={"topicId": topic_id, "targetPlatform": "小红书"},
        headers=headers,
    )
    assert creation.status_code == 200
    creation_payload = creation.json()
    creation_id = creation_payload["creationId"]

    submitted = client.post(
        f"/api/v1/accounts/{account_id}/creations/{creation_id}/submit-task",
        json={
            "topicId": topic_id,
            "targetPlatform": "小红书",
            "type": "video",
            "content": {
                **creation_payload["content"],
                "title": "用户编辑后的脚本标题",
                "body": "这是用户在内容创作页编辑后的正文和脚本。",
                "scriptRewritten": ["镜头1：产品特写", "镜头2：上脸演示"],
            },
        },
        headers=headers,
    )

    assert submitted.status_code == 200
    task = submitted.json()
    assert task["title"] == "用户编辑后的脚本标题"
    assert task["creationId"] == creation_id
    assert task["status"] == "draft"

    tasks = client.get(f"/api/v1/accounts/{account_id}/tasks", headers=headers)
    assert tasks.status_code == 200
    assert any(item["id"] == task["id"] and item["creationId"] == creation_id for item in tasks.json())

    persisted = client.get(f"/api/v1/accounts/{account_id}/creations/{creation_id}", headers=headers)
    assert persisted.status_code == 200
    assert persisted.json()["content"]["body"] == "这是用户在内容创作页编辑后的正文和脚本。"
    assert persisted.json()["content"]["scriptRewritten"] == ["镜头1：产品特写", "镜头2：上脸演示"]


def test_creation_submit_persists_creation_state_for_workflow_reopen():
    client = TestClient(app)
    headers = auth_headers(client)
    account_id, topic_id = account_and_topic(client, headers)
    creation = client.post(
        f"/api/v1/accounts/{account_id}/creations/generate",
        json={"topicId": topic_id, "targetPlatform": "小红书"},
        headers=headers,
    )
    creation_payload = creation.json()
    creation_id = creation_payload["creationId"]
    creation_state = {
        "version": 1,
        "linkReference": {"url": "https://example.test/post", "title": "参考内容"},
        "promptJobId": "gj_prompt",
        "imageJobIds": ["gj_image"],
        "activeImageJobId": "gj_image",
        "imageGroups": [
            {
                "slotId": "slot_1",
                "variants": [{"variantId": "v1", "url": "https://cdn.example.test/a.png"}],
            }
        ],
        "selectedVariants": {"slot_1": "v1"},
        "ratio": "3:4",
        "countMode": "same",
    }

    submitted = client.post(
        f"/api/v1/accounts/{account_id}/creations/{creation_id}/submit-task",
        json={
            "topicId": topic_id,
            "targetPlatform": "小红书",
            "type": "image",
            "content": creation_payload["content"],
            "creationState": creation_state,
        },
        headers=headers,
    )

    assert submitted.status_code == 200
    persisted = client.get(f"/api/v1/accounts/{account_id}/creations/{creation_id}", headers=headers)
    assert persisted.status_code == 200
    assert persisted.json()["creationState"] == creation_state


def test_accounts_include_platform_and_created_account_preserves_it():
    client = TestClient(app)
    headers = auth_headers(client)

    accounts = client.get("/api/v1/accounts", headers=headers)
    assert accounts.status_code == 200
    assert {account["platform"] for account in accounts.json()} >= {"小红书", "抖音", "视频号"}

    created = client.post(
        "/api/v1/accounts",
        json={
            "name": "视频号增长号",
            "description": "视频号内容运营",
            "purpose": "私域转化",
            "type": "专业号",
            "platform": "视频号",
            "accountLinks": {"视频号": "https://channels.weixin.qq.com/profile/growth"},
        },
        headers=headers,
    )
    assert created.status_code == 200
    assert created.json()["platform"] == "视频号"


def test_accounts_support_paginated_search_and_platform_filter():
    client = TestClient(app)
    headers = auth_headers(client)
    unique_keyword = f"分页搜索{uuid4().hex[:8]}"

    created = client.post(
        "/api/v1/accounts",
        json={
            "name": f"{unique_keyword}账号",
            "description": "用于分页搜索测试",
            "purpose": "验证账号列表分页",
            "type": "专业号",
            "platforms": ["快手"],
            "accountLinks": {"快手": f"https://www.kuaishou.com/profile/{unique_keyword}"},
        },
        headers=headers,
    )
    assert created.status_code == 200
    created_id = created.json()["id"]

    first_page = client.get("/api/v1/accounts?page=1&pageSize=2", headers=headers)
    assert first_page.status_code == 200
    payload = first_page.json()
    assert payload["total"] >= 3
    assert payload["page"] == 1
    assert payload["pageSize"] == 2
    assert len(payload["items"]) == 2

    unique_search = client.get(f"/api/v1/accounts?page=1&pageSize=100&keyword={unique_keyword}", headers=headers)
    assert unique_search.status_code == 200
    unique_payload = unique_search.json()
    assert unique_payload["total"] >= 1
    assert any(item["id"] == created_id for item in unique_payload["items"])

    platform_filtered = client.get("/api/v1/accounts?page=1&pageSize=100&platform=快手", headers=headers)
    assert platform_filtered.status_code == 200
    platform_payload = platform_filtered.json()
    assert platform_payload["total"] >= 1
    assert any(item["id"] == created_id for item in platform_payload["items"])
    assert all("快手" in item["platforms"] for item in platform_payload["items"])


def test_created_account_can_preserve_multiple_platforms():
    client = TestClient(app)
    headers = auth_headers(client)

    created = client.post(
        "/api/v1/accounts",
        json={
            "name": "多平台增长号",
            "description": "多平台内容运营",
            "purpose": "全域增长",
            "type": "专业号",
            "platforms": ["小红书", "抖音"],
            "accountLinks": {
                "小红书": "https://www.xiaohongshu.com/user/profile/growth",
                "抖音": "https://www.douyin.com/user/growth",
            },
        },
        headers=headers,
    )
    assert created.status_code == 200
    assert created.json()["platforms"] == ["小红书", "抖音"]
    assert created.json()["platform"] == "小红书"


def test_account_profile_can_be_updated_with_publish_settings():
    client = TestClient(app)
    headers = auth_headers(client)

    created = client.post(
        "/api/v1/accounts",
        json={
            "name": "待编辑账号",
            "description": "旧定位",
            "purpose": "旧目标",
            "type": "普通号",
            "platforms": ["小红书"],
            "accountLinks": {"小红书": "https://www.xiaohongshu.com/user/profile/old"},
            "industry": "旧行业",
            "productService": "旧产品",
            "targetCity": "上海",
            "targetAudience": "旧人群",
            "conversionGoal": "旧转化",
        },
        headers=headers,
    )
    assert created.status_code == 200
    account_id = created.json()["id"]

    updated = client.patch(
        f"/api/v1/accounts/{account_id}",
        json={
            "name": "编辑后账号",
            "description": "新定位",
            "purpose": "新目标",
            "type": "专业号",
            "platforms": ["小红书", "抖音"],
            "accountLinks": {
                "小红书": "https://www.xiaohongshu.com/user/profile/new",
                "抖音": "https://www.douyin.com/user/new",
            },
            "publishSettings": {
                "小红书": {"androidId": "android-xhs"},
                "抖音": {"androidId": "android-dy"},
            },
            "industry": "美妆护肤",
            "productService": "抗氧精华",
            "targetCity": "杭州",
            "targetAudience": "25-35岁白领女性",
            "conversionGoal": "留资转化",
        },
        headers=headers,
    )

    assert updated.status_code == 200
    payload = updated.json()
    assert payload["name"] == "编辑后账号"
    assert payload["platforms"] == ["小红书", "抖音"]
    assert payload["accountLinks"]["抖音"] == "https://www.douyin.com/user/new"
    assert payload["publishSettings"] == {
        "小红书": {"androidId": "android-xhs", "platform": "xhs"},
        "抖音": {"androidId": "android-dy", "platform": "douyin"},
    }
    assert payload["industry"] == "美妆护肤"


def test_tasks_materials_dashboard_and_report():
    client = TestClient(app)
    headers = auth_headers(client)
    account_id = create_isolated_account(client, headers)

    task = client.post(
        f"/api/v1/accounts/{account_id}/tasks",
        json={"title": "测试任务", "type": "video", "targetPlatform": "抖音"},
        headers=headers,
    )
    assert task.status_code == 200
    assert task.json()["targetPlatform"] == "抖音"

    materials = client.get(f"/api/v1/accounts/{account_id}/materials", headers=headers)
    assert materials.status_code == 200
    assert isinstance(materials.json(), list)

    dashboard = client.get(f"/api/v1/accounts/{account_id}/dashboard", headers=headers)
    assert dashboard.status_code == 200
    assert "views" in dashboard.json()

    report = client.get(f"/api/v1/accounts/{account_id}/report", headers=headers)
    assert report.status_code == 200
    assert "competitors" in report.json()
    assert report.json()["similarAccounts"] == []
    assert report.json()["targetUserProfile"] == {}
    assert report.json()["reportVersion"] == 0
    assert report.json()["generatedAt"] is None


def test_registration_is_disabled_and_login_me_still_works():
    client = TestClient(app)
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "new-user@starx.ai", "password": "secret88", "nickname": "新用户"},
    )
    assert registered.status_code == 404

    login = client.post("/api/v1/auth/login", json={"email": "demo@starx.ai", "password": "demo123"})
    assert login.status_code == 200
    token = login.json()["accessToken"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "demo@starx.ai"


def test_knowledge_base_crud_and_account_binding_flow():
    client = TestClient(app)
    headers = auth_headers(client)

    created_kb = client.post(
        "/api/v1/knowledge-bases",
        json={
            "name": "美妆品牌基础库",
            "productName": "星颜精华",
            "industry": "美妆护肤",
            "productIntro": "主打抗氧修护。",
            "brandStory": "来自实验室护肤研发团队。",
            "price": "299元",
            "logoUrl": "https://cdn.example.com/logo.png",
            "imageMaterials": ["https://cdn.example.com/kv-1.png"],
            "contactInfo": "VX: starx-service",
            "websiteUrl": "https://brand.example.com",
            "enabledFields": {
                "productIntro": True,
                "brandStory": True,
                "price": True,
                "logoUrl": True,
                "imageMaterials": True,
                "contactInfo": True,
                "websiteUrl": True,
            },
        },
        headers=headers,
    )
    assert created_kb.status_code == 200
    created_kb_payload = created_kb.json()
    knowledge_base_id = created_kb_payload["id"]
    assert created_kb_payload["name"] == "美妆品牌基础库"
    assert created_kb_payload["industry"] == "美妆护肤"

    updated_kb = client.patch(
        f"/api/v1/knowledge-bases/{knowledge_base_id}",
        json={
            "industry": "功效护肤",
            "enabledFields": {
                "productIntro": True,
                "brandStory": False,
                "price": True,
                "logoUrl": True,
                "imageMaterials": True,
                "contactInfo": True,
                "websiteUrl": False,
            }
        },
        headers=headers,
    )
    assert updated_kb.status_code == 200
    assert updated_kb.json()["industry"] == "功效护肤"
    assert updated_kb.json()["enabledFields"]["brandStory"] is False

    created_account = client.post(
        "/api/v1/accounts",
        json={
            "name": "星颜小红书主号",
            "description": "专注功效护肤种草",
            "purpose": "私域转化",
            "type": "专业号",
            "platforms": ["小红书", "抖音"],
            "accountLinks": {
                "小红书": "https://www.xiaohongshu.com/user/profile/abc",
                "抖音": "https://www.douyin.com/user/abc",
            },
            "industry": "美妆护肤",
            "productService": "抗氧修护精华",
            "targetCity": "上海",
            "targetAudience": "25-35岁白领女性",
            "conversionGoal": "留资到店",
            "knowledgeBaseId": knowledge_base_id,
        },
        headers=headers,
    )
    assert created_account.status_code == 200
    created_account_payload = created_account.json()
    assert created_account_payload["knowledgeBaseId"] == knowledge_base_id
    assert created_account_payload["knowledgeBaseSummary"]["id"] == knowledge_base_id
    assert created_account_payload["knowledgeBaseSummary"]["name"] == "美妆品牌基础库"
    assert created_account_payload["knowledgeBaseSummary"]["productName"] == "星颜精华"
    assert created_account_payload["accountLinks"]["抖音"].startswith("https://")
    assert created_account_payload["industry"] == "美妆护肤"
    assert created_account_payload["productService"] == "抗氧修护精华"
    assert created_account_payload["targetCity"] == "上海"
    assert created_account_payload["targetAudience"] == "25-35岁白领女性"
    assert created_account_payload["conversionGoal"] == "留资到店"

    kb_list = client.get("/api/v1/knowledge-bases", headers=headers)
    assert kb_list.status_code == 200
    kb_list_payload = kb_list.json()
    listed_knowledge_base = next(
        item for item in kb_list_payload["items"] if item["id"] == knowledge_base_id
    )
    assert listed_knowledge_base["industry"] == "功效护肤"
    assert kb_list_payload["page"] == 1
    assert kb_list_payload["pageSize"] == 20
    assert kb_list_payload["total"] >= 1

    kb_detail = client.get(f"/api/v1/knowledge-bases/{knowledge_base_id}", headers=headers)
    assert kb_detail.status_code == 200
    assert kb_detail.json()["id"] == knowledge_base_id
    assert kb_detail.json()["industry"] == "功效护肤"

    cleared_industry = client.patch(
        f"/api/v1/knowledge-bases/{knowledge_base_id}",
        json={"industry": ""},
        headers=headers,
    )
    assert cleared_industry.status_code == 200
    assert cleared_industry.json()["industry"] == ""
    reopened_kb = client.get(
        f"/api/v1/knowledge-bases/{knowledge_base_id}", headers=headers
    )
    assert reopened_kb.status_code == 200
    assert reopened_kb.json()["industry"] == ""


def test_knowledge_base_list_supports_pagination_and_keyword_filter():
    client = TestClient(app)
    headers = auth_headers(client)
    created_ids = []

    try:
        for index in range(3):
            created = client.post(
                "/api/v1/knowledge-bases",
                json={
                    "name": f"分页测试知识库 {index}",
                    "productName": f"分页产品 {index}",
                    "enabledFields": {"productIntro": True},
                },
                headers=headers,
            )
            assert created.status_code == 200
            assert created.json()["industry"] == ""
            created_ids.append(created.json()["id"])

        first_page = client.get("/api/v1/knowledge-bases?page=1&pageSize=2&keyword=分页测试", headers=headers)
        assert first_page.status_code == 200
        first_payload = first_page.json()
        assert first_payload["page"] == 1
        assert first_payload["pageSize"] == 2
        assert first_payload["total"] >= 3
        assert len(first_payload["items"]) == 2
        assert all("分页测试" in item["name"] for item in first_payload["items"])

        second_page = client.get("/api/v1/knowledge-bases?page=2&pageSize=2&keyword=分页测试", headers=headers)
        assert second_page.status_code == 200
        second_payload = second_page.json()
        assert second_payload["page"] == 2
        assert second_payload["pageSize"] == 2
        assert len(second_payload["items"]) >= 1
        assert {item["id"] for item in first_payload["items"]}.isdisjoint(
            {item["id"] for item in second_payload["items"]}
        )
    finally:
        for knowledge_base_id in created_ids:
            client.delete(f"/api/v1/knowledge-bases/{knowledge_base_id}", headers=headers)


def test_account_creation_rejects_missing_platform_links():
    client = TestClient(app)
    headers = auth_headers(client)

    created = client.post(
        "/api/v1/accounts",
        json={
            "name": "多平台账号",
            "description": "内容运营",
            "purpose": "获客",
            "type": "普通号",
            "platforms": ["小红书", "抖音"],
            "accountLinks": {"小红书": "https://www.xiaohongshu.com/user/profile/demo"},
            "industry": "教育",
            "productService": "课程服务",
            "targetCity": "杭州",
            "targetAudience": "家长",
            "conversionGoal": "加企微",
        },
        headers=headers,
    )

    assert created.status_code == 400
    assert "platform" in created.json()["detail"]


def test_account_creation_rejects_non_owner_knowledge_base():
    client = TestClient(app)
    owner_headers = auth_headers(client)

    knowledge_base = client.post(
        "/api/v1/knowledge-bases",
        json={
            "name": "私有知识库",
            "productName": "异地主体产品",
            "productIntro": "不应被他人绑定。",
            "brandStory": "",
            "price": "",
            "logoUrl": "",
            "imageMaterials": [],
            "contactInfo": "",
            "websiteUrl": "",
            "enabledFields": {
                "productIntro": True,
                "brandStory": False,
                "price": False,
                "logoUrl": False,
                "imageMaterials": False,
                "contactInfo": False,
                "websiteUrl": False,
            },
        },
        headers=owner_headers,
    )
    assert knowledge_base.status_code == 200
    knowledge_base_id = knowledge_base.json()["id"]

    with SessionLocal() as session:
        existing = session.get(UserRecord, "user_other")
        if existing is None:
            session.add(
                UserRecord(
                    id="user_other",
                    email="other-owner@starx.ai",
                    password_hash=get_password_hash("demo123"),
                    nickname="其他用户",
                    status="active",
                )
            )
            session.commit()

    other_login = client.post(
        "/api/v1/auth/login",
        json={"email": "other-owner@starx.ai", "password": "demo123"},
    )
    assert other_login.status_code == 200
    other_headers = {"Authorization": f"Bearer {other_login.json()['accessToken']}"}

    created = client.post(
        "/api/v1/accounts",
        json={
            "name": "越权绑定账号",
            "description": "尝试绑定他人知识库",
            "purpose": "获客",
            "type": "普通号",
            "platforms": ["视频号"],
            "accountLinks": {"视频号": "https://channels.weixin.qq.com/profile/demo"},
            "industry": "教育",
            "productService": "课程服务",
            "targetCity": "杭州",
            "targetAudience": "家长",
            "conversionGoal": "留资",
            "knowledgeBaseId": knowledge_base_id,
        },
        headers=other_headers,
    )

    assert created.status_code == 400
    assert "knowledge" in created.json()["detail"].lower()


def test_cannot_delete_bound_knowledge_base():
    client = TestClient(app)
    headers = auth_headers(client)

    kb_response = client.post(
        "/api/v1/knowledge-bases",
        json={
            "name": "门店服务库",
            "productName": "探店套餐",
            "productIntro": "双人体验套餐",
            "brandStory": "老店升级品牌化运营",
            "price": "198元",
            "logoUrl": "",
            "imageMaterials": [],
            "contactInfo": "400-800-9000",
            "websiteUrl": "",
            "enabledFields": {
                "productIntro": True,
                "brandStory": True,
                "price": True,
                "logoUrl": False,
                "imageMaterials": False,
                "contactInfo": True,
                "websiteUrl": False,
            },
        },
        headers=headers,
    )
    assert kb_response.status_code == 200
    kb = kb_response.json()

    account = client.post(
        "/api/v1/accounts",
        json={
            "name": "视频号探店号",
            "description": "面向本地生活探店",
            "purpose": "门店核销",
            "type": "普通号",
            "platforms": ["视频号"],
            "accountLinks": {"视频号": "https://channels.weixin.qq.com/profile/demo"},
            "industry": "餐饮",
            "productService": "双人餐套餐",
            "targetCity": "深圳",
            "targetAudience": "附近3公里白领",
            "conversionGoal": "到店核销",
            "knowledgeBaseId": kb["id"],
        },
        headers=headers,
    )
    assert account.status_code == 200

    deleted = client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=headers)
    assert deleted.status_code == 400
    assert "bound" in deleted.json()["detail"].lower()
