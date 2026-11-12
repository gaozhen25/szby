from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_autophone_service, get_current_user, get_service
from app.models.user import User

from app.schemas.creations import (
    AssetPersistenceSummarySchema,
    CreationResponse,
    GenerateCreationRequest,
    PublishCreationRequest,
    PublishCreationResponse,
    SubmitCreationTaskRequest,
    SubmitCreationTaskResponse,
)
from app.schemas.materials import MaterialSchema
from app.schemas.tasks import TaskSchema
from app.services.autophone_service import (
    AutophoneConfigError,
    AutophoneConflictError,
    AutophoneNotFoundError,
    AutophonePublishRequest,
    AutophoneRequestError,
    AutophoneService,
    AutophoneSubmissionRejectedError,
    validate_autophone_publish_result,
)
from app.services.db_service import AUTOPHONE_PLATFORM_BY_ACCOUNT_PLATFORM
from app.services.db_service import DBService
from app.services.creation_save_service import CreationSaveError, CreationSaveService
from app.services.publish_attempts import PublishReservationError
from app.api.routes.uploads import get_direct_upload_service
from app.services.uploads import DirectUploadError, DirectUploadService
from app.services.workflow.scheduler import WorkflowScheduler

router = APIRouter()


def get_creation_scheduler() -> WorkflowScheduler:
    return WorkflowScheduler.get_instance()


def _publish_response_from_autophone(
    data: dict[str, object],
    *,
    expected_external_id: str,
    attempt: int,
) -> PublishCreationResponse:
    validated = validate_autophone_publish_result(
        data,
        expected_external_id=expected_external_id,
    )
    return PublishCreationResponse(
        externalId=str(validated.get("external_id") or ""),
        platform=str(validated.get("platform") or ""),
        status=str(validated.get("status") or ""),
        androidId=str(validated.get("android_id") or ""),
        materialId=str(validated.get("material_id") or ""),
        publishJobId=str(validated.get("publish_job_id") or ""),
        taskId=str(validated.get("task_id") or ""),
        attempt=attempt,
        errorMessage=validated.get("error_message") if validated.get("error_message") is None else str(validated.get("error_message")),
        createdAt=validated.get("created_at") if validated.get("created_at") is None else str(validated.get("created_at")),
        triggeredAt=validated.get("triggered_at") if validated.get("triggered_at") is None else str(validated.get("triggered_at")),
        startedAt=validated.get("started_at") if validated.get("started_at") is None else str(validated.get("started_at")),
        finishedAt=validated.get("finished_at") if validated.get("finished_at") is None else str(validated.get("finished_at")),
    )


def _publish_state_from_response(response: PublishCreationResponse) -> dict[str, object]:
    return {
        "externalId": response.externalId,
        "platform": response.platform,
        "status": response.status,
        "androidId": response.androidId,
        "materialId": response.materialId,
        "publishJobId": response.publishJobId,
        "taskId": response.taskId,
        "attempt": response.attempt,
        "errorMessage": response.errorMessage,
        "createdAt": response.createdAt,
        "triggeredAt": response.triggeredAt,
        "startedAt": response.startedAt,
        "finishedAt": response.finishedAt,
    }


def _failed_publish_response(
    *,
    external_id: str,
    platform: str,
    android_id: str,
    attempt: int,
    error: Exception,
) -> PublishCreationResponse:
    return PublishCreationResponse(
        externalId=external_id,
        platform=platform,
        status="failed",
        androidId=android_id,
        attempt=attempt,
        errorMessage=str(error),
    )


def _current_publish_response(creation: CreationResponse) -> PublishCreationResponse | None:
    state = creation.creationState.get("publish") if isinstance(creation.creationState, dict) else None
    if not isinstance(state, dict):
        return None
    return PublishCreationResponse.model_validate(state)


def _publish_attempt(value: object) -> int:
    if isinstance(value, bool):
        return 1
    try:
        attempt = int(value)
    except (TypeError, ValueError):
        return 1
    return attempt if attempt >= 1 else 1


