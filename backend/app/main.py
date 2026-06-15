from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routers
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in routers:
        app.include_router(router)

    @app.on_event("startup")
    def create_tables_for_dev() -> None:
        Base.metadata.create_all(bind=engine)

    return app


app = create_app()
