from fastapi import APIRouter

from app.api.endpoints.admin_crawl_jobs import router as admin_crawl_jobs_router
from app.api.endpoints.admin_settings import router as admin_settings_router
from app.api.endpoints.admin_crawl_errors import router as admin_crawl_errors_router
from app.api.endpoints.admin_dashboard import router as admin_dashboard_router
from app.api.endpoints.admin_notices import router as admin_notices_router
from app.api.endpoints.admin_raw_documents import router as admin_raw_documents_router
from app.api.endpoints.admin_sources import router as admin_sources_router
from app.api.endpoints.crawl_errors import router as crawl_errors_router
from app.api.endpoints.crawl_jobs import router as crawl_jobs_router
from app.api.endpoints.health import router as health_router
from app.api.endpoints.notices import router as notices_router
from app.api.endpoints.reports import router as reports_router
from app.api.endpoints.settings import router as settings_router
from app.api.endpoints.raw_documents import router as raw_documents_router
from app.api.endpoints.stats import router as stats_router
from app.api.endpoints.sources import router as sources_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(crawl_jobs_router)
api_router.include_router(crawl_errors_router)
api_router.include_router(notices_router)
api_router.include_router(reports_router)
api_router.include_router(raw_documents_router)
api_router.include_router(stats_router)
api_router.include_router(settings_router)
api_router.include_router(sources_router)
api_router.include_router(admin_dashboard_router)
api_router.include_router(admin_crawl_jobs_router)
api_router.include_router(admin_crawl_errors_router)
api_router.include_router(admin_notices_router)
api_router.include_router(admin_raw_documents_router)
api_router.include_router(admin_sources_router)
api_router.include_router(admin_settings_router)
