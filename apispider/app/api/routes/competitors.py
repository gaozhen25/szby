"""竞品账号和视频监控 API。"""

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.competitors import (
    AddCompetitorAccountRequest,
    AddCompetitorVideoRequest,
    CompetitorAccountSchema,
    CompetitorBatchRefreshResponse,
    CompetitorVideoSchema,
    CreateCompetitorAccountResponse,
    CreateCompetitorVideoResponse,
)
from app.schemas.generation import WorkflowSchema
from app.services.competitor_monitoring.service import (
    CompetitorMonitoringService,
    CompetitorTargetNotFound,
    DuplicateCompetitorTarget,
)
from app.services.mediaspider.models import InvalidCrawlRequestError
from app.services.workflow import WorkflowScheduler
from app.services.workflow.service import job_schema

router = APIRouter()


def get_competitor_monitoring_service() -> CompetitorMonitoringService:
    return CompetitorMonitoringService()


def get_competitor_scheduler() -> WorkflowScheduler:
    return WorkflowScheduler.get_instance()


def _submit(service, scheduler, workflow, is_new: bool = True) -> None:
    if not is_new:
        return
    try:
        scheduler.submit("competitor_refresh", workflow.id)
    except Exception as exc:
        service.mark_submission_failed(workflow.id)
        raise HTTPException(
            status_code=500, detail="竞品刷新任务提交失败，请稍后重试"
        ) from exc


def _submit_batch(service, scheduler, entries) -> None:
    for workflow, is_new in entries:
        try:
            _submit(service, scheduler, workflow, is_new)
        except HTTPException:
            continue


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get(
    "/accounts/{account_id}/competitors/accounts",
    response_model=list[CompetitorAccountSchema],
)
def list_competitor_accounts(
    account_id: str,
    user: User = Depends(get_current_user),
    service: CompetitorMonitoringService = Depends(get_competitor_monitoring_service),
):
    try:
        return service.list_accounts(user.id, account_id)
    except CompetitorTargetNotFound as exc:
        raise _not_found(exc) from exc


@router.post(
    "/accounts/{account_id}/competitors/accounts",
    response_model=CreateCompetitorAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_competitor_account(
    account_id: str,
    payload: AddCompetitorAccountRequest,
    user: User = Depends(get_current_user),
    service: CompetitorMonitoringService = Depends(get_competitor_monitoring_service),
    scheduler: WorkflowScheduler = Depends(get_competitor_scheduler),
):
    try:
        target, workflow = service.add_account(user.id, account_id, payload.profileUrl)
    except DuplicateCompetitorTarget as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CompetitorTargetNotFound as exc:
        raise _not_found(exc) from exc
    except InvalidCrawlRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        _submit(service, scheduler, workflow)
    except HTTPException:
        service.delete_account(user.id, account_id, target.id)
        raise
    return {"target": target, "workflow": job_schema(workflow)}


@router.delete(
    "/accounts/{account_id}/competitors/accounts/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_competitor_account(
    account_id: str,
    target_id: str,
    user: User = Depends(get_current_user),
    service: CompetitorMonitoringService = Depends(get_competitor_monitoring_service),
):
    try:
        service.delete_account(user.id, account_id, target_id)
    except CompetitorTargetNotFound as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/accounts/{account_id}/competitors/accounts/{target_id}/refresh",
    response_model=WorkflowSchema,
)
def refresh_competitor_account(
    account_id: str,
    target_id: str,
    user: User = Depends(get_current_user),
    service: CompetitorMonitoringService = Depends(get_competitor_monitoring_service),
    scheduler: WorkflowScheduler = Depends(get_competitor_scheduler),
):
    try:
        workflow, is_new = service.create_refresh(
            user.id, account_id, "account", target_id, "manual"
        )
    except CompetitorTargetNotFound as exc:
        raise _not_found(exc) from exc
    _submit(service, scheduler, workflow, is_new)
    return job_schema(workflow)


