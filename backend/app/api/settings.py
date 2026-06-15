from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.settings import get_prompt_settings, update_prompt_settings
from app.schemas.domain import PromptSettingsRead, PromptSettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/prompts", response_model=PromptSettingsRead)
def read_prompts(db: Session = Depends(get_db)):
    return get_prompt_settings(db)


@router.put("/prompts", response_model=PromptSettingsRead)
def save_prompts(payload: PromptSettingsUpdate, db: Session = Depends(get_db)):
    return update_prompt_settings(db, payload)
