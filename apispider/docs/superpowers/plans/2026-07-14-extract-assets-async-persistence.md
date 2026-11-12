# 链接解析资源异步持久化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 链接解析阶段只返回第三方媒体地址，用户显式保存后立即写入流程与可选脚本素材，并由后台工作流异步转存当前解析记录的全部图片和视频。

**Architecture:** 解析服务只规范化外链；保存编排服务在同一事务中写入业务记录和 `asset_persistence` 工作流；独立持久化服务负责下载、OSS 上传、重新解析重试、降级和 URL 原子回写。前端通过明确的保存意图区分自动保存与用户显式保存。

**Tech Stack:** Python 3.11+、FastAPI、SQLAlchemy 2、Alembic、Pydantic 2、requests、现有 WorkflowScheduler、React 18、Node Test Runner。

## Global Constraints

- 设计文档和实施说明使用中文。
- 后端 Python 命令必须使用名为 `starx` 的 conda 环境。
- 解析阶段不得请求媒体文件或写入 OSS。
- 每次保存只处理当前解析历史，且处理其中全部图片和视频。
- 保存接口立即返回；首轮失败后重新解析原链接并完整重试一次；第二轮失败保留原链接。
- 不引入 Celery、Redis 队列或新的外部基础设施。
- 网络、重试和 OSS 代码不得放入 `app/services/db_service.py`。

---

## 文件结构

- `app/services/extract_service/reference_service.py`：解析结果规范化，不执行媒体 I/O。
- `app/services/extract_service/asset_persistence.py`：媒体下载、校验、幂等上传、清理和两轮转存算法。
- `app/services/workflow/workflows/asset_persistence.py`：后台工作流编排与业务状态回写。
- `app/services/creation_save_service.py`：显式保存事务，协调任务、素材和后台工作流记录。
- `app/services/workflow/workflow_store.py`：短 Session 的持久化查询与 URL 映射回写。
- `app/api/routes/creations.py`：保存接口和调度边界。
- `app/api/routes/extract.py`：返回解析历史 ID。
- `app/db/models.py` 与 Alembic：解析持久化状态和素材资源字段。
- `../starx-frontend/src/pages/ContentCreation.jsx`：区分自动保存、流程保存和脚本素材保存。
- `../starx-frontend/src/hooks/useStarxApp.js`：提交新保存契约并更新本地状态。

### Task 1: 解析阶段移除下载与 OSS 写入

**Files:**
- Modify: `app/services/extract_service/reference_service.py`
- Modify: `app/schemas/extract.py`
- Modify: `app/api/routes/extract.py`
- Test: `tests/test_extract_service.py`
- Test: `tests/test_extract_api.py`

**Interfaces:**
- Produces: `ExtractReferenceService.extract_from_text(share_text: str) -> dict[str, Any]`，媒体项的 `url == sourceUrl`、`storageStatus == "external"`。
- Produces: `ExtractLinkResponse.historyId: str | None`。
- Produces: `_save_history(session: Session, user_id: str, result: ExtractLinkResponse, payload: ExtractLinkRequest) -> str | None`。

- [ ] **Step 1: 写解析阶段零媒体 I/O 的失败测试**

```python
def test_extract_reference_returns_external_media_without_download_or_upload():
    storage = FakeStorage()
    media_session = FakeSession()
    service = ExtractReferenceService(
        extractor=FakeExtractor(),
        storage=storage,
        media_session=media_session,
    )

    result = service.extract_from_text("看看 https://v.douyin.com/xdSvtgg4xpo/")

    assert result["images"][0] == {
        "sourceUrl": "https://source.example.test/cover.webp",
        "url": "https://source.example.test/cover.webp",
        "contentType": "",
        "kind": "image",
        "storageStatus": "external",
    }
    assert result["videos"][0]["url"] == "https://source.example.test/video.mp4"
    assert media_session.requests == []
    assert storage.uploads == []
```

- [ ] **Step 2: 运行测试并确认因仍会下载上传而失败**

Run: `conda run -n starx pytest tests/test_extract_service.py::test_extract_reference_returns_external_media_without_download_or_upload -v`

Expected: FAIL，实际 URL 仍为 OSS URL或媒体 Session 被调用。

- [ ] **Step 3: 最小化解析服务为纯规范化逻辑**

