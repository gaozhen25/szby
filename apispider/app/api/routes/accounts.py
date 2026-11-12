from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.deps import get_current_user, get_service
from app.api.workflow_deps import (
    ACCOUNT_REPORT_DISPATCH_ERROR,
    get_account_report_scheduler,
    get_account_report_workflow_service,
    log_account_report_dispatch_failure,
)
from app.models.user import User
from app.schemas.accounts import AccountListResponse, AccountSchema, CreateAccountRequest, UpdateAccountRequest
from app.services.db_service import DBService
from app.services.workflow import WorkflowScheduler, WorkflowService

router = APIRouter()


@router.get("/accounts")
def list_accounts(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(12, alias="pageSize", ge=1, le=100),
    keyword: str = Query("", max_length=80),
    platform: str = Query("", max_length=32),
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> list[AccountSchema] | AccountListResponse:
    wants_page = any(key in request.query_params for key in ("page", "pageSize", "keyword", "platform"))
    if not wants_page:
        return [AccountSchema.model_validate(account, from_attributes=True) for account in service.list_accounts(user.id)]

    items, total, page_value, page_size_value = service.list_accounts_page(
        user.id,
        page=page,
        page_size=page_size,
        keyword=keyword,
        platform=platform,
    )
    return AccountListResponse(
        items=[AccountSchema.model_validate(account, from_attributes=True) for account in items],
        total=total,
        page=page_value,
        pageSize=page_size_value,
    )


@router.post("/accounts", response_model=AccountSchema)
def create_account(
    payload: CreateAccountRequest,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
    workflows: WorkflowService = Depends(get_account_report_workflow_service),
    scheduler: WorkflowScheduler = Depends(get_account_report_scheduler),
) -> AccountSchema:
    try:
        account = service.create_account(
            user.id,
            payload.name,
            payload.description,
            payload.purpose,
            payload.type,
            payload.platforms or [payload.platform],
            payload.accountLinks,
            {key: value.model_dump() for key, value in (payload.publishSettings or {}).items()},
            payload.industry,
            payload.productService,
            payload.targetCity,
            payload.targetAudience,
            payload.conversionGoal,
            payload.knowledgeBaseId,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    workflow, is_new = workflows.create_account_report_job(user.id, account.id)
    if is_new:
        try:
            scheduler.submit("account_report", workflow.id)
        except Exception as exc:
            log_account_report_dispatch_failure(exc)
            workflows.mark_account_report_job_failed(
                user.id,
                account.id,
                workflow.id,
                ACCOUNT_REPORT_DISPATCH_ERROR,
            )
    return AccountSchema.model_validate(account, from_attributes=True)


@router.patch("/accounts/{account_id}", response_model=AccountSchema)
def update_account(
    account_id: str,
    payload: UpdateAccountRequest,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> AccountSchema:
    try:
        account = service.update_account(
            user.id,
            account_id,
            payload.name,
            payload.description,
            payload.purpose,
            payload.type,
            payload.platforms or [payload.platform],
            payload.accountLinks,
            {key: value.model_dump() for key, value in (payload.publishSettings or {}).items()},
            payload.industry,
            payload.productService,
            payload.targetCity,
            payload.targetAudience,
            payload.conversionGoal,
            payload.knowledgeBaseId,
        )
    except StopIteration:
        raise HTTPException(status_code=404, detail="account not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AccountSchema.model_validate(account, from_attributes=True)


@router.delete("/accounts/{account_id}")
def delete_account(
    account_id: str,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> None:
    return service.delete_account(user.id, account_id)
