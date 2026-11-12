from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_ai_service, get_current_user, get_service, get_similar_account_resolver
from app.models.user import User
from app.schemas.reports import (
    AddSimilarAccountRequest,
    ReportSchema,
    ResolveSimilarAccountRequest,
    ResolvedSimilarAccountSchema,
    UpdateReportSectionRequest,
)
from app.services.ai_service import AIService
from app.services.db_service import DBService
from app.services.account_report.similar_account_resolver import SimilarAccountResolver
from app.services.mediaspider.models import InvalidCrawlRequestError
from app.services.tikhub_service.errors import TikHubBusinessError

router = APIRouter()


@router.post(
    "/accounts/{account_id}/report/similar-accounts/resolve",
    response_model=ResolvedSimilarAccountSchema,
)
async def resolve_similar_account(
    account_id: str,
    payload: ResolveSimilarAccountRequest,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
    resolver: SimilarAccountResolver = Depends(get_similar_account_resolver),
) -> ResolvedSimilarAccountSchema:
    try:
        service.get_account(user.id, account_id)
        resolved = await resolver.resolve(payload.profileUrl)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="账号不存在") from exc
    except (InvalidCrawlRequestError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TikHubBusinessError as exc:
        raise HTTPException(status_code=502, detail="账号链接解析失败，请稍后重试") from exc
    return ResolvedSimilarAccountSchema.model_validate(resolved)


@router.get("/accounts/{account_id}/report", response_model=ReportSchema)
def get_report(account_id: str, user: User = Depends(get_current_user), service: DBService = Depends(get_service)) -> ReportSchema:
    return ReportSchema.model_validate(service.get_report(user.id, account_id), from_attributes=True)


@router.post("/accounts/{account_id}/report/similar-accounts", response_model=ReportSchema)
def add_similar_account(
    account_id: str,
    payload: AddSimilarAccountRequest,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> ReportSchema:
    try:
        report = service.add_report_similar_account(user.id, account_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="账号报告不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ReportSchema.model_validate(report, from_attributes=True)


@router.delete(
    "/accounts/{account_id}/report/similar-accounts/{similar_account_key}",
    response_model=ReportSchema,
)
def delete_similar_account(
    account_id: str,
    similar_account_key: str,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> ReportSchema:
    try:
        report = service.delete_report_similar_account(user.id, account_id, similar_account_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="相似账号不存在") from exc
    return ReportSchema.model_validate(report, from_attributes=True)


@router.put("/accounts/{account_id}/report/sections/{section_key}", response_model=ReportSchema)
def update_report(
    account_id: str,
    section_key: str,
    payload: UpdateReportSectionRequest,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> ReportSchema:
    return ReportSchema.model_validate(
        service.update_report_section(user.id, account_id, section_key, payload.content), from_attributes=True
    )


@router.post("/accounts/{account_id}/report/sections/{section_key}/analyze", response_model=ReportSchema)
async def analyze_report(
    account_id: str,
    section_key: str,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
    ai_service: AIService = Depends(get_ai_service),
) -> ReportSchema:
    account = service.get_account(user.id, account_id)
    content = await ai_service.analyze_report_section(
        section_key=section_key,
        account_context={
            "id": account.id,
            "name": account.name,
            "type": account.type,
            "description": account.description,
            "purpose": account.purpose,
        },
    )
    return ReportSchema.model_validate(
        service.update_report_section(user.id, account_id, section_key, content), from_attributes=True
    )
