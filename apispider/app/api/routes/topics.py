from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, get_service
from app.models.user import User
from app.schemas.generation import WorkflowSchema
from app.schemas.topics import FavoriteTopicSchema, TopicSchema
from app.services.db_service import DBService
from app.services.workflow import WorkflowScheduler, WorkflowService

router = APIRouter()


def get_topic_workflow_service(db_service: DBService = Depends(get_service)) -> WorkflowService:
    return WorkflowService(db_service.session)


def get_topic_refresh_scheduler() -> WorkflowScheduler:
    return WorkflowScheduler.get_instance()


@router.get("/accounts/{account_id}/topics", response_model=list[TopicSchema])
def list_topics(
    account_id: str,
    limit: int = 100,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> list[TopicSchema]:
    return [TopicSchema.model_validate(topic, from_attributes=True) for topic in service.list_topics(user.id, account_id, limit=limit)]


@router.get("/accounts/{account_id}/favorite-topics", response_model=list[FavoriteTopicSchema])
def list_favorite_topics(
    account_id: str,
    limit: int = 100,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> list[FavoriteTopicSchema]:
    return [
        FavoriteTopicSchema.model_validate(topic, from_attributes=True)
        for topic in service.list_favorite_topics(user.id, account_id, limit=limit)
    ]


@router.post("/accounts/{account_id}/favorite-topics/{topic_id}", response_model=FavoriteTopicSchema)
def favorite_topic(
    account_id: str,
    topic_id: str,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> FavoriteTopicSchema:
    try:
        topic = service.favorite_topic(user.id, account_id, topic_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail="topic is not available") from exc
    return FavoriteTopicSchema.model_validate(topic, from_attributes=True)


@router.delete("/accounts/{account_id}/favorite-topics/{favorite_id}", status_code=204)
def delete_favorite_topic(
    account_id: str,
    favorite_id: str,
    user: User = Depends(get_current_user),
    service: DBService = Depends(get_service),
) -> None:
    if not service.delete_favorite_topic(user.id, account_id, favorite_id):
        raise HTTPException(status_code=404, detail="favorite topic was not found")


@router.post("/accounts/{account_id}/topics/refresh-batch", response_model=WorkflowSchema)
def refresh_topics(
    account_id: str,
    user: User = Depends(get_current_user),
    workflows: WorkflowService = Depends(get_topic_workflow_service),
    scheduler: WorkflowScheduler = Depends(get_topic_refresh_scheduler),
) -> WorkflowSchema:
    try:
        workflow, is_new = workflows.create_topic_recommendation_job(user.id, account_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if is_new:
        try:
            scheduler.submit("topic_recommendation", workflow.id)
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            workflows.mark_topic_recommendation_job_failed(user.id, account_id, workflow.id, error)
            raise HTTPException(status_code=500, detail=f"failed to submit topic refresh workflow: {error}") from exc
    return workflow


@router.get("/accounts/{account_id}/topics/refresh-workflows/{workflow_id}", response_model=WorkflowSchema)
def get_topic_refresh_workflow(
    account_id: str,
    workflow_id: str,
    user: User = Depends(get_current_user),
    workflows: WorkflowService = Depends(get_topic_workflow_service),
) -> WorkflowSchema:
    try:
        return workflows.get_topic_recommendation_job(user.id, account_id, workflow_id)
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
