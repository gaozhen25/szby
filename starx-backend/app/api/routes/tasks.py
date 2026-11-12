from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, get_service
from app.models.user import User
from app.schemas.tasks import CreateTaskRequest, TaskSchema, UpdateTaskStatusRequest
from app.services.db_service import DBService, TaskCreationConflictError

router = APIRouter()


@router.get("/accounts/{account_id}/tasks", response_model=list[TaskSchema])
def list_tasks(
    account_id: str,
    limit: int = 100,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> list[TaskSchema]:
    return [TaskSchema.model_validate(task, from_attributes=True) for task in service.list_tasks(user.id, account_id, limit=limit)]


@router.post("/accounts/{account_id}/tasks", response_model=TaskSchema)
def create_task(
    account_id: str, payload: CreateTaskRequest, user: User = Depends(get_current_user), service: DBService = Depends(get_service)
) -> TaskSchema:
    try:
        task = service.create_task(
            user.id,
            account_id,
            payload.title,
            payload.type,
            payload.targetPlatform,
            creation_id=payload.creationId,
            body=payload.body,
            tags=payload.tags,
            assignee=payload.assignee,
            due_date=payload.dueDate,
            priority=payload.priority,
            handoff_note=payload.handoffNote,
        )
    except StopIteration:
        raise HTTPException(status_code=404, detail="creation not found for account") from None
    except TaskCreationConflictError:
        raise HTTPException(status_code=409, detail="creation already has a workflow task") from None
    return TaskSchema.model_validate(task, from_attributes=True)


@router.post("/accounts/{account_id}/tasks/{task_id}/duplicate", response_model=TaskSchema)
def duplicate_task(
    account_id: str,
    task_id: str,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> TaskSchema:
    try:
        task = service.duplicate_task(user.id, account_id, task_id)
    except StopIteration:
        raise HTTPException(status_code=404, detail="workflow task not found") from None
    return TaskSchema.model_validate(task, from_attributes=True)


@router.patch("/accounts/{account_id}/tasks/{task_id}/status", response_model=TaskSchema)
def update_task_status(
    account_id: str,
    task_id: str,
    payload: UpdateTaskStatusRequest,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> TaskSchema:
    task = service.update_task_status(user.id, account_id, task_id, payload.status)
    return TaskSchema.model_validate(task, from_attributes=True)
