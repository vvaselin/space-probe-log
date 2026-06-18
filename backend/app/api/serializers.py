from datetime import UTC

from sqlalchemy.orm import Session

from app.models import MISSION_START_AT, Probe
from app.schemas.domain import ProbeRead
from app.services.clock import ensure_simulation_clock
from app.services.navigation import latest_navigation_state, navigation_payload
from app.services.probe_spec import probe_specification


def probe_read(db: Session, probe: Probe) -> ProbeRead:
    clock = ensure_simulation_clock(db)
    nav_state = latest_navigation_state(db, probe)
    sim_dt = clock.simulation_datetime if clock.simulation_datetime.tzinfo else clock.simulation_datetime.replace(tzinfo=UTC)
    payload = ProbeRead.model_validate(probe).model_dump()
    payload["specification"] = probe_specification().model_dump()
    payload["navigation"] = navigation_payload(probe, nav_state, sim_dt)
    payload["simulation_datetime"] = sim_dt
    payload["mission_clock"] = sim_dt.strftime("%Y/%m/%d %H:%M:%S UTC")
    payload["sim_timestamp"] = sim_dt.isoformat().replace("+00:00", "Z")
    payload["sim_elapsed_seconds"] = max(0, int((sim_dt - MISSION_START_AT).total_seconds()))
    return ProbeRead.model_validate(payload)
