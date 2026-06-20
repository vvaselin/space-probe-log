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
from app.services.scheduler import run_simulation_scheduler

LOGGER = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    settings = get_settings()
    stop_event = asyncio.Event()
    scheduler_task = (
        asyncio.create_task(run_simulation_scheduler(stop_event))
        if settings.simulation_scheduler_enabled
        else None
    )
    try:
        yield
    finally:
        if scheduler_task is not None:
            stop_event.set()
            await scheduler_task


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
