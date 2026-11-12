"""WorkflowScheduler — singleton, fire-and-forget, concurrency-controlled.

- ``submit()`` dispatches a background ``asyncio.Task`` and returns immediately.
  The frontend polls workflow status via API.
- Concurrency is gated by an internal ``asyncio.Semaphore``.
- Every DB operation goes through ``WorkflowStore`` which opens short-lived
  sessions — connections are never idle during AI calls.
- ``ai_service`` and ``storage`` are injected; if the workflow does not receive
  them via context, the scheduler's (or the global default) values are used.
"""

from __future__ import annotations

import asyncio
import threading
from time import perf_counter
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.ai_service import default_ai_service
from app.services.object_storage import default_object_storage
from .workflow_store import WorkflowStore
from .workflows.base import BaseWorkflow, WorkflowRegister

logger = get_logger(__name__)
TOKEN_MISSING_ERROR = "AI service token is not configured"


def _duration_ms(started_at: float) -> int:
    return max(int((perf_counter() - started_at) * 1000), 0)


class WorkflowScheduler:
    """Singleton scheduler — fire-and-forget execution with concurrency control.

    Usage::

        scheduler = WorkflowScheduler.get_instance(max_concurrent=5)
        scheduler.submit("video_analysis", workflow_id, context={...})
    """

    _instance: WorkflowScheduler | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def __init__(
        self,
        max_concurrent: int | None = None,
        *,
        ai_service: Any = None,
        storage: Any = None,
        store: WorkflowStore | None = None,
        session_factory: Any = None,
        use_default_concurrency: bool = True,
    ) -> None:
        if max_concurrent is None and not use_default_concurrency:
            resolved_max_concurrent = None
        elif max_concurrent is None:
            resolved_max_concurrent = max(int(settings.workflow_max_concurrent or 1), 1)
        else:
            resolved_max_concurrent = max(int(max_concurrent), 1)
        self._semaphore: asyncio.Semaphore | None = (
            asyncio.Semaphore(resolved_max_concurrent) if resolved_max_concurrent is not None else None
        )
        self._max_concurrent = resolved_max_concurrent
        self._ai_service = ai_service or default_ai_service
        self._storage = storage or default_object_storage
        if store is not None:
            self._store = store
        elif session_factory is not None:
            self._store = WorkflowStore(session_factory=session_factory)
        else:
            self._store = WorkflowStore()
        self._active_count = 0
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}

        # background-loop thread — bridges sync→async dispatch
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_lock = threading.Lock()
        self._tasks_lock = threading.Lock()
        self._accepting = True

    @classmethod
    def get_instance(
        cls,
        max_concurrent: int | None = None,
        *,
        ai_service: Any = None,
        storage: Any = None,
    ) -> WorkflowScheduler:
        if cls._instance is None:
            cls._instance = cls(max_concurrent=max_concurrent, ai_service=ai_service, storage=storage)
        return cls._instance

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @property
    def active_count(self) -> int:
        return self._active_count

    @property
    def max_concurrent(self) -> int | None:
        return self._max_concurrent

    @property
    def store(self) -> WorkflowStore:
        """Expose the store so workflows can persist data mid-execution."""
        return self._store

    def submit(self, type: str, workflow_id: str, context: dict[str, Any] | None = None) -> None:
        """Fire a workflow and return immediately.

        The workflow record MUST already exist in the DB (created by the route
        layer).  This method only dispatches the background task.

        Works from both sync and async contexts.  In sync contexts a background
        event-loop thread is started lazily.
        """
        if not self._accepting:
            raise RuntimeError("Workflow scheduler is shutting down")
        workflow_class = WorkflowRegister.get(type)
        if workflow_class is None:
            raise ValueError(f"Workflow type '{type}' is not registered.")

        ctx = context or {}
        loop = self._get_or_create_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._execute(workflow_class, type, workflow_id, ctx),
            loop,
        )
        with self._tasks_lock:
            self._running_tasks[workflow_id] = future  # type: ignore[assignment]

        def remove_finished(_future) -> None:
            with self._tasks_lock:
                self._running_tasks.pop(workflow_id, None)

        future.add_done_callback(remove_finished)

    def start(self) -> None:
        """Allow submissions after an application lifecycle restart."""
        self._accepting = True

    async def shutdown(self, timeout_seconds: float = 30) -> None:
        """Stop accepting work, cancel active futures, then stop the loop thread."""
        self._accepting = False
        with self._tasks_lock:
            futures = list(self._running_tasks.values())
        for future in futures:
            future.cancel()
        if futures:
            wrapped = [asyncio.wrap_future(future) for future in futures]
            try:
                await asyncio.wait_for(
                    asyncio.gather(*wrapped, return_exceptions=True),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                logger.error("workflow scheduler shutdown timed out active=%s", len(futures))

        with self._loop_lock:
            loop = self._loop
            thread = self._loop_thread
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            await asyncio.to_thread(thread.join, timeout_seconds)
        if thread is None or not thread.is_alive():
            if loop is not None and not loop.is_closed():
                loop.close()
            with self._loop_lock:
                self._loop = None
                self._loop_thread = None
            with self._tasks_lock:
                self._running_tasks.clear()

    def cancel(self, workflow_id: str) -> bool:
        """Request cancellation of a running workflow.  Returns False if not found."""
        with self._tasks_lock:
            fut = self._running_tasks.get(workflow_id)
        if fut is None:
            return False
        return fut.cancel()

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _get_or_create_loop(self) -> asyncio.AbstractEventLoop:
        """Return the scheduler's single dedicated event loop."""
        with self._loop_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop

            loop = asyncio.new_event_loop()
            started = threading.Event()

            def run_loop() -> None:
                asyncio.set_event_loop(loop)
                loop.call_soon(started.set)
                loop.run_forever()

            self._loop = loop
            self._loop_thread = threading.Thread(
                target=run_loop,
                daemon=True,
                name="wf-scheduler-loop",
            )
            self._loop_thread.start()
            started.wait()
            return loop

    async def _execute(
        self,
        workflow_class: type[BaseWorkflow],
        _type: str,
        workflow_id: str,
        context: dict[str, Any],
    ) -> None:
        """Background coroutine — acquires semaphore, runs workflow, persists result."""
        started_at = perf_counter()

        # ---- wait for concurrency slot ----
        if self._semaphore is not None:
            await self._semaphore.acquire()
        self._active_count += 1

        try:
            # ---- mark running ----
            self._store.mark_running(workflow_id, record_class=workflow_class.record_class)
            logger.info("workflow started type=%s workflow_id=%s", _type, workflow_id)
            logger.info("generation job started job_id=%s job_type=%s", workflow_id, _type)

            if workflow_class.requires_ai and getattr(self._ai_service, "token", None) == "":
                self._store.mark_failed(workflow_id, TOKEN_MISSING_ERROR, record_class=workflow_class.record_class)
                logger.error(
                    "workflow failed type=%s workflow_id=%s total_duration_ms=%s error=%s",
                    _type,
                    workflow_id,
                    _duration_ms(started_at),
                    TOKEN_MISSING_ERROR,
                )
                return

            # ---- build workflow instance, inject dependencies ----
            workflow = workflow_class(workflow_id, context)

            # inject ai_service / storage: prefer context, fall back to scheduler defaults
            if not getattr(workflow, "ai_service", None):
                workflow.ai_service = context.get("_ai_service") or self._ai_service
            if not getattr(workflow, "storage", None):
                workflow.storage = context.get("_storage") or self._storage

            # inject store so workflow can persist mid-execution
            workflow.store = self._store

            # ---- execute ----
            result = await workflow.execute()

            # ---- mark completed ----
            if isinstance(result, dict):
                self._store.mark_completed(workflow_id, result=result, record_class=workflow_class.record_class)
            else:
                self._store.mark_completed(workflow_id, record_class=workflow_class.record_class)
            logger.info("workflow completed type=%s workflow_id=%s", _type, workflow_id)
            logger.info(
                "generation job completed job_id=%s total_duration_ms=%s",
                workflow_id,
                _duration_ms(started_at),
            )

        except asyncio.CancelledError:
            self._store.mark_cancelled(workflow_id, record_class=workflow_class.record_class)
            logger.warning("workflow cancelled type=%s workflow_id=%s", _type, workflow_id)
        except Exception as exc:
            error = _exception_message(exc)
            self._store.mark_failed(workflow_id, error, record_class=workflow_class.record_class)
            logger.error(
                "workflow failed type=%s workflow_id=%s total_duration_ms=%s error=%s",
                _type,
                workflow_id,
                _duration_ms(started_at),
                error,
                exc_info=True,
            )
        finally:
            self._active_count -= 1
            if self._semaphore is not None:
                self._semaphore.release()


def _exception_message(exc: BaseException) -> str:
    original = getattr(exc, "orig", None)
    if original is not None:
        msg = str(original).strip()
        if msg:
            return msg
    msg = str(exc).strip()
    return msg or exc.__class__.__name__
