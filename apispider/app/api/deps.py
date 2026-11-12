from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.services.ai_service import AIService, default_ai_service
from app.services.autophone_service import AutophoneService, default_autophone_service
from app.services.db_service import DBService
from app.services.online_search.service import OnlineSearchService, default_online_search_service
from app.services.account_report.similar_account_resolver import SimilarAccountResolver
from app.services.tikhub_service import default_tikhub_runtime
from tikhub import AsyncTikHub
from app.models.user import User


def get_service(db: Session = Depends(get_db)) -> DBService:
    return DBService(db)


def get_ai_service() -> AIService:
    return default_ai_service


def get_autophone_service() -> AutophoneService:
    return default_autophone_service


def get_online_search_service() -> OnlineSearchService:
    return default_online_search_service


def get_tikhub_sdk() -> AsyncTikHub:
    """返回进程共享的官方 TikHub SDK 客户端。"""

    return default_tikhub_runtime.client


def get_similar_account_resolver() -> SimilarAccountResolver:
    return SimilarAccountResolver()


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    service: DBService = Depends(get_service),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authorization token")
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid authorization token")
    user = service.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid authorization token")
    return user
