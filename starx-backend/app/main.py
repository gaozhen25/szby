import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.services.competitor_monitoring.periodic_scheduler import (
    competitor_periodic_scheduler,
)
from app.services.own_content_analytics.periodic_scheduler import (
    own_dashboard_periodic_scheduler,
)
from app.services.tikhub_service import default_tikhub_runtime
from app.services.workflow.shutdown import fail_unfinished_jobs
from app.services.workflow import WorkflowScheduler
from app.services.digital_human.reconciler import digital_human_reconciler

configure_logging()
logger = get_logger("starx.main")
workflow_scheduler = WorkflowScheduler.get_instance()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    workflow_scheduler.start()
    competitor_periodic_scheduler.start()
    own_dashboard_periodic_scheduler.start()
    digital_human_reconciler.start()
    try:
        yield
    finally:
        await competitor_periodic_scheduler.stop()
        await own_dashboard_periodic_scheduler.stop()
        await digital_human_reconciler.stop()
        await workflow_scheduler.shutdown()
        await default_tikhub_runtime.aclose()
        mark_unfinished_jobs_failed_on_shutdown()


def mark_unfinished_jobs_failed_on_shutdown() -> None:
    counts = fail_unfinished_jobs()
    logger.info("unfinished jobs marked failed on shutdown: %s", counts)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info("request started: %s %s", request.method, request.url.path)
    response = await call_next(request)
    logger.info(
        "request completed: %s %s -> %s",
        request.method,
        request.url.path,
        response.status_code,
    )
    return response


@app.get(f"{settings.api_prefix}/health")
def healthcheck() -> dict[str, str]:
    logger.info("healthcheck requested")
    return {"status": "ok"}


app.include_router(api_router, prefix=settings.api_prefix)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=True)
