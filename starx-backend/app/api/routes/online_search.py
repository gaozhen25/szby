from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, get_online_search_service
from app.models.user import User
from app.services.online_search.models import OnlineSearchRequest
from app.services.online_search.platform.doubao import (
    OnlineSearchConfigError,
    OnlineSearchRequestError,
)
from app.services.online_search.service import OnlineSearchService

router = APIRouter(prefix="/online-search")


@router.post("", response_model=dict[str, Any])
async def online_search(
    payload: OnlineSearchRequest,
    _user: User = Depends(get_current_user),
    service: OnlineSearchService = Depends(get_online_search_service),
) -> dict[str, Any]:
    try:
        return await service.search(payload)
    except OnlineSearchConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OnlineSearchRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
