"""Shutdown helpers for the new workflow scheduler."""

from app.core.logging import get_logger
from .workflow_store import WorkflowStore
from .service import _existing_session_factory

logger = get_logger(__name__)


def fail_unfinished_jobs(session=None) -> dict[str, int]:  # noqa: ANN001
    """Mark all pending/running workflows and steps as failed before the backend exits."""
    if session is not None:
        return WorkflowStore(session_factory=_existing_session_factory(session)).fail_unfinished()
    return WorkflowStore().fail_unfinished()
