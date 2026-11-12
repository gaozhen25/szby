import json
import re
from typing import Any, ClassVar
from uuid import uuid4

from app.core.logging import get_logger
from app.db.models import WorkflowRecord, WorkflowStepRecord  # noqa: F401 — WorkflowStepRecord used by workflow_store

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def normalize_json(raw: Any) -> dict[str, Any] | None:
    """Parse an AI response into a dict, stripping markdown fences.

    Returns ``None`` when the result is empty / unparseable; the caller
    decides whether to raise or fall back.
    """
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").lstrip("\ufeff").strip()
    if not text:
        return None

    # ---- strip markdown fences ----
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```\s*$", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Models occasionally wrap JSON with reasoning or explanatory text. Use
        # raw_decode from every object boundary so braces in the preamble do not
        # make an otherwise valid object fail parsing.
        decoder = json.JSONDecoder()
        parsed = None
        parsed_length = -1
        for match in re.finditer(r"\{", text):
            try:
                candidate, end = decoder.raw_decode(text, match.start())
            except json.JSONDecodeError:
                continue
            candidate_length = end - match.start()
            if isinstance(candidate, dict) and candidate_length > parsed_length:
                parsed = candidate
                parsed_length = candidate_length
        if parsed is None:
            return None

    return parsed if isinstance(parsed, dict) else None


def new_id(prefix: str = "wf") -> str:
    return f"{prefix}_{uuid4().hex}"


# ---------------------------------------------------------------------------
# WorkflowStep  — pure AI unit (no DB access)
# ---------------------------------------------------------------------------

class WorkflowStep:
    """Pure AI unit run by the scheduler.

    Steps receive plain payloads, return plain payloads, and
    must not access the database.
    """

    sub_type: ClassVar[str] = "workflow_step"

    def __init__(self, *, ai_service: Any = None, storage: Any = None) -> None:
        self.ai_service = ai_service
        self.storage = storage

    async def execute(self, _payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# BaseWorkflow
# ---------------------------------------------------------------------------

class BaseWorkflow:
    """Workflow implementation base class.

    Subclasses define ``type``, optionally override ``record_class``, and
    implement ``execute()``.

    During execution the scheduler injects a ``WorkflowStore`` instance via
    ``self.store`` so the workflow can persist intermediate results and
    sub-steps with short-lived database sessions.
    """

    type: ClassVar[str] = "base"
    record_class: ClassVar[Any] = WorkflowRecord
    requires_ai: ClassVar[bool] = True

    def __init__(self, workflow_id: str, context: dict[str, Any] | None = None) -> None:
        self.workflow_id = workflow_id
        self.context = context or {}
        self.store: Any = None  # injected by scheduler before execute()

    async def execute(self) -> Any:
        raise NotImplementedError("Subclasses must implement the execute method.")


# ---------------------------------------------------------------------------
# WorkflowRegister
# ---------------------------------------------------------------------------

class WorkflowRegister:
    _registry: ClassVar[dict[str, type[BaseWorkflow]]] = {}

    @classmethod
    def register(cls, workflow_class: type[BaseWorkflow]) -> type[BaseWorkflow]:
        if not workflow_class.type:
            raise ValueError("workflow class must define 'type'")
        cls._registry[workflow_class.type] = workflow_class
        return workflow_class

    @classmethod
    def get(cls, workflow_type: str) -> type[BaseWorkflow]:
        try:
            return cls._registry[workflow_type]
        except KeyError as exc:
            raise KeyError(f"unregistered workflow type: {workflow_type}") from exc

    @classmethod
    def all_types(cls) -> list[str]:
        return list(cls._registry)
