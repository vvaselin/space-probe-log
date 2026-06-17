from datetime import UTC

from sqlalchemy.orm import Session

from app.models import MISSION_START_AT, Probe
from app.repositories.read import system_detail
from app.schemas.domain import ProbeRead
from app.services.clock import advance_simulation_clock
from app.services.navigation import latest_navigation_state, navigation_payload, synchronize_navigation
from app.services.probe_spec import probe_specification


def probe_read(db: Session, probe: Probe) -> ProbeRead:
    clock, _ = advance_simulation_clock(db)
    nav_state = latest_navigation_state(db, probe)
    sim_dt = clock.simulation_datetime if clock.simulation_datetime.tzinfo else clock.simulation_datetime.replace(tzinfo=UTC)
    nav_target = system_detail(db, nav_state.destination_system_id) if nav_state else None
    synchronize_navigation(db, probe, nav_state, nav_target, sim_dt)
    payload = ProbeRead.model_validate(probe).model_dump()
    payload["specification"] = probe_specification().model_dump()
    payload["navigation"] = navigation_payload(probe, nav_state, sim_dt)
    payload["simulation_datetime"] = sim_dt
    payload["mission_clock"] = sim_dt.strftime("%Y/%m/%d %H:%M:%S UTC")
    payload["sim_timestamp"] = sim_dt.isoformat().replace("+00:00", "Z")
    payload["sim_elapsed_seconds"] = max(0, int((sim_dt - MISSION_START_AT).total_seconds()))
    return ProbeRead.model_validate(payload)
