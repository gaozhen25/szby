from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user, get_service
from app.models.user import User
from app.schemas.knowledge_bases import (
    CreateKnowledgeBaseRequest,
    KnowledgeBaseListResponse,
    KnowledgeBaseSchema,
    UpdateKnowledgeBaseRequest,
)
from app.services.db_service import DBService

router = APIRouter()


@router.get("/knowledge-bases", response_model=KnowledgeBaseListResponse)
def list_knowledge_bases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
    keyword: str = Query("", max_length=80),
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> KnowledgeBaseListResponse:
    items, total, page_value, page_size_value = service.list_knowledge_bases(
        user.id,
        page=page,
        page_size=page_size,
        keyword=keyword,
    )
    return KnowledgeBaseListResponse(
        items=[KnowledgeBaseSchema.model_validate(item, from_attributes=True) for item in items],
        total=total,
        page=page_value,
        pageSize=page_size_value,
    )


@router.get("/knowledge-bases/{knowledge_base_id}", response_model=KnowledgeBaseSchema)
def get_knowledge_base(
    knowledge_base_id: str,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> KnowledgeBaseSchema:
    try:
        knowledge_base = service.get_knowledge_base(user.id, knowledge_base_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return KnowledgeBaseSchema.model_validate(knowledge_base, from_attributes=True)


@router.post("/knowledge-bases", response_model=KnowledgeBaseSchema)
def create_knowledge_base(
    payload: CreateKnowledgeBaseRequest,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> KnowledgeBaseSchema:
    try:
        knowledge_base = service.create_knowledge_base(
            user.id,
            payload.name,
            payload.productName,
            payload.productIntro,
            payload.brandStory,
            payload.price,
            payload.logoUrl,
            payload.imageMaterials,
            payload.contactInfo,
            payload.websiteUrl,
            payload.enabledFields,
            industry=payload.industry,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KnowledgeBaseSchema.model_validate(knowledge_base, from_attributes=True)


@router.patch("/knowledge-bases/{knowledge_base_id}", response_model=KnowledgeBaseSchema)
def update_knowledge_base(
    knowledge_base_id: str,
    payload: UpdateKnowledgeBaseRequest,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> KnowledgeBaseSchema:
    try:
        knowledge_base = service.update_knowledge_base(
            user.id,
            knowledge_base_id,
            name=payload.name,
            product_name=payload.productName,
            industry=payload.industry,
            product_intro=payload.productIntro,
            brand_story=payload.brandStory,
            price=payload.price,
            logo_url=payload.logoUrl,
            image_materials=payload.imageMaterials,
            contact_info=payload.contactInfo,
            website_url=payload.websiteUrl,
            enabled_fields=payload.enabledFields,
        )
    except ValueError as exc:
        status_code = 404 if "not available" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return KnowledgeBaseSchema.model_validate(knowledge_base, from_attributes=True)


@router.delete("/knowledge-bases/{knowledge_base_id}")
def delete_knowledge_base(
    knowledge_base_id: str,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> dict[str, bool]:
    try:
        deleted = service.delete_knowledge_base(user.id, knowledge_base_id)
    except ValueError as exc:
        status_code = 404 if "not available" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"ok": deleted}