```python
def _external_media_list(source_urls: list[str], *, kind: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for source_url in source_urls:
        if len(items) >= settings.max_extract_media_items:
            break
        clean_url = str(source_url or "").strip()
        if not clean_url or clean_url in seen:
            continue
        seen.add(clean_url)
        items.append({
            "sourceUrl": clean_url,
            "url": clean_url,
            "contentType": "",
            "kind": kind,
            "storageStatus": "external",
        })
    return items
```

`extract_from_text()` 使用 `_external_media_list()` 生成 `images` 和 `videos`，删除解析路径对 `_upload_media_list()` 的调用；下载帮助函数迁移到 Task 3 的新模块后再从本文件删除。

- [ ] **Step 4: 写并通过 API historyId 测试**

```python
def test_extract_link_reference_api_returns_history_id_and_external_urls():
    response = client.post("/api/v1/extract/link-reference", json={"text": SHARE_TEXT}, headers=headers)
    payload = response.json()
    assert response.status_code == 200
    assert payload["historyId"].startswith("eh_")
    assert payload["images"][0]["url"] == "https://source.example.test/cover.webp"
    assert payload["images"][0]["storageStatus"] == "external"
```

实现 `ExtractedMediaSchema.storageStatus`、`ExtractLinkResponse.historyId`，让 `_save_history()` 在成功提交后返回记录 ID；数据库写入失败时返回 `None`。

- [ ] **Step 5: 运行解析测试**

Run: `conda run -n starx pytest tests/test_extract_service.py tests/test_extract_api.py -v`

Expected: PASS。

- [ ] **Step 6: 提交后端解析改造**

```bash
git add app/services/extract_service/reference_service.py app/schemas/extract.py app/api/routes/extract.py tests/test_extract_service.py tests/test_extract_api.py
git commit -m "refactor: keep extracted media on source urls"
```

### Task 2: 增加持久化状态与素材资源数据模型

**Files:**
- Create: `alembic/versions/20260714_000018_extract_asset_persistence.py`
- Modify: `app/db/models.py`
- Modify: `app/models/material.py`
- Modify: `app/schemas/materials.py`
- Modify: `app/schemas/extract.py`
- Modify: `app/services/db_service.py`
- Test: `tests/test_database_init.py`

**Interfaces:**
- Produces: `ExtractHistoryRecord.persistence_status/persistence_job_id/persistence_error/persisted_at/media_url_map`。
- Produces: `MaterialRecord.assets` 与 `Material.assets`。

- [ ] **Step 1: 写模型默认值失败测试**

```python
def test_extract_history_and_material_asset_persistence_defaults():
    history = ExtractHistoryRecord(id="eh_defaults", user_id="u1", url="https://example.test/post")
    material = MaterialRecord(
        id="m_defaults", account_id="acc1", name="脚本", material_type="script",
        tags=[], material_date="2026-07-14", thumb="📝",
    )
    assert history.persistence_status == "external"
    assert history.media_url_map == {}
    assert material.assets == []
```

- [ ] **Step 2: 运行并确认字段缺失**

Run: `conda run -n starx pytest tests/test_database_init.py::test_extract_history_and_material_asset_persistence_defaults -v`

Expected: FAIL with `AttributeError`。

- [ ] **Step 3: 添加 ORM 字段与迁移**

```python
# ExtractHistoryRecord
persistence_status: Mapped[str] = mapped_column(String(16), nullable=False, default="external")
persistence_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
persistence_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
persisted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
media_url_map: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)

# MaterialRecord
assets: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
```

迁移 revision 固定为 `20260714_000018`、down revision 为 `20260708_000017`，为非空 JSON/字符串字段设置服务端默认值后移除默认值。

- [ ] **Step 4: 扩展素材模型和数据库映射**

```python
@dataclass
class Material:
    id: str
    name: str
    type: str
    tags: list[str]
    date: str
    thumb: str
    assets: list[dict[str, object]]
```

`DBService.create_material(user_id: str, account_id: str, name: str, material_type: str, tags: list[str], thumb: str, assets: list[dict[str, object]] | None = None) -> Material` 写入 `assets`；`list_materials()` 和 `MaterialSchema` 返回该字段，旧调用默认传空列表。

- [ ] **Step 5: 验证迁移和模型测试**

Run: `conda run -n starx alembic upgrade head`

