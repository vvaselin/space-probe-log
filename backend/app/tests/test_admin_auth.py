from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.auth import password_hash


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
    previous = (settings.admin_username, settings.admin_password_hash, settings.admin_cookie_secure)
    settings.admin_username = "operator"
    settings.admin_password_hash = password_hash.hash("test-password")
    settings.admin_cookie_secure = False
    app.dependency_overrides[get_db] = override_db
    return engine, settings, previous


def cleanup_admin_test(settings, previous) -> None:
    app.dependency_overrides.clear()
    settings.admin_username, settings.admin_password_hash, settings.admin_cookie_secure = previous


def test_admin_login_session_csrf_and_logout() -> None:
    engine, settings, previous = admin_test_client()
    try:
        with TestClient(app) as client:
            assert client.get("/api/admin/session").status_code == 401
            assert client.post("/api/admin/login", json={"username": "operator", "password": "wrong"}).status_code == 401
            login = client.post("/api/admin/login", json={"username": "operator", "password": "test-password"})
            assert login.status_code == 200
            csrf = login.json()["csrf_token"]
            assert client.get("/api/admin/session").json()["username"] == "operator"
            # 管理者の操作には CSRF トークンが要る（航行の時計の変更で確かめる）
            assert client.patch("/api/voyage/clock", json={"mode": "manual"}).status_code == 403
            assert client.patch(
                "/api/voyage/clock",
                json={"mode": "manual"},
                headers={"X-CSRF-Token": csrf},
            ).status_code == 200
            assert client.post("/api/admin/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
            assert client.get("/api/admin/session").status_code == 401
    finally:
        cleanup_admin_test(settings, previous)
        engine.dispose()
