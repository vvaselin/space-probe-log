from typing import Any

from app.models import Probe


def probe_snapshot(probe: Probe) -> dict[str, Any]:
    return {
        "id": probe.id,
        "name": probe.name,
        "current_system_id": probe.current_system_id,
        "target_id": probe.target_id,
        "x": probe.x,
        "y": probe.y,
        "z": probe.z,
        "display_x": probe.display_x,
        "display_y": probe.display_y,
        "display_z": probe.display_z,
        "velocity": probe.velocity,
        "energy": probe.energy,
        "fuel": probe.fuel,
        "hull": probe.hull,
        "communication": probe.communication,
        "sensors": probe.sensors,
        "propulsion": probe.propulsion,
        "storage_used": probe.storage_used,
        "storage_capacity": probe.storage_capacity,
        "collected_resources": probe.collected_resources,
        "discovered_body_ids": probe.discovered_body_ids,
        "current_mission": probe.current_mission,
        "mission_time": probe.mission_time,
        "mission_clock": probe.mission_clock,
        "sim_timestamp": probe.sim_timestamp,
        "sim_elapsed_seconds": probe.sim_elapsed_seconds,
    }
