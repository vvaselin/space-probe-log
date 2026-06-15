from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.llm.factory import get_llm_client
from app.schemas.domain import LogListItem, ProbeRead, ResetRequest, SimulationStepResponse
from app.services.reset import reset_world
from app.services.simulation import run_step

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


@router.post("/step", response_model=SimulationStepResponse)
async def step(db: Session = Depends(get_db)):
    action, event, log, probe = await run_step(db, get_llm_client())
    return {
        "action": {
            "id": action.id,
            "proposed_action": action.proposed_action,
            "validated_action": action.validated_action,
            "target_id": action.target_id,
            "status": action.status,
            "validation_message": action.validation_message,
        },
        "event": {"id": event.id, "event_type": event.event_type, "summary": event.summary, "mission_time": event.mission_time},
        "log": LogListItem.model_validate(log),
        "probe": ProbeRead.model_validate(probe),
    }


@router.post("/reset", response_model=ProbeRead)
def reset(payload: ResetRequest, db: Session = Depends(get_db)):
    return reset_world(db, payload.world_seed)
