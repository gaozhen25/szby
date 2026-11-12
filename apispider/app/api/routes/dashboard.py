from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_service
from app.models.user import User
from app.schemas.dashboards import DashboardSchema, SummaryItemSchema
from app.services.db_service import DBService

router = APIRouter()


@router.get("/accounts/{account_id}/dashboard", response_model=DashboardSchema)
def get_dashboard(account_id: str, user: User = Depends(get_current_user), service: DBService = Depends(get_service)) -> DashboardSchema:
    return DashboardSchema.model_validate(service.get_dashboard(user.id, account_id), from_attributes=True)


@router.get("/dashboard/summary", response_model=list[SummaryItemSchema])
def get_summary(user: User = Depends(get_current_user), service: DBService = Depends(get_service)) -> list[SummaryItemSchema]:
    return [SummaryItemSchema.model_validate(item, from_attributes=True) for item in service.summary(user.id)]
