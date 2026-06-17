from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.settings import get_prompt_settings, update_prompt_settings
from app.schemas.domain import PromptSettingsRead, PromptSettingsUpdate, SimulationSettingsRead, SimulationSettingsUpdate
from app.services.clock import ensure_simulation_settings, update_simulation_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/prompts", response_model=PromptSettingsRead)
def read_prompts(db: Session = Depends(get_db)):
    return get_prompt_settings(db)


@router.put("/prompts", response_model=PromptSettingsRead)
def save_prompts(payload: PromptSettingsUpdate, db: Session = Depends(get_db)):
    return update_prompt_settings(db, payload)


@router.get("/simulation", response_model=SimulationSettingsRead)
def read_simulation_settings(db: Session = Depends(get_db)):
    settings = ensure_simulation_settings(db)
    db.commit()
    return settings


@router.patch("/simulation", response_model=SimulationSettingsRead)
def save_simulation_settings(payload: SimulationSettingsUpdate, db: Session = Depends(get_db)):
    settings = update_simulation_settings(db, payload)
    db.commit()
    db.refresh(settings)
    return settings
