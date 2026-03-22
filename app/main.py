from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings
from app.services import initialize_source_schedule_runtime, shutdown_source_schedule_runtime


@asynccontextmanager
async def _app_lifespan(_: FastAPI):
    try:
        runtime = initialize_source_schedule_runtime(settings.database_url)
        runtime.start()
    except Exception as exc:
        print(f"[source-scheduler] startup skipped: {exc}")
        shutdown_source_schedule_runtime()
    try:
        yield
    finally:
        shutdown_source_schedule_runtime()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=_app_lifespan)

    app.include_router(api_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
