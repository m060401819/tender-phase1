from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request

from app.api.router import api_router
from app.core.config import Settings, settings
from app.core.logging import REQUEST_ID_HEADER, build_log_extra, configure_logging, reset_request_id, set_request_id
from app.services import initialize_source_schedule_runtime, shutdown_source_schedule_runtime

LOGGER = logging.getLogger(__name__)

def create_app(app_settings: Settings | None = None) -> FastAPI:
    runtime_settings = app_settings or settings
    configure_logging(level=runtime_settings.log_level_value)

    @asynccontextmanager
    async def _app_lifespan(_: FastAPI):
        if not runtime_settings.source_scheduler_embedded_enabled:
            LOGGER.info(
                "embedded source scheduler disabled",
                extra=build_log_extra(
                    event="source_scheduler_embedded_disabled",
                    job_type="scheduled",
                    triggered_by="embedded_scheduler",
                ),
            )
            yield
            return

        scheduler_cleaned_up = False
        try:
            runtime = initialize_source_schedule_runtime(
                runtime_settings.database_url,
                refresh_interval_seconds=runtime_settings.source_scheduler_refresh_interval_seconds,
            )
            runtime.start()
            LOGGER.info(
                "embedded source scheduler started",
                extra=build_log_extra(
                    event="source_scheduler_started",
                    job_type="scheduled",
                    triggered_by="embedded_scheduler",
                    refresh_interval_seconds=runtime_settings.source_scheduler_refresh_interval_seconds,
                ),
            )
        except Exception:
            LOGGER.exception(
                "embedded source scheduler startup skipped",
                extra=build_log_extra(
                    event="source_scheduler_startup_skipped",
                    job_type="scheduled",
                    triggered_by="embedded_scheduler",
                    refresh_interval_seconds=runtime_settings.source_scheduler_refresh_interval_seconds,
                ),
            )
            shutdown_source_schedule_runtime()
            scheduler_cleaned_up = True
        try:
            yield
        finally:
            if not scheduler_cleaned_up:
                shutdown_source_schedule_runtime()

    app = FastAPI(title=runtime_settings.app_name, lifespan=_app_lifespan)

    @app.middleware("http")
    async def _request_context_middleware(request: Request, call_next):
        request_id, token = set_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            reset_request_id(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    app.include_router(api_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