@router.post("/accounts/{account_id}/creations/generate", response_model=CreationResponse)
def generate_creation(
    account_id: str,
    payload: GenerateCreationRequest,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> CreationResponse:
    return service.generate_creation(user.id, account_id, payload.topicId, payload.targetPlatform)


@router.get("/accounts/{account_id}/creations/{creation_id}", response_model=CreationResponse)
def get_creation(
    account_id: str,
    creation_id: str,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> CreationResponse:
    try:
        return service.get_creation(user.id, account_id, creation_id)
    except StopIteration:
        raise HTTPException(status_code=404, detail="creation not found") from None


@router.post(
    "/accounts/{account_id}/creations/{creation_id}/submit-task",
    response_model=SubmitCreationTaskResponse,
)
def submit_task(
    account_id: str,
    creation_id: str,
    payload: SubmitCreationTaskRequest,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
    scheduler: WorkflowScheduler = Depends(get_creation_scheduler),
) -> SubmitCreationTaskResponse:
    try:
        result = CreationSaveService(service).save(user.id, account_id, creation_id, payload)
    except CreationSaveError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result.should_dispatch and result.asset_persistence is not None:
        scheduler.submit("asset_persistence", result.asset_persistence.job_id)
    task_payload = TaskSchema.model_validate(result.task, from_attributes=True).model_dump()
    material = MaterialSchema.model_validate(result.material, from_attributes=True) if result.material else None
    persistence = None
    if result.asset_persistence is not None:
        persistence = AssetPersistenceSummarySchema(
            jobId=result.asset_persistence.job_id,
            historyId=result.asset_persistence.history_id,
            status=result.asset_persistence.status,
            error=result.asset_persistence.error,
        )
    return SubmitCreationTaskResponse(
        **task_payload,
        material=material,
        assetPersistence=persistence,
    )


@router.post("/accounts/{account_id}/creations/{creation_id}/publish", response_model=PublishCreationResponse)
def publish_creation(
    account_id: str,
    creation_id: str,
    payload: PublishCreationRequest,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
    autophone_service: AutophoneService = Depends(get_autophone_service),
    uploads: DirectUploadService = Depends(get_direct_upload_service),
) -> PublishCreationResponse:
    account = service.get_account(user.id, account_id)
    creation = service.get_creation(user.id, account_id, creation_id)
    target_platform = payload.targetPlatform.strip() or creation.targetPlatform
    publish_setting = account.publishSettings.get(target_platform)
    if not publish_setting or not publish_setting.get("androidId"):
        raise HTTPException(status_code=400, detail=f"publishSettings is required for {target_platform}")
    external_platform = publish_setting.get("platform") or AUTOPHONE_PLATFORM_BY_ACCOUNT_PLATFORM.get(target_platform)
    if external_platform not in {"xhs", "douyin", "kuaishou"}:
        raise HTTPException(status_code=400, detail=f"{target_platform} is not supported for external publish")
    asset_list = payload.normalized_asset_list()
    if not asset_list:
        raise HTTPException(status_code=400, detail="assetList is required")
    invalid_assets = [url for url in asset_list if not url.startswith("https://")]
    if invalid_assets:
        raise HTTPException(status_code=400, detail="assetList must contain HTTPS URLs")
    try:
        upload_records = [
            uploads.verify_ref(
                user_id=user.id,
                ref=ref,
                purposes={"publish_video", "publish_image"},
                account_id=account_id,
            )
            for ref in payload.uploadedAssets
        ]
    except DirectUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    uploaded_urls = {ref.url for ref in payload.uploadedAssets}
    if not uploaded_urls.issubset(set(asset_list)):
        raise HTTPException(status_code=422, detail="uploadedAssets must be included in assetList")

    try:
        reservation = service.reserve_creation_publish_attempt(
            user.id,
            account_id,
            creation_id,
            expected_target_platform=creation.targetPlatform,
            external_platform=external_platform,
            android_id=publish_setting["androidId"],
            retry=payload.retry,
        )
    except PublishReservationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    attempt = reservation.attempt
    external_id = reservation.external_id
    request = AutophonePublishRequest(
        external_id=external_id,
        platform=external_platform,
        android_id=publish_setting["androidId"],
        asset_list=asset_list,
        filename=payload.filename.strip(),
        title=payload.title.strip(),
        description=payload.description,
        visibility=payload.visibility,
        copy_to_album=payload.copyToAlbum,
        sha256=payload.sha256.strip(),
        size_bytes=payload.sizeBytes,
    )
    try:
        result = autophone_service.publish(request)
        response = _publish_response_from_autophone(
            result,
            expected_external_id=external_id,
            attempt=attempt,
        )
    except AutophoneConflictError as exc:
        try:
            recovered_result = autophone_service.get_publish_status(external_id)
            recovered = _publish_response_from_autophone(
                recovered_result,
                expected_external_id=external_id,
                attempt=attempt,
            )
        except (AutophoneConfigError, AutophoneRequestError) as recovery_exc:
            raise HTTPException(status_code=409, detail=str(exc)) from recovery_exc
        persisted = service.update_creation_publish_state(
            user.id,
            account_id,
            creation_id,
            _publish_state_from_response(recovered),
            expected_external_id=external_id,
            expected_attempt=attempt,
        )
        return _current_publish_response(persisted) or recovered
    except AutophoneConfigError as exc:
        failed = _failed_publish_response(
            external_id=external_id,
            platform=external_platform,
            android_id=publish_setting["androidId"],
            attempt=attempt,
            error=exc,
        )
        service.update_creation_publish_state(
            user.id,
            account_id,
            creation_id,
            _publish_state_from_response(failed),
            expected_external_id=external_id,
            expected_attempt=attempt,
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AutophoneSubmissionRejectedError as exc:
        failed = _failed_publish_response(
            external_id=external_id,
            platform=external_platform,
            android_id=publish_setting["androidId"],
            attempt=attempt,
            error=exc,
        )
        service.update_creation_publish_state(
            user.id,
            account_id,
            creation_id,
            _publish_state_from_response(failed),
            expected_external_id=external_id,
            expected_attempt=attempt,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AutophoneRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    persisted = service.update_creation_publish_state(
        user.id,
        account_id,
        creation_id,
        _publish_state_from_response(response),
        expected_external_id=external_id,
        expected_attempt=attempt,
    )
    uploads.mark_consumed(
        [record for record in upload_records if record is not None],
        resource_type="creation_publish",
        resource_id=external_id,
    )
    service.session.commit()
    return _current_publish_response(persisted) or response


@router.get("/accounts/{account_id}/creations/{creation_id}/publish/status", response_model=PublishCreationResponse)
def get_publish_status(
    account_id: str,
    creation_id: str,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
    autophone_service: AutophoneService = Depends(get_autophone_service),
) -> PublishCreationResponse:
    publish_state = service.get_current_creation_publish_state(user.id, account_id, creation_id)
    external_id = str(publish_state.get("externalId") or "") if isinstance(publish_state, dict) else ""
    if not external_id:
        raise HTTPException(status_code=404, detail="publish state not found")
    attempt = _publish_attempt(publish_state.get("attempt"))
    try:
        result = autophone_service.get_publish_status(external_id)
        response = _publish_response_from_autophone(
            result,
            expected_external_id=external_id,
            attempt=attempt,
        )
    except AutophoneConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AutophoneNotFoundError as exc:
        expired = service.fail_stale_publish_reservation(
            user.id,
            account_id,
            creation_id,
            expected_external_id=external_id,
            expected_attempt=attempt,
            error=str(exc),
        )
        if expired is not None:
            recovered = _current_publish_response(expired)
            if recovered is not None:
                return recovered
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AutophoneRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    persisted = service.update_creation_publish_state(
        user.id,
        account_id,
        creation_id,
        _publish_state_from_response(response),
        expected_external_id=external_id,
        expected_attempt=attempt,
    )
    return _current_publish_response(persisted) or response


@router.post("/accounts/{account_id}/creations/{creation_id}/save-materials", response_model=MaterialSchema)
def save_materials(
    account_id: str,
    creation_id: str,
    payload: GenerateCreationRequest,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> MaterialSchema:
    creation = service.generate_creation(user.id, account_id, payload.topicId, payload.targetPlatform)
    material = service.create_material(
        user.id, account_id, f"{creation.topicTitle}_素材.txt", "script", ["自动保存", payload.targetPlatform], "📝"
    )
    return MaterialSchema.model_validate(material, from_attributes=True)
