"""Workflow services package."""

from app.services.competitor_monitoring import workflow as _competitor_monitoring  # noqa: F401

# Ensure all workflow classes are registered at import time
from .workflows import asset_persistence as _asset_persistence  # noqa: F401
from .workflows import video_analysis as _video_analysis  # noqa: F401
from .workflows import video_script as _video_script  # noqa: F401
from .workflows import video_script_rewrite as _video_script_rewrite  # noqa: F401
from .workflows import generation as _generation  # noqa: F401
from .workflows import topic_recommendation as _topic_recommendation  # noqa: F401
from .workflows import digital_human_enrollment as _digital_human_enrollment  # noqa: F401
from .scheduler import WorkflowScheduler
from .service import WorkflowService

__all__ = ["WorkflowScheduler", "WorkflowService"]
