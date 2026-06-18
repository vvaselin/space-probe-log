from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.serializers import probe_read
from app.schemas.domain import ProbeNavigationRead, ProbeRead, ProbeSpecification
from app.services.clock import advance_simulation_clock, ensure_simulation_clock
from app.services.navigation import latest_navigation_state, navigation_payload, synchronize_navigation
from app.repositories.read import system_detail
from app.services.probe_spec import probe_specification
from app.services.simulation import ensure_probe
from app.services.auth import require_admin

router = APIRouter(prefix="/api/probe", tags=["probe"])


@router.get("", response_model=ProbeRead)
def get_probe(db: Session = Depends(get_db)):
    probe = ensure_probe(db)
    return probe_read(db, probe)


@router.get("/specification", response_model=ProbeSpecification)
def get_probe_specification():
    return probe_specification()


@router.get("/navigation", response_model=ProbeNavigationRead)
def get_probe_navigation(db: Session = Depends(get_db)):
    probe = ensure_probe(db)
    clock = ensure_simulation_clock(db)
    state = latest_navigation_state(db, probe)
    return navigation_payload(probe, state, clock.simulation_datetime)


@router.post("/navigation/sync", response_model=ProbeNavigationRead)
def sync_probe_navigation(db: Session = Depends(get_db), _admin=Depends(require_admin)):
    probe = ensure_probe(db)
    clock, _ = advance_simulation_clock(db)
    state = latest_navigation_state(db, probe)
    target = system_detail(db, state.destination_system_id) if state else None
    synchronize_navigation(db, probe, state, target, clock.simulation_datetime)
    db.commit()
    return navigation_payload(probe, state, clock.simulation_datetime)
