from datetime import UTC, datetime, timedelta
import hashlib
import secrets

from fastapi import Depends, Header, HTTPException, Request, status
from pwdlib import PasswordHash
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.db.session import get_db
from app.models import AdminSession


password_hash = PasswordHash.recommended()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate_admin(db: Session, username: str, password: str) -> tuple[str, AdminSession]:
    settings = get_settings()
    if not settings.admin_password_hash:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Admin login is not configured")
    username_valid = secrets.compare_digest(username, settings.admin_username)
    try:
        password_valid = password_hash.verify(password, settings.admin_password_hash)
    except Exception:
        password_valid = False
    if not username_valid or not password_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    now = utcnow()
    db.execute(delete(AdminSession).where(AdminSession.expires_at <= now))
    raw_token = secrets.token_urlsafe(48)
    session = AdminSession(
        token_hash=token_hash(raw_token),
        username=settings.admin_username,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=now + timedelta(seconds=settings.admin_session_ttl_seconds),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return raw_token, session


def current_admin_session(request: Request, db: Session = Depends(get_db)) -> AdminSession:
    settings = get_settings()
    raw_token = request.cookies.get(settings.admin_session_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required")
    session = db.get(AdminSession, token_hash(raw_token))
    if session is None or _aware(session.expires_at) <= datetime.now(UTC):
        if session is not None:
            db.delete(session)
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session expired")
    return session


def require_admin(
    session: AdminSession = Depends(current_admin_session),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> AdminSession:
    if not csrf_token or not secrets.compare_digest(csrf_token, session.csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    return session
