from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, get_service
from app.models.user import User
from app.schemas.auth import AuthResponse, LoginRequest, UserSchema
from app.services.db_service import DBService

router = APIRouter()


@router.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, service: DBService = Depends(get_service)) -> AuthResponse:
    try:
        return service.login_user(payload.email, payload.password)
    except ValueError as exc:
        if str(exc) == "invalid_credentials":
            raise HTTPException(status_code=401, detail="Invalid credentials") from exc
        raise


@router.get("/auth/me", response_model=UserSchema)
def me(user: User = Depends(get_current_user)) -> UserSchema:
    return UserSchema(id=user.id, email=user.email, nickname=user.nickname)