Expected: 数据库升级到 `20260714_000018`。

Run: `conda run -n starx pytest tests/test_database_init.py tests/test_api_flows.py -v`

Expected: PASS。

- [ ] **Step 6: 提交数据模型**

```bash
git add alembic/versions/20260714_000018_extract_asset_persistence.py app/db/models.py app/models/material.py app/schemas/materials.py app/schemas/extract.py app/services/db_service.py tests/test_database_init.py
git commit -m "feat: store extracted asset persistence state"
```

### Task 3: 实现可测试的资源转存算法

**Files:**
- Create: `app/services/extract_service/asset_persistence.py`
- Create: `tests/test_asset_persistence.py`

**Interfaces:**
- Produces: `AssetPersistenceResult(status: str, assets: list[dict[str, str]], url_map: dict[str, str], retry_count: int, error: str)`。
- Produces: `ExtractAssetPersistenceService.persist(history: ExtractHistorySnapshot) -> AssetPersistenceResult`。
- Consumes: 平台解析器 `extract(url: str) -> dict`、对象存储 `put_bytes/delete_object/public_url`。

- [ ] **Step 1: 写首轮成功和稳定对象键失败测试**

```python
def test_persist_uploads_all_media_with_stable_keys():
    storage = FakeStorage()
    service = ExtractAssetPersistenceService(storage=storage, media_session=FakeSession(), extractor=FakeExtractor())
    result = service.persist(history_snapshot())
    assert result.status == "completed"
    assert result.retry_count == 0
    assert set(result.url_map) == {
        "https://source.example.test/cover.webp",
        "https://source.example.test/video.mp4",
    }
    assert storage.keys == [
        "extract/acc1/eh_1/image/" + sha256_url("https://source.example.test/cover.webp") + ".webp",
        "extract/acc1/eh_1/video/" + sha256_url("https://source.example.test/video.mp4") + ".mp4",
    ]
```

- [ ] **Step 2: 运行并确认模块不存在**

Run: `conda run -n starx pytest tests/test_asset_persistence.py::test_persist_uploads_all_media_with_stable_keys -v`

Expected: ERROR with `ModuleNotFoundError`。

- [ ] **Step 3: 实现首轮下载、限制校验和上传**

```python
@dataclass(frozen=True)
class ExtractHistorySnapshot:
    id: str
    account_id: str
    source_url: str
    platform: str
    images: list[dict[str, str]]
    videos: list[dict[str, str]]

@dataclass(frozen=True)
class AssetPersistenceResult:
    status: str
    assets: list[dict[str, str]]
    url_map: dict[str, str]
    retry_count: int
    error: str = ""

class ExtractAssetPersistenceService:
    def persist(self, history: ExtractHistorySnapshot) -> AssetPersistenceResult:
        try:
            return self._persist_once(history, retry_count=0)
        except AssetPersistenceError as first_error:
            refreshed = self._refresh_snapshot(history)
            try:
                return self._persist_once(refreshed, retry_count=1)
            except AssetPersistenceError as second_error:
                return self._fallback(history, first_error, second_error)
```

下载逻辑从原 `reference_service.py` 迁移 `_clean_content_type()` 与 `_read_response_limited()`；每个响应同时校验响应头和流式字节数，类型白名单沿用现有集合。

- [ ] **Step 4: 写重试、降级、清理和幂等测试**

