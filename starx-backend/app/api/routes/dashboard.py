from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_user, get_service, get_tikhub_provider
from app.models.user import User
from app.schemas.dashboards import (
    DashboardContentTrendSchema,
    DashboardRefreshJobSchema,
    DashboardSchema,
    SocialDashboardSchema,
    SummaryItemSchema,
)
from app.services.db_service import DBService
from app.services.own_content_analytics import (
    DashboardRefreshJobService,
    OwnContentAnalyticsService,
)
from app.services.own_content_analytics.periodic_scheduler import (
    own_dashboard_periodic_scheduler,
)
from app.services.own_content_analytics.service import PLATFORM_CODES
from app.services.mediaspider.http_platforms.common.cookies import (
    get_user_bound_platform_entry,
)
from app.services.tikhub_service import TikHubProvider

router = APIRouter()


def select_dashboard_platform(requested: str, available: list[str]) -> str:
    """只允许选择当前账号已配置的平台，否则回退到第一个可用平台。"""

    return requested if requested in available else (available[0] if available else "")


def _dashboard_available_platforms(user_id: str, account) -> list[str]:
    """档案里已有平台号，或用户已扫码绑定同平台登录态，均可进入看板。"""

    available: list[str] = []
    for name, code in PLATFORM_CODES.items():
        if name not in (account.platforms or []):
            continue
        if account.platformAccounts.get(name):
            available.append(name)
            continue
        bound = get_user_bound_platform_entry(user_id, code)
        if bound and bound.get("accountId"):
            available.append(name)
    return available


@router.get("/accounts/{account_id}/dashboard", response_model=DashboardSchema)
async def get_dashboard(
    account_id: str,
    platform: str = Query(""),
    days: int = Query(30),
    force_refresh: bool = Query(False, alias="forceRefresh"),
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
    provider: TikHubProvider = Depends(get_tikhub_provider),
) -> DashboardSchema:
    if days not in {7, 30, 90}:
        raise HTTPException(status_code=422, detail="days must be 7, 30 or 90")
    try:
        account = service.get_account(user.id, account_id)
        internal = DashboardSchema.model_validate(
            service.get_dashboard(user.id, account_id), from_attributes=True
        )
    except StopIteration:
        raise HTTPException(status_code=404, detail="account not found") from None

    available = _dashboard_available_platforms(user.id, account)
    selected = select_dashboard_platform(platform, available)
    if not selected:
        social = SocialDashboardSchema(
            status="unconfigured",
            days=days,
            notices=["请先配置抖音/小红书号，或先完成对应平台浏览器扫码登录"],
        )
    else:
        analytics = OwnContentAnalyticsService(
            service.session, tikhub_provider=provider
        )
        social = analytics.build(
            user_id=user.id, account_id=account_id, platform_name=selected, days=days
        )
        if force_refresh or (
            social.status == "unavailable"
            and "尚未完成首次小时数据采集" in social.notices
        ):
            try:
                DashboardRefreshJobService(service.session).enqueue(
                    user_id=user.id,
                    account_id=account_id,
                    platform_name=selected,
                )
                own_dashboard_periodic_scheduler.notify()
            except (StopIteration, ValueError):
                pass
    return internal.model_copy(
        update={"availablePlatforms": available, "social": social}
    )


@router.post(
    "/accounts/{account_id}/dashboard/refresh",
    response_model=DashboardRefreshJobSchema,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_dashboard_refresh(
    account_id: str,
    platform: str = Query(...),
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> DashboardRefreshJobSchema:
    try:
        job = DashboardRefreshJobService(service.session).enqueue(
            user_id=user.id,
            account_id=account_id,
            platform_name=platform,
        )
    except StopIteration:
        raise HTTPException(status_code=404, detail="account not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    own_dashboard_periodic_scheduler.notify()
    return job


@router.get(
    "/accounts/{account_id}/dashboard/refreshes/{refresh_id}",
    response_model=DashboardRefreshJobSchema,
)
def get_dashboard_refresh(
    account_id: str,
    refresh_id: str,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> DashboardRefreshJobSchema:
    try:
        return DashboardRefreshJobService(service.session).get(
            user_id=user.id,
            account_id=account_id,
            refresh_id=refresh_id,
        )
    except StopIteration:
        raise HTTPException(status_code=404, detail="refresh job not found") from None


@router.get("/dashboard/summary", response_model=list[SummaryItemSchema])
def get_summary(user: User = Depends(get_current_user), service: DBService = Depends(get_service)) -> list[SummaryItemSchema]:
    return [SummaryItemSchema.model_validate(item, from_attributes=True) for item in service.summary(user.id)]


@router.get(
    "/accounts/{account_id}/dashboard/contents/{content_id}/trend",
    response_model=DashboardContentTrendSchema,
)
def get_content_trend(
    account_id: str,
    content_id: int,
    days: int = Query(7),
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
    provider: TikHubProvider = Depends(get_tikhub_provider),
) -> DashboardContentTrendSchema:
    if days not in {1, 7, 30}:
        raise HTTPException(status_code=422, detail="days must be 1, 7 or 30")
    try:
        return OwnContentAnalyticsService(
            service.session, tikhub_provider=provider
        ).trend(
            user_id=user.id,
            account_id=account_id,
            content_id=content_id,
            days=days,
        )
    except StopIteration:
        raise HTTPException(status_code=404, detail="content not found") from None
