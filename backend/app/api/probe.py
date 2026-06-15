from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.domain import ProbeRead
from app.services.simulation import ensure_probe

router = APIRouter(prefix="/api/probe", tags=["probe"])


@router.get("", response_model=ProbeRead)
def get_probe(db: Session = Depends(get_db)):
    return ensure_probe(db)