```python
def test_persist_reextracts_original_link_then_succeeds():
    service, storage, extractor = retrying_service(first_round_error="expired")
    result = service.persist(history_snapshot())
    assert result.status == "completed"
    assert result.retry_count == 1
    assert extractor.urls == ["https://v.douyin.com/source/"]
    assert len(storage.put_calls) == 2

def test_persist_falls_back_to_original_urls_after_second_failure():
    service = always_failing_service()
    result = service.persist(history_snapshot())
    assert result.status == "fallback"
    assert result.retry_count == 1
    assert result.url_map[SOURCE_IMAGE] == SOURCE_IMAGE
    assert result.url_map[SOURCE_VIDEO] == SOURCE_VIDEO
    assert "second round failed" in result.error

def test_persist_deletes_new_objects_when_round_partially_fails():
    service, storage = partial_failure_service()
    result = service.persist(history_snapshot())
    assert result.status == "fallback"
    assert storage.delete_calls == storage.new_keys_from_failed_rounds

def test_persist_reuses_existing_url_map_without_media_requests():
    service, media_session = service_with_existing_map({SOURCE_IMAGE: OSS_IMAGE, SOURCE_VIDEO: OSS_VIDEO})
    result = service.persist(history_snapshot())
    assert result.status == "completed"
    assert result.url_map == {SOURCE_IMAGE: OSS_IMAGE, SOURCE_VIDEO: OSS_VIDEO}
    assert media_session.requests == []

@pytest.mark.parametrize("url", ["file:///tmp/a.png", "ftp://example.test/a.png", "javascript:alert(1)"])
def test_persist_rejects_non_http_media_urls(url):
    service = service_for_single_image(url)
    result = service.persist(history_snapshot(images=[media(url, "image")], videos=[]))
    assert result.status == "fallback"
    assert "HTTP or HTTPS" in result.error

def test_persist_rejects_oversized_streamed_media(monkeypatch):
    monkeypatch.setattr(settings, "max_extract_media_bytes", 4)
    service = service_for_stream([b"123", b"45"])
    result = service.persist(history_snapshot(images=[media(SOURCE_IMAGE, "image")], videos=[]))
    assert result.status == "fallback"
    assert "exceeds" in result.error
```

每个测试使用显式 Fake 记录调用次数，并分别断言 `retry_count`、`status`、删除键和最终 URL。

- [ ] **Step 5: 运行资源服务测试**

Run: `conda run -n starx pytest tests/test_asset_persistence.py -v`

Expected: PASS。

- [ ] **Step 6: 提交资源服务**

```bash
git add app/services/extract_service/asset_persistence.py tests/test_asset_persistence.py
git commit -m "feat: persist extracted assets with fallback"
```

### Task 4: 接入非 AI 后台工作流和 URL 原子回写

**Files:**
- Create: `app/services/workflow/workflows/asset_persistence.py`
- Modify: `app/services/workflow/workflows/base.py`
- Modify: `app/services/workflow/scheduler.py`
- Modify: `app/services/workflow/__init__.py`
- Modify: `app/services/workflow/workflow_store.py`
- Test: `tests/test_workflow_scheduler.py`
- Test: `tests/test_asset_persistence_workflow.py`

**Interfaces:**
- Produces: `BaseWorkflow.requires_ai: ClassVar[bool] = True`。
- Produces: `AssetPersistenceWorkflow.type == "asset_persistence"` 且 `requires_ai == False`。
- Produces: `WorkflowStore.load_asset_persistence_context(workflow_id)`。
- Produces: `WorkflowStore.apply_asset_url_map(workflow_id, result)`。

- [ ] **Step 1: 写空 AI Token 仍执行资源工作流的失败测试**

```python
@WorkflowRegister.register
class NoAiWorkflow(BaseWorkflow):
    type = "test_no_ai"
    requires_ai = False
    async def execute(self):
        return {"ok": True}

def test_scheduler_runs_non_ai_workflow_without_ai_token():
    scheduler = WorkflowScheduler(ai_service=SimpleNamespace(token=""), store=store, use_default_concurrency=False)
    scheduler.submit("test_no_ai", "wf_no_ai")
    wait_for_workflow(scheduler, "wf_no_ai")
    assert store.completed["wf_no_ai"] == {"ok": True}
```

- [ ] **Step 2: 运行并确认调度器错误标记任务失败**

Run: `conda run -n starx pytest tests/test_workflow_scheduler.py::test_scheduler_runs_non_ai_workflow_without_ai_token -v`

Expected: FAIL，任务被 `TOKEN_MISSING_ERROR` 标记失败。

- [ ] **Step 3: 让调度器按能力检查 AI Token**

```python
class BaseWorkflow:
    requires_ai: ClassVar[bool] = True

# WorkflowScheduler._execute
if workflow_class.requires_ai and getattr(self._ai_service, "token", None) == "":
    self._store.mark_failed(workflow_id, TOKEN_MISSING_ERROR, record_class=workflow_class.record_class)
    return
```

- [ ] **Step 4: 写工作流成功与降级回写失败测试**

