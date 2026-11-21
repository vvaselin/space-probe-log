from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def no_voyage_scheduler_or_real_llm() -> Generator[None, None, None]:
    # .env の設定に関係なく、テストでは航行のスケジューラを動かさず、本物のLLMも呼ばず、航行のDBにも触れない
    settings = get_settings()
    overrides = {
        "voyage_scheduler_enabled": False,
        "voyage_llm_route_provider": "mock",
        "voyage_llm_log_provider": "mock",
        "voyage_database_url": "sqlite://",
    }
    previous = {key: getattr(settings, key) for key in overrides}
    for key, value in overrides.items():
        setattr(settings, key, value)
    try:
        yield
    finally:
        for key, value in previous.items():
            setattr(settings, key, value)
