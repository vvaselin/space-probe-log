from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.time import utcnow
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import SchedulerLease, SimulationAction, SimulationClock, SimulationEvent
from app.services import scheduler
from app.services.auth import password_hash
from app.services.clock import reset_simulation_clock


def admin_test_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with TestingSession() as db:
            yield db

    settings = get_settings()
    previous = (
        settings.admin_username,
        settings.admin_password_hash,
        settings.admin_cookie_secure,
        settings.simulation_scheduler_enabled,
    )
    settings.admin_username = "operator"
    settings.admin_password_hash = password_hash.hash("test-password")
    settings.admin_cookie_secure = False
    settings.simulation_scheduler_enabled = False
    app.dependency_overrides[get_db] = override_db
    return engine, TestingSession, settings, previous


def cleanup_admin_test(settings, previous) -> None:
    app.dependency_overrides.clear()
    (
        settings.admin_username,
        settings.admin_password_hash,
        settings.admin_cookie_secure,
        settings.simulation_scheduler_enabled,
    ) = previous


def test_admin_login_session_csrf_and_logout() -> None:
    engine, _, settings, previous = admin_test_client()
    try:
        with TestClient(app) as client:
            assert client.get("/api/admin/session").status_code == 401
            assert client.post("/api/admin/login", json={"username": "operator", "password": "wrong"}).status_code == 401
            login = client.post("/api/admin/login", json={"username": "operator", "password": "test-password"})
            assert login.status_code == 200
            csrf = login.json()["csrf_token"]
            assert client.get("/api/admin/session").json()["username"] == "operator"
            assert client.patch("/api/simulation/clock", json={"clock_state": "paused"}).status_code == 403
            assert client.patch(
                "/api/simulation/clock",
                json={"clock_state": "paused"},
                headers={"X-CSRF-Token": csrf},
            ).status_code == 200
            assert client.post("/api/admin/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
            assert client.get("/api/admin/session").status_code == 401
    finally:
        cleanup_admin_test(settings, previous)
        engine.dispose()


def test_paused_tick_is_rejected_without_writes() -> None:
    engine, TestingSession, settings, previous = admin_test_client()
    try:
        with TestingSession() as db:
            reset_simulation_clock(db)
            clock = db.get(SimulationClock, 1)
            clock.clock_state = "paused"
            db.commit()
        with TestClient(app) as client:
            login = client.post("/api/admin/login", json={"username": "operator", "password": "test-password"})
            csrf = login.json()["csrf_token"]
            response = client.post("/api/simulation/tick", headers={"X-CSRF-Token": csrf})
            assert response.status_code == 409
        with TestingSession() as db:
            assert db.scalar(select(func.count()).select_from(SimulationAction)) == 0
            assert db.scalar(select(func.count()).select_from(SimulationEvent)) == 0
    finally:
        cleanup_admin_test(settings, previous)
        engine.dispose()


def test_scheduler_lease_is_exclusive_and_can_fail_over(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(scheduler, "SessionLocal", TestingSession)

    assert scheduler.acquire_scheduler_lease("owner-a") is True
    assert scheduler.acquire_scheduler_lease("owner-b") is False
    with TestingSession() as db:
        lease = db.get(SchedulerLease, scheduler.TICK_LEASE_NAME)
        lease.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert scheduler.acquire_scheduler_lease("owner-b") is True
    with TestingSession() as db:
        scheduler.clear_scheduler_lease(db)
        db.commit()
    assert scheduler.acquire_scheduler_lease("owner-c") is True
    engine.dispose()
