import asyncio
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from app.api import routers
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine
from app.voyage.scheduler import run_voyage_scheduler
from app.voyage.service import ensure_voyage
from app.voyage.store import cached_session_factory

LOGGER = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    settings = get_settings()
    with cached_session_factory(settings.voyage_database_url)() as voyage_db:
        ensure_voyage(voyage_db, settings.default_world_seed)
    stop_event = asyncio.Event()
    voyage_task = asyncio.create_task(run_voyage_scheduler(stop_event)) if settings.voyage_scheduler_enabled else None
    try:
        yield
    finally:
        stop_event.set()
        if voyage_task is not None:
            await voyage_task


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in routers:
        app.include_router(router)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled API error for %s %s", request.method, request.url.path, exc_info=exc)
        headers = {}
        origin = request.headers.get("origin")
        if origin and origin in settings.cors_origin_list:
            headers = {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
                "Vary": "Origin",
            }
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error": exc.__class__.__name__},
            headers=headers,
        )

    return app


app = create_app()
