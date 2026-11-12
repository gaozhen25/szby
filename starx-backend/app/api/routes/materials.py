from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_service
from app.models.user import User
from app.schemas.materials import CreateMaterialRequest, MaterialSchema
from app.services.db_service import DBService

router = APIRouter()


@router.get("/accounts/{account_id}/materials", response_model=list[MaterialSchema])
def list_materials(
    account_id: str,
    limit: int = 100,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> list[MaterialSchema]:
    return [MaterialSchema.model_validate(material, from_attributes=True) for material in service.list_materials(user.id, account_id, limit=limit)]


@router.post("/accounts/{account_id}/materials", response_model=MaterialSchema)
def create_material(
    account_id: str, payload: CreateMaterialRequest, user: User = Depends(get_current_user), service: DBService = Depends(get_service)
) -> MaterialSchema:
    material = service.create_material(
        user.id,
        account_id,
        payload.name,
        payload.type,
        payload.tags,
        payload.thumb,
        payload.assets,
    )
    return MaterialSchema.model_validate(material, from_attributes=True)
