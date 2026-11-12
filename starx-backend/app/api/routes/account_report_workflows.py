"""账号报告整份及四个可见板块的生成任务接口。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.api.workflow_deps import (
    ACCOUNT_REPORT_DISPATCH_ERROR,
    get_account_report_scheduler,
    get_account_report_workflow_service,
    log_account_report_dispatch_failure,
)
from app.models.user import User
from app.schemas.generation import WorkflowSchema
from app.schemas.reports import (
    CreateAccountReportSectionWorkflowRequest,
    CreateAccountReportWorkflowRequest,
)
from app.services.workflow import WorkflowScheduler, WorkflowService

router = APIRouter()

ReportSectionKey = Literal[
    "similarAccounts",
    "complianceRules",
    "targetUserProfile",
    "hotContents",
]


def _create_workflow(
    *,
    account_id: str,
    reference_comments: bool,
    section_key: ReportSectionKey | None,
    user: User,
    workflows: WorkflowService,
    scheduler: WorkflowScheduler,
) -> WorkflowSchema:
    try:
        if section_key:
            workflow, is_new = workflows.create_account_report_section_job(
                user.id,
                account_id,
                section_key,
                reference_comments=reference_comments,
            )
        else:
            workflow, is_new = workflows.create_account_report_job(
                user.id,
                account_id,
                reference_comments=reference_comments,
            )
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if is_new:
        try:
            scheduler.submit(workflow.type, workflow.id)
        except Exception as exc:
            log_account_report_dispatch_failure(exc)
            workflows.mark_account_report_job_failed(
                user.id,
                account_id,
                workflow.id,
                ACCOUNT_REPORT_DISPATCH_ERROR,
            )
            raise HTTPException(status_code=500, detail=ACCOUNT_REPORT_DISPATCH_ERROR) from exc
    return workflow


@router.post("/accounts/{account_id}/report/workflows", response_model=WorkflowSchema)
def create_account_report_workflow(
    account_id: str,
    payload: CreateAccountReportWorkflowRequest | None = None,
    user: User = Depends(get_current_user),
    workflows: WorkflowService = Depends(get_account_report_workflow_service),
    scheduler: WorkflowScheduler = Depends(get_account_report_scheduler),
) -> WorkflowSchema:
    """生成整份报告；sectionKey 仅作为旧客户端兼容入口保留。"""
    return _create_workflow(
        account_id=account_id,
        reference_comments=payload.referenceComments if payload else False,
        section_key=payload.sectionKey if payload else None,
        user=user,
        workflows=workflows,
        scheduler=scheduler,
    )


def _create_section_workflow(
    account_id: str,
    payload: CreateAccountReportSectionWorkflowRequest | None,
    section_key: ReportSectionKey,
    user: User,
    workflows: WorkflowService,
    scheduler: WorkflowScheduler,
) -> WorkflowSchema:
    return _create_workflow(
        account_id=account_id,
        reference_comments=payload.referenceComments if payload else False,
        section_key=section_key,
        user=user,
        workflows=workflows,
        scheduler=scheduler,
    )


@router.post("/accounts/{account_id}/report/similar-accounts/workflows", response_model=WorkflowSchema)
def create_similar_accounts_workflow(
    account_id: str,
    payload: CreateAccountReportSectionWorkflowRequest | None = None,
    user: User = Depends(get_current_user),
    workflows: WorkflowService = Depends(get_account_report_workflow_service),
    scheduler: WorkflowScheduler = Depends(get_account_report_scheduler),
) -> WorkflowSchema:
    return _create_section_workflow(account_id, payload, "similarAccounts", user, workflows, scheduler)


@router.post("/accounts/{account_id}/report/compliance-rules/workflows", response_model=WorkflowSchema)
def create_compliance_rules_workflow(
    account_id: str,
    payload: CreateAccountReportSectionWorkflowRequest | None = None,
    user: User = Depends(get_current_user),
    workflows: WorkflowService = Depends(get_account_report_workflow_service),
    scheduler: WorkflowScheduler = Depends(get_account_report_scheduler),
) -> WorkflowSchema:
    return _create_section_workflow(account_id, payload, "complianceRules", user, workflows, scheduler)


@router.post("/accounts/{account_id}/report/target-user-profile/workflows", response_model=WorkflowSchema)
def create_target_user_profile_workflow(
    account_id: str,
    payload: CreateAccountReportSectionWorkflowRequest | None = None,
    user: User = Depends(get_current_user),
    workflows: WorkflowService = Depends(get_account_report_workflow_service),
    scheduler: WorkflowScheduler = Depends(get_account_report_scheduler),
) -> WorkflowSchema:
    return _create_section_workflow(account_id, payload, "targetUserProfile", user, workflows, scheduler)


@router.post("/accounts/{account_id}/report/hot-contents/workflows", response_model=WorkflowSchema)
def create_hot_contents_workflow(
    account_id: str,
    payload: CreateAccountReportSectionWorkflowRequest | None = None,
    user: User = Depends(get_current_user),
    workflows: WorkflowService = Depends(get_account_report_workflow_service),
    scheduler: WorkflowScheduler = Depends(get_account_report_scheduler),
) -> WorkflowSchema:
    return _create_section_workflow(account_id, payload, "hotContents", user, workflows, scheduler)


@router.get("/accounts/{account_id}/report/workflows/latest", response_model=WorkflowSchema)
def get_latest_account_report_workflow(
    account_id: str,
    user: User = Depends(get_current_user),
    workflows: WorkflowService = Depends(get_account_report_workflow_service),
) -> WorkflowSchema:
    try:
        return workflows.get_latest_account_report_job(user.id, account_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/accounts/{account_id}/report/workflows/active", response_model=list[WorkflowSchema])
def get_active_account_report_workflows(
    account_id: str,
    user: User = Depends(get_current_user),
    workflows: WorkflowService = Depends(get_account_report_workflow_service),
) -> list[WorkflowSchema]:
    try:
        return workflows.get_active_account_report_jobs(user.id, account_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/accounts/{account_id}/report/workflows/{workflow_id}", response_model=WorkflowSchema)
def get_account_report_workflow(
    account_id: str,
    workflow_id: str,
    user: User = Depends(get_current_user),
    workflows: WorkflowService = Depends(get_account_report_workflow_service),
) -> WorkflowSchema:
    try:
        return workflows.get_account_report_job(user.id, account_id, workflow_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