```python
async def test_asset_persistence_workflow_applies_completed_url_map():
    result = await workflow.execute()
    assert result["persistenceStatus"] == "completed"
    assert store.applied_result.url_map[SOURCE_IMAGE] == OSS_IMAGE

async def test_asset_persistence_workflow_applies_fallback_state_without_replacing_urls():
    result = await workflow.execute()
    assert result["persistenceStatus"] == "fallback"
    assert store.applied_result.url_map[SOURCE_IMAGE] == SOURCE_IMAGE
```

- [ ] **Step 5: 实现工作流与作用域内 URL 替换**

`WorkflowStore.apply_asset_url_map()` 在一个短事务中加载工作流指定的解析历史、创作、素材和同创作视频分析工作流。使用纯函数递归替换字符串值，只替换 `url_map` 中的完整字符串，不对普通正文做子串替换；同时更新解析历史的状态、错误、映射和完成时间。

```python
def replace_exact_urls(value: Any, url_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        return url_map.get(value, value)
    if isinstance(value, list):
        return [replace_exact_urls(item, url_map) for item in value]
    if isinstance(value, dict):
        return {key: replace_exact_urls(item, url_map) for key, item in value.items()}
    return value
```

- [ ] **Step 6: 运行调度与工作流测试**

Run: `conda run -n starx pytest tests/test_workflow_scheduler.py tests/test_asset_persistence_workflow.py -v`

Expected: PASS。

- [ ] **Step 7: 提交后台工作流**

```bash
git add app/services/workflow/workflows/asset_persistence.py app/services/workflow/workflows/base.py app/services/workflow/scheduler.py app/services/workflow/__init__.py app/services/workflow/workflow_store.py tests/test_workflow_scheduler.py tests/test_asset_persistence_workflow.py
git commit -m "feat: run extracted asset persistence in background"
```

### Task 5: 原子保存流程、脚本素材与持久化任务

**Files:**
- Create: `app/services/creation_save_service.py`
- Modify: `app/schemas/creations.py`
- Modify: `app/api/routes/creations.py`
- Modify: `app/services/db_service.py`
- Test: `tests/test_api_flows.py`
- Test: `tests/test_extract_api.py`

**Interfaces:**
- Produces: `SubmitCreationTaskRequest.extractHistoryId/linkReference/saveScriptMaterial/persistExtractAssets`。
- Produces: `SubmitCreationTaskResponse(task, material, assetPersistence)`。
- Produces: `CreationSaveService.save(user_id: str, account_id: str, creation_id: str, payload: SubmitCreationTaskRequest) -> CreationSaveResult`。

- [ ] **Step 1: 写自动保存不创建后台任务的失败测试**

```python
def test_creation_auto_save_does_not_create_asset_persistence_workflow():
    response = submit_creation(client, headers, persistExtractAssets=False)
    assert response.status_code == 200
    assert response.json()["assetPersistence"] is None
    assert session.scalar(select(func.count()).select_from(WorkflowRecord).where(WorkflowRecord.type == "asset_persistence")) == 0
```

- [ ] **Step 2: 写显式保存立即创建 pending 工作流的失败测试**

```python
def test_explicit_save_persists_task_and_pending_asset_workflow_before_dispatch():
    response = submit_creation(
        client, headers,
        persistExtractAssets=True,
        extractHistoryId=history_id,
        linkReference=link_reference,
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["task"]["creationId"] == creation_id
    assert payload["assetPersistence"]["status"] == "pending"
    assert payload["assetPersistence"]["historyId"] == history_id
```

- [ ] **Step 3: 实现保存请求与响应模型**

```python
class SubmitCreationTaskRequest(BaseModel):
    topicId: str = ""
    targetPlatform: str
    type: str
    content: CreationContentSchema
    creationState: dict[str, object] = Field(default_factory=dict)
    assignee: str = ""
    dueDate: str = ""
    priority: str = "normal"
    status: str = "draft"
    handoffNote: str = ""
    persistExtractAssets: bool = False
    extractHistoryId: str | None = None
    linkReference: ExtractLinkResponse | None = None
    saveScriptMaterial: bool = False

class AssetPersistenceSummarySchema(BaseModel):
    jobId: str
    historyId: str
    status: str
    error: str = ""

class SubmitCreationTaskResponse(BaseModel):
    task: TaskSchema
    material: MaterialSchema | None = None
    assetPersistence: AssetPersistenceSummarySchema | None = None
```

