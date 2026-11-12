from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, get_service
from app.schemas.tags import TagSchema

from app.services.db_service import DBService

router = APIRouter()

@router.get("/tags", response_model=list[TagSchema]) 
def get_tags(user=Depends(get_current_user), service: DBService = Depends(get_service)) -> list[TagSchema]:
    return [TagSchema.model_validate(tag, from_attributes=True) for tag in service.get_tags()]