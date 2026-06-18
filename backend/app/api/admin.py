from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import AdminSession
from app.schemas.domain import AdminLoginRequest, AdminSessionRead
from app.services.auth import authenticate_admin, current_admin_session, require_admin


router = APIRouter(prefix="/api/admin", tags=["admin"])


def session_payload(session: AdminSession) -> AdminSessionRead:
    return AdminSessionRead(
        authenticated=True,
        username=session.username,
        csrf_token=session.csrf_token,
        expires_at=session.expires_at,
    )


@router.post("/login", response_model=AdminSessionRead)
def login(payload: AdminLoginRequest, response: Response, db: Session = Depends(get_db)):
    settings = get_settings()
    raw_token, session = authenticate_admin(db, payload.username, payload.password)
    response.set_cookie(
        key=settings.admin_session_cookie_name,
        value=raw_token,
        max_age=settings.admin_session_ttl_seconds,
        httponly=True,
        secure=settings.admin_cookie_secure,
        samesite="strict",
        path="/api",
    )
    return session_payload(session)


@router.get("/session", response_model=AdminSessionRead)
def read_session(session: AdminSession = Depends(current_admin_session)):
    return session_payload(session)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    session: AdminSession = Depends(require_admin),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    db.delete(session)
    db.commit()
    response.delete_cookie(settings.admin_session_cookie_name, path="/api")