- [ ] **Step 4: 实现 `CreationSaveService` 单事务编排**

服务验证账号和当前历史归属；历史缺失但有 `linkReference` 时补建历史；将当前历史全部媒体合并进创作 `assets`；按 `saveScriptMaterial` 创建素材；创建或复用 `asset_persistence` 工作流并在 `creationState.assetPersistence` 写入 pending。`DBService.submit_creation_task()` 拆出不提交的内部写入方法，最终只由编排服务提交一次。

- [ ] **Step 5: 写脚本素材、越权和单历史范围测试**

```python
def test_save_script_material_also_saves_workflow_and_all_current_media():
    response = submit_explicit_save(save_script_material=True, history_id="eh_current")
    payload = response.json()
    assert payload["task"]["creationId"] == CREATION_ID
    assert payload["material"]["type"] == "script"
    assert [item["kind"] for item in payload["material"]["assets"]] == ["image", "video"]

def test_explicit_save_rejects_extract_history_owned_by_another_user():
    response = submit_explicit_save(history_id="eh_other_user")
    assert response.status_code == 404
    assert response.json()["detail"] == "extract history is not available"

def test_explicit_save_uses_only_requested_history_when_creation_has_multiple_histories():
    response = submit_explicit_save(history_id="eh_current")
    persisted = get_creation(response.json()["task"]["creationId"])
    urls = [item["sourceUrl"] for item in persisted["content"]["assets"]]
    assert urls == [CURRENT_IMAGE, CURRENT_VIDEO]
    assert OTHER_HISTORY_IMAGE not in urls

def test_explicit_save_rebuilds_missing_history_from_current_link_reference():
    response = submit_explicit_save(history_id=None, link_reference=current_link_reference())
    assert response.status_code == 200
    assert response.json()["assetPersistence"]["historyId"].startswith("eh_")

def test_repeated_explicit_save_reuses_pending_or_completed_persistence_job():
    first = submit_explicit_save(history_id="eh_current").json()
    second = submit_explicit_save(history_id="eh_current").json()
    assert second["assetPersistence"]["jobId"] == first["assetPersistence"]["jobId"]
```

- [ ] **Step 6: 提交事务后调度任务**

`creations.submit_task()` 调用 `CreationSaveService.save()`，仅当返回新建的 pending 工作流时执行：

```python
scheduler.submit("asset_persistence", result.asset_persistence.jobId)
return SubmitCreationTaskResponse(
    task=TaskSchema.model_validate(result.task, from_attributes=True),
    material=MaterialSchema.model_validate(result.material, from_attributes=True) if result.material else None,
    assetPersistence=result.asset_persistence,
)
```

- [ ] **Step 7: 运行保存 API 回归**

Run: `conda run -n starx pytest tests/test_api_flows.py tests/test_extract_api.py -v`

Expected: PASS。

- [ ] **Step 8: 提交保存编排**

```bash
git add app/services/creation_save_service.py app/schemas/creations.py app/api/routes/creations.py app/services/db_service.py tests/test_api_flows.py tests/test_extract_api.py
git commit -m "feat: enqueue asset persistence on explicit save"
```

### Task 6: 前端区分保存意图并展示后台状态

**Files:**
- Modify: `../starx-frontend/src/api/starx.js`
- Modify: `../starx-frontend/src/hooks/useStarxApp.js`
- Modify: `../starx-frontend/src/pages/ContentCreation.jsx`
- Modify: `../starx-frontend/src/pages/ContentCreation.preview.test.js`
- Modify: `../starx-frontend/src/api/starx.test.js`

**Interfaces:**
- Consumes: `SubmitCreationTaskResponse { task, material, assetPersistence }`。
- Produces: `submitCreationToWorkflow(payload, { saveScriptMaterial?: boolean })`。

- [ ] **Step 1: 写显式保存携带当前历史、自动保存不携带的失败测试**

```javascript
test("explicit save persists only current link reference", () => {
  assert.match(contentCreationSource, /persistExtractAssets:\s*Boolean\(linkReference\)/);
  assert.match(contentCreationSource, /extractHistoryId:\s*linkReference\?\.historyId\s*\|\|\s*null/);
  assert.match(contentCreationSource, /linkReference,/);
});

test("auto save does not request extracted asset persistence", () => {
  assert.match(appHookSource, /persistExtractAssets:\s*false/);
});
```

