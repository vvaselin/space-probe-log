from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.llm.factory import get_llm_client
from app.schemas.domain import LogListItem, ProbeRead, ResetRequest, SimulationClockRead, SimulationClockUpdate, SimulationStepResponse, SimulationTickResponse
from app.api.serializers import probe_read
from app.services.clock import advance_simulation_clock, clock_payload, reset_simulation_clock, update_simulation_clock
from app.services.reset import reset_world
from app.services.simulation import run_step, run_tick

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


@router.post("/step", response_model=SimulationStepResponse)
async def step(db: Session = Depends(get_db)):
    action, event, log, probe = await run_step(db, get_llm_client())
    probe_payload = probe_read(db, probe)
    clock = {
        "mission_clock": probe_payload.mission_clock,
        "sim_timestamp": probe_payload.sim_timestamp,
        "sim_elapsed_seconds": probe_payload.sim_elapsed_seconds,
    }
    return {
        "action": {
            "id": action.id,
            "proposed_action": action.proposed_action,
            "validated_action": action.validated_action,
            "target_id": action.target_id,
            "status": action.status,
            "validation_message": action.validation_message,
        },
        "event": {"id": event.id, "event_type": event.event_type, "summary": event.summary, "mission_time": event.mission_time, **clock},
        "log": LogListItem.model_validate(log),
        "probe": probe_payload,
        **clock,
    }


@router.post("/tick", response_model=SimulationTickResponse)
async def tick(db: Session = Depends(get_db)):
    action, event, log, probe, route = await run_tick(db, get_llm_client())
    probe_payload = probe_read(db, probe)
    clock = {
        "mission_clock": probe_payload.mission_clock,
        "sim_timestamp": probe_payload.sim_timestamp,
        "sim_elapsed_seconds": probe_payload.sim_elapsed_seconds,
    }
    return {
        "action": {
            "id": action.id,
            "proposed_action": action.proposed_action,
            "validated_action": action.validated_action,
            "target_id": action.target_id,
            "status": action.status,
            "validation_message": action.validation_message,
        },
        "event": {
            "id": event.id,
            "event_type": event.event_type,
            "summary": event.summary,
            "mission_time": event.mission_time,
            "log_worthy": bool(event.data.get("log_worthy")),
            **clock,
        },
        "log": LogListItem.model_validate(log) if log else None,
        "probe": probe_payload,
        "route": route,
        **clock,
    }


@router.post("/reset", response_model=ProbeRead)
def reset(payload: ResetRequest, db: Session = Depends(get_db)):
    probe = reset_world(db, payload.world_seed)
    reset_simulation_clock(db)
    db.commit()
    return probe_read(db, probe)


@router.get("/clock", response_model=SimulationClockRead)
def read_clock(db: Session = Depends(get_db)):
    clock, applied_seconds = advance_simulation_clock(db)
    db.commit()
    return clock_payload(clock, applied_seconds)


@router.patch("/clock", response_model=SimulationClockRead)
def patch_clock(payload: SimulationClockUpdate, db: Session = Depends(get_db)):
    clock, applied_seconds = update_simulation_clock(db, payload)
    db.commit()
    return clock_payload(clock, applied_seconds)


@router.post("/clock/reset", response_model=SimulationClockRead)
def reset_clock(db: Session = Depends(get_db)):
    clock = reset_simulation_clock(db)
    db.commit()
    return clock_payload(clock)
