from fastapi import APIRouter

from app.api.routes.accounts import router as accounts_router
from app.api.routes.account_report_workflows import router as account_report_workflows_router
from app.api.routes.auth import router as auth_router
from app.api.routes.creations import router as creations_router
from app.api.routes.competitors import router as competitors_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.extract import router as extract_router
from app.api.routes.generation import router as generation_router
from app.api.routes.knowledge_bases import router as knowledge_bases_router
from app.api.routes.materials import router as materials_router
from app.api.routes.online_search import router as online_search_router
from app.api.routes.reports import router as reports_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.topics import router as topics_router

api_router = APIRouter()
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(accounts_router, tags=["accounts"])
api_router.include_router(account_report_workflows_router, tags=["account-report-workflows"])
api_router.include_router(knowledge_bases_router, tags=["knowledge-bases"])
api_router.include_router(topics_router, tags=["topics"])
api_router.include_router(creations_router, tags=["creations"])
api_router.include_router(competitors_router, tags=["competitors"])
api_router.include_router(extract_router, tags=["extract"])
api_router.include_router(generation_router, tags=["generation"])
api_router.include_router(tasks_router, tags=["tasks"])
api_router.include_router(materials_router, tags=["materials"])
api_router.include_router(online_search_router, tags=["online-search"])
api_router.include_router(dashboard_router, tags=["dashboard"])
api_router.include_router(reports_router, tags=["reports"])