@router.post(
    "/accounts/{account_id}/competitors/accounts/refresh-batch",
    response_model=CompetitorBatchRefreshResponse,
)
def refresh_competitor_accounts(
    account_id: str,
    user: User = Depends(get_current_user),
    service: CompetitorMonitoringService = Depends(get_competitor_monitoring_service),
    scheduler: WorkflowScheduler = Depends(get_competitor_scheduler),
):
    try:
        entries = service.create_batch_refresh(user.id, account_id, "account")
    except CompetitorTargetNotFound as exc:
        raise _not_found(exc) from exc
    _submit_batch(service, scheduler, entries)
    return {
        "workflows": [
            job_schema(service.get_workflow(user.id, account_id, workflow.id))
            for workflow, _ in entries
        ]
    }


@router.get(
    "/accounts/{account_id}/competitors/videos",
    response_model=list[CompetitorVideoSchema],
)
def list_competitor_videos(
    account_id: str,
    user: User = Depends(get_current_user),
    service: CompetitorMonitoringService = Depends(get_competitor_monitoring_service),
):
    try:
        return service.list_videos(user.id, account_id)
    except CompetitorTargetNotFound as exc:
        raise _not_found(exc) from exc


@router.post(
    "/accounts/{account_id}/competitors/videos",
    response_model=CreateCompetitorVideoResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_competitor_video(
    account_id: str,
    payload: AddCompetitorVideoRequest,
    user: User = Depends(get_current_user),
    service: CompetitorMonitoringService = Depends(get_competitor_monitoring_service),
    scheduler: WorkflowScheduler = Depends(get_competitor_scheduler),
):
    try:
        target, workflow = service.add_video(user.id, account_id, payload.contentUrl)
    except DuplicateCompetitorTarget as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CompetitorTargetNotFound as exc:
        raise _not_found(exc) from exc
    except InvalidCrawlRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        _submit(service, scheduler, workflow)
    except HTTPException:
        service.delete_video(user.id, account_id, target.id)
        raise
    return {"target": target, "workflow": job_schema(workflow)}


@router.delete(
    "/accounts/{account_id}/competitors/videos/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_competitor_video(
    account_id: str,
    target_id: str,
    user: User = Depends(get_current_user),
    service: CompetitorMonitoringService = Depends(get_competitor_monitoring_service),
):
    try:
        service.delete_video(user.id, account_id, target_id)
    except CompetitorTargetNotFound as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/accounts/{account_id}/competitors/videos/{target_id}/refresh",
    response_model=WorkflowSchema,
)
def refresh_competitor_video(
    account_id: str,
    target_id: str,
    user: User = Depends(get_current_user),
    service: CompetitorMonitoringService = Depends(get_competitor_monitoring_service),
    scheduler: WorkflowScheduler = Depends(get_competitor_scheduler),
):
    try:
        workflow, is_new = service.create_refresh(
            user.id, account_id, "video", target_id, "manual"
        )
    except CompetitorTargetNotFound as exc:
        raise _not_found(exc) from exc
    _submit(service, scheduler, workflow, is_new)
    return job_schema(workflow)


@router.post(
    "/accounts/{account_id}/competitors/videos/refresh-batch",
    response_model=CompetitorBatchRefreshResponse,
)
def refresh_competitor_videos(
    account_id: str,
    user: User = Depends(get_current_user),
    service: CompetitorMonitoringService = Depends(get_competitor_monitoring_service),
    scheduler: WorkflowScheduler = Depends(get_competitor_scheduler),
):
    try:
        entries = service.create_batch_refresh(user.id, account_id, "video")
    except CompetitorTargetNotFound as exc:
        raise _not_found(exc) from exc
    _submit_batch(service, scheduler, entries)
    return {
        "workflows": [
            job_schema(service.get_workflow(user.id, account_id, workflow.id))
            for workflow, _ in entries
        ]
    }


@router.get(
    "/accounts/{account_id}/competitors/refresh-workflows/{workflow_id}",
    response_model=WorkflowSchema,
)
def get_competitor_refresh_workflow(
    account_id: str,
    workflow_id: str,
    user: User = Depends(get_current_user),
    service: CompetitorMonitoringService = Depends(get_competitor_monitoring_service),
):
    try:
        return job_schema(service.get_workflow(user.id, account_id, workflow_id))
    except CompetitorTargetNotFound as exc:
        raise _not_found(exc) from exc
