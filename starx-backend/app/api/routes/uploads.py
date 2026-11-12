from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, get_service
from app.models.user import User
from app.schemas.uploads import PresignUploadRequest, PresignUploadResponse
from app.services.db_service import DBService
from app.services.uploads import DirectUploadError, DirectUploadService

router = APIRouter()


def get_direct_upload_service(
    service: DBService = Depends(get_service),
) -> DirectUploadService:
    return DirectUploadService(service.session)


@router.post("/uploads/presign", response_model=PresignUploadResponse)
def presign_upload(
    payload: PresignUploadRequest,
    user: User = Depends(get_current_user),
    uploads: DirectUploadService = Depends(get_direct_upload_service),
) -> PresignUploadResponse:
    try:
        return uploads.create_presigned_upload(user_id=user.id, payload=payload)
    except DirectUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