- [ ] **Step 2: 运行并确认保存参数缺失**

Run: `npm test -- src/pages/ContentCreation.preview.test.js src/api/starx.test.js`

Expected: FAIL，源码中没有新保存意图字段。

- [ ] **Step 3: 更新 API Hook 响应和本地状态**

```javascript
const response = await starxApi.submitCreationTask(currentAccountId, creationId, payload);
const task = response.task;
if (response.material) setMaterials((prev) => [response.material, ...prev]);
setCreation((prev) => normalizeCreationRecord({
  ...prev,
  creationState: {
    ...prev.creationState,
    ...payload.creationState,
    assetPersistence: response.assetPersistence || prev.creationState?.assetPersistence || null,
  },
}));
```

自动保存请求显式设置 `persistExtractAssets: false`，并兼容后端新响应结构。

- [ ] **Step 4: 合并两个保存动作，移除脚本素材的独立先保存请求**

```javascript
const buildExplicitSavePayload = (saveScriptMaterial = false) => ({
  topicId: app.creation.topicId || "",
  targetPlatform: currentTargetPlatform,
  type,
  content: buildContentPayload(),
  creationState: buildCreationState(),
  persistExtractAssets: Boolean(linkReference),
  extractHistoryId: linkReference?.historyId || null,
  linkReference,
  saveScriptMaterial,
  ...handoff,
});

const submit = async () => app.submitCreationToWorkflow(buildExplicitSavePayload(false));
const saveScript = async () => app.submitCreationToWorkflow(buildExplicitSavePayload(true));
```

保留现有内容非空校验，并确保两个动作成功后分别显示准确提示。

- [ ] **Step 5: 增加持久化状态展示测试与实现**

```javascript
const persistenceLabels = {
  pending: "资源转存中",
  completed: "资源已转存",
  fallback: "转存失败，当前使用源链接",
  failed: "后台任务异常，当前使用源链接",
};
```

在流程交接区域显示 `creationState.assetPersistence.status`；没有状态时不渲染提示。

- [ ] **Step 6: 运行前端测试和构建**

Run: `npm test`

Expected: PASS。

Run: `npm run build`

Expected: 构建成功，无语法错误。

- [ ] **Step 7: 提交前端改造**

```bash
git add src/api/starx.js src/hooks/useStarxApp.js src/pages/ContentCreation.jsx src/pages/ContentCreation.preview.test.js src/api/starx.test.js
git commit -m "feat: persist extracted assets after explicit save"
```

### Task 7: 全量验证与文档一致性检查

**Files:**
- Modify: `docs/superpowers/specs/2026-07-14-extract-assets-async-persistence-design.md`（仅在实现与已确认契约出现必要差异时同步）
- Modify: `docs/superpowers/plans/2026-07-14-extract-assets-async-persistence.md`（勾选已完成步骤）

**Interfaces:**
- Consumes: Task 1-6 的全部接口。
- Produces: 可部署、测试全绿的前后端改造。

- [ ] **Step 1: 运行后端针对性测试**

Run: `conda run -n starx pytest tests/test_extract_service.py tests/test_extract_api.py tests/test_asset_persistence.py tests/test_asset_persistence_workflow.py tests/test_api_flows.py -v`

Expected: PASS。

- [ ] **Step 2: 运行后端全量测试**

Run: `conda run -n starx pytest -q`

Expected: 全部测试通过，无新增 warning 或 error。

- [ ] **Step 3: 验证 Alembic 单一 head**

Run: `conda run -n starx alembic heads`

Expected: 仅输出 `20260714_000018 (head)`。

- [ ] **Step 4: 运行前端全量测试与构建**

Run: `npm test`

Expected: PASS。

Run: `npm run build`

Expected: PASS。

- [ ] **Step 5: 检查工作区和补丁质量**

```bash
git diff --check
git status --short
```

后端和前端仓库分别执行；确认没有调试输出、缓存文件、密钥或无关改动。

- [ ] **Step 6: 提交计划勾选或必要文档同步**

```bash
git add docs/superpowers/specs/2026-07-14-extract-assets-async-persistence-design.md docs/superpowers/plans/2026-07-14-extract-assets-async-persistence.md
git commit -m "docs: record extracted asset persistence implementation"
```
