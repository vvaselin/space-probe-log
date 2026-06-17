import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models import Probe, ProbeNavigationState, SimulationEvent, StarSystem
from app.schemas.domain import DriveMode, NavigationPhase
from app.services.clock import mission_clock_text
from app.services.probe_spec import probe_specification

PARSEC_KM = 30_856_775_814_913.672
AU_KM = 149_597_870.7
SYSTEM_DEPARTURE_SECONDS = 5 * 60
SYSTEM_ARRIVAL_SECONDS = 5 * 60
MIN_ACCELERATION_SECONDS = 5 * 60
MAX_ACCELERATION_SECONDS = 30 * 60
DRIVE_PROFILE = "instant_high_output_v1"

PHASE_LABELS = {
    NavigationPhase.system_departure.value: "恒星系離脱",
    NavigationPhase.accelerating.value: "加速",
    NavigationPhase.interstellar_cruise.value: "巡航",
    NavigationPhase.decelerating.value: "減速",
    NavigationPhase.system_arrival.value: "到着処理",
}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(a, b, strict=True)))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _scale(a: tuple[float, float, float], factor: float) -> tuple[float, float, float]:
    return a[0] * factor, a[1] * factor, a[2] * factor


def _vector_from_payload(payload: dict | None, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    if not payload:
        return fallback
    return (
        float(payload.get("x", fallback[0])),
        float(payload.get("y", fallback[1])),
        float(payload.get("z", fallback[2])),
    )


def latest_navigation_state(db: Session, probe: Probe) -> ProbeNavigationState | None:
    return db.scalar(
        select(ProbeNavigationState)
        .where(ProbeNavigationState.probe_id == probe.id)
        .order_by(ProbeNavigationState.id.desc())
        .limit(1)
    )


def active_navigation_state(db: Session, probe: Probe) -> ProbeNavigationState | None:
    state = latest_navigation_state(db, probe)
    if state and state.phase != NavigationPhase.arrived.value:
        return state
    return None


def physical_distance_pc(probe: Probe, target: StarSystem) -> float:
    return _distance((probe.x, probe.y, probe.z), (target.x, target.y, target.z))


def _schedule_for_distance(distance_km: float, cruise_speed_m_s: float) -> dict:
    cruise_seconds_at_speed = distance_km * 1000 / max(cruise_speed_m_s, 1)
    acceleration_seconds = min(MAX_ACCELERATION_SECONDS, max(MIN_ACCELERATION_SECONDS, cruise_seconds_at_speed * 0.04))
    deceleration_seconds = acceleration_seconds
    cruise_seconds = max(0.0, cruise_seconds_at_speed - acceleration_seconds * 0.5 - deceleration_seconds * 0.5)
    departure_end = SYSTEM_DEPARTURE_SECONDS
    acceleration_end = departure_end + acceleration_seconds
    cruise_end = acceleration_end + cruise_seconds
    deceleration_end = cruise_end + deceleration_seconds
    arrival_end = deceleration_end + SYSTEM_ARRIVAL_SECONDS
    return {
        "system_departure_end_s": departure_end,
        "acceleration_end_s": acceleration_end,
        "cruise_end_s": cruise_end,
        "deceleration_end_s": deceleration_end,
        "arrival_end_s": arrival_end,
        "acceleration_seconds": acceleration_seconds,
        "cruise_seconds": cruise_seconds,
        "deceleration_seconds": deceleration_seconds,
        "drive_profile": DRIVE_PROFILE,
    }


def _sync_navigation_spec(state: ProbeNavigationState) -> None:
    if state.phase == NavigationPhase.arrived.value:
        return
    spec = probe_specification()
    existing_schedule = state.schedule or {}
    if (
        math.isclose(state.cruise_speed_m_s, spec.cruise_speed_m_s)
        and math.isclose(state.max_speed_m_s, spec.max_cruise_speed_m_s)
        and existing_schedule.get("drive_profile") == DRIVE_PROFILE
    ):
        return
    schedule = _schedule_for_distance(state.total_distance_km, spec.cruise_speed_m_s)
    for key in (
        "origin_position_pc",
        "origin_display_position",
        "destination_position_pc",
        "destination_display_position",
    ):
        if key in existing_schedule:
            schedule[key] = existing_schedule[key]
    state.cruise_speed_m_s = spec.cruise_speed_m_s
    state.max_speed_m_s = spec.max_cruise_speed_m_s
    state.schedule = schedule
    state.eta_datetime = _aware(state.started_at) + timedelta(seconds=schedule["arrival_end_s"])


def begin_navigation(db: Session, probe: Probe, target: StarSystem, simulation_datetime: datetime) -> ProbeNavigationState:
    existing = active_navigation_state(db, probe)
    if existing and existing.destination_system_id == target.id:
        return existing
    now = _aware(simulation_datetime)
    spec = probe_specification()
    distance_pc = physical_distance_pc(probe, target)
    distance_km = distance_pc * PARSEC_KM
    schedule = _schedule_for_distance(distance_km, spec.cruise_speed_m_s)
    schedule = {
        **schedule,
        "origin_position_pc": {"x": probe.x, "y": probe.y, "z": probe.z},
        "origin_display_position": {"x": probe.display_x, "y": probe.display_y, "z": probe.display_z},
        "destination_position_pc": {"x": target.x, "y": target.y, "z": target.z},
        "destination_display_position": {"x": target.display_x, "y": target.display_y, "z": target.display_z},
    }
    state = ProbeNavigationState(
        probe_id=probe.id,
        origin_system_id=probe.current_system_id,
        destination_system_id=target.id,
        destination_name=target.name,
        phase=NavigationPhase.system_departure.value,
        drive_mode=DriveMode.conventional.value,
        started_at=now,
        eta_datetime=now + timedelta(seconds=schedule["arrival_end_s"]),
        total_distance_pc=distance_pc,
        total_distance_km=distance_km,
        remaining_distance_pc=distance_pc,
        remaining_distance_km=distance_km,
        progress=0.0,
        current_speed_m_s=0.0,
        cruise_speed_m_s=spec.cruise_speed_m_s,
        max_speed_m_s=spec.max_cruise_speed_m_s,
        event_keys=[],
        schedule=schedule,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(state)
    db.flush()
    return state


def _phase_for_elapsed(state: ProbeNavigationState, elapsed_seconds: float) -> tuple[NavigationPhase, DriveMode, float]:
    schedule = state.schedule or {}
    departure_end = float(schedule.get("system_departure_end_s", SYSTEM_DEPARTURE_SECONDS))
    acceleration_end = float(schedule.get("acceleration_end_s", departure_end + MIN_ACCELERATION_SECONDS))
    cruise_end = float(schedule.get("cruise_end_s", acceleration_end))
    deceleration_end = float(schedule.get("deceleration_end_s", cruise_end + MIN_ACCELERATION_SECONDS))
    arrival_end = float(schedule.get("arrival_end_s", deceleration_end + SYSTEM_ARRIVAL_SECONDS))
    if elapsed_seconds >= arrival_end:
        return NavigationPhase.arrived, DriveMode.conventional, 0.0
    if elapsed_seconds >= deceleration_end:
        return NavigationPhase.system_arrival, DriveMode.conventional, 0.0
    if elapsed_seconds >= cruise_end:
        decel_span = max(1.0, deceleration_end - cruise_end)
        factor = max(0.0, 1.0 - (elapsed_seconds - cruise_end) / decel_span)
        return NavigationPhase.decelerating, DriveMode.piano_drive, state.cruise_speed_m_s * factor
    if elapsed_seconds >= acceleration_end:
        return NavigationPhase.interstellar_cruise, DriveMode.piano_drive, state.cruise_speed_m_s
    if elapsed_seconds >= departure_end:
        accel_span = max(1.0, acceleration_end - departure_end)
        factor = min(1.0, (elapsed_seconds - departure_end) / accel_span)
        return NavigationPhase.accelerating, DriveMode.piano_drive, state.cruise_speed_m_s * factor
    return NavigationPhase.system_departure, DriveMode.conventional, 0.0


def _travel_distance_fraction(state: ProbeNavigationState, elapsed_seconds: float) -> float:
    schedule = state.schedule or {}
    departure_end = float(schedule.get("system_departure_end_s", SYSTEM_DEPARTURE_SECONDS))
    acceleration_end = float(schedule.get("acceleration_end_s", departure_end + MIN_ACCELERATION_SECONDS))
    cruise_end = float(schedule.get("cruise_end_s", acceleration_end))
    deceleration_end = float(schedule.get("deceleration_end_s", cruise_end + MIN_ACCELERATION_SECONDS))
    arrival_end = float(schedule.get("arrival_end_s", deceleration_end + SYSTEM_ARRIVAL_SECONDS))
    accel_span = max(1.0, acceleration_end - departure_end)
    cruise_span = max(0.0, cruise_end - acceleration_end)
    decel_span = max(1.0, deceleration_end - cruise_end)
    cruise_speed = max(0.0, state.cruise_speed_m_s)
    acceleration = cruise_speed / accel_span
    deceleration = cruise_speed / decel_span
    accel_distance = 0.5 * acceleration * accel_span * accel_span
    cruise_distance = cruise_speed * cruise_span
    decel_distance = 0.5 * cruise_speed * decel_span
    total_motion_distance = max(1.0, accel_distance + cruise_distance + decel_distance)

    if elapsed_seconds <= departure_end:
        travelled = 0.0
    elif elapsed_seconds < acceleration_end:
        t = elapsed_seconds - departure_end
        travelled = 0.5 * acceleration * t * t
    elif elapsed_seconds < cruise_end:
        t = elapsed_seconds - acceleration_end
        travelled = accel_distance + cruise_speed * t
    elif elapsed_seconds < deceleration_end:
        t = elapsed_seconds - cruise_end
        travelled = accel_distance + cruise_distance + cruise_speed * t - 0.5 * deceleration * t * t
    elif elapsed_seconds < arrival_end:
        travelled = total_motion_distance
    else:
        travelled = total_motion_distance
    return max(0.0, min(1.0, travelled / total_motion_distance))


def navigation_display_velocity(
    state: ProbeNavigationState,
    display_start: tuple[float, float, float],
    display_target: tuple[float, float, float],
) -> tuple[float, float, float]:
    display_delta = _sub(display_target, display_start)
    display_distance = _distance(display_start, display_target)
    if state.current_speed_m_s <= 0 or state.total_distance_km <= 0 or display_distance <= 0:
        return 0.0, 0.0, 0.0
    display_units_per_sim_second = (state.current_speed_m_s / 1000.0) / state.total_distance_km * display_distance
    return _scale(display_delta, display_units_per_sim_second / display_distance)


def _sync_probe_mission_text(probe: Probe, state: ProbeNavigationState) -> None:
    if state.phase == NavigationPhase.arrived.value:
        probe.current_mission = f"{state.destination_name}に到着。次の航路選定待ち。"
        return
    phase_label = PHASE_LABELS.get(state.phase, "航行")
    probe.current_mission = f"{state.destination_name}へ向けて{phase_label}中。"


def synchronize_navigation(
    db: Session,
    probe: Probe,
    state: ProbeNavigationState | None,
    target: StarSystem | None,
    simulation_datetime: datetime,
) -> ProbeNavigationState | None:
    if state is None:
        return state
    if state.phase == NavigationPhase.arrived.value:
        state.progress = 1.0
        state.remaining_distance_km = 0.0
        state.remaining_distance_pc = 0.0
        state.current_speed_m_s = 0.0
        state.drive_mode = DriveMode.conventional.value
        if state.arrived_at is None:
            state.arrived_at = _aware(simulation_datetime)
        if target is not None:
            schedule = state.schedule or {}
            physical_target = _vector_from_payload(schedule.get("destination_position_pc"), (target.x, target.y, target.z))
            display_target = _vector_from_payload(schedule.get("destination_display_position"), (target.display_x, target.display_y, target.display_z))
            probe.x, probe.y, probe.z = physical_target
            probe.display_x, probe.display_y, probe.display_z = display_target
            probe.current_system_id = target.id
        probe.target_id = None
        probe.velocity = 0.0
        _sync_probe_mission_text(probe, state)
        state.updated_at = utcnow()
        db.flush()
        return state
    if target is None:
        return state
    _sync_navigation_spec(state)
    sim_dt = _aware(simulation_datetime)
    elapsed_seconds = max(0.0, (sim_dt - _aware(state.started_at)).total_seconds())
    phase, drive_mode, speed_m_s = _phase_for_elapsed(state, elapsed_seconds)
    progress = 1.0 if phase == NavigationPhase.arrived else max(0.0, min(0.995, _travel_distance_fraction(state, elapsed_seconds)))
    remaining_km = state.total_distance_km * (1.0 - progress)
    remaining_pc = state.total_distance_pc * (1.0 - progress)

    state.phase = phase.value
    state.drive_mode = drive_mode.value
    state.current_speed_m_s = min(speed_m_s, state.max_speed_m_s)
    state.progress = progress
    state.remaining_distance_km = remaining_km
    state.remaining_distance_pc = remaining_pc
    state.updated_at = utcnow()

    schedule = state.schedule or {}
    display_start = _vector_from_payload(schedule.get("origin_display_position"), (probe.display_x, probe.display_y, probe.display_z))
    physical_start = _vector_from_payload(schedule.get("origin_position_pc"), (probe.x, probe.y, probe.z))
    display_target = _vector_from_payload(schedule.get("destination_display_position"), (target.display_x, target.display_y, target.display_z))
    physical_target = _vector_from_payload(schedule.get("destination_position_pc"), (target.x, target.y, target.z))
    probe.display_x = _lerp(display_start[0], display_target[0], progress)
    probe.display_y = _lerp(display_start[1], display_target[1], progress)
    probe.display_z = _lerp(display_start[2], display_target[2], progress)
    probe.x = _lerp(physical_start[0], physical_target[0], progress)
    probe.y = _lerp(physical_start[1], physical_target[1], progress)
    probe.z = _lerp(physical_start[2], physical_target[2], progress)
    probe.velocity = state.current_speed_m_s

    if phase == NavigationPhase.arrived:
        probe.x, probe.y, probe.z = physical_target
        probe.display_x, probe.display_y, probe.display_z = display_target
        probe.current_system_id = target.id
        probe.target_id = None
        probe.velocity = 0.0
        state.remaining_distance_km = 0.0
        state.remaining_distance_pc = 0.0
        state.progress = 1.0
        state.arrived_at = sim_dt
        state.current_speed_m_s = 0.0
        state.drive_mode = DriveMode.conventional.value
        state.phase = NavigationPhase.arrived.value
        _sync_probe_mission_text(probe, state)
        _record_navigation_event_once(db, probe, state, "arrival")
    else:
        probe.target_id = state.destination_system_id
        _sync_probe_mission_text(probe, state)
    db.flush()
    return state


def _record_navigation_event_once(db: Session, probe: Probe, state: ProbeNavigationState, event_key: str) -> None:
    full_key = f"navigation:{state.id}:{event_key}"
    if full_key in (state.event_keys or []):
        return
    state.event_keys = [*(state.event_keys or []), full_key]
    db.add(
        SimulationEvent(
            probe_id=probe.id,
            event_type="navigation_arrived",
            mission_time=probe.mission_time,
            summary=f"{state.destination_name}へ到着しました。航行イベントを確定しました。",
            data={
                "event_key": full_key,
                "simulation_datetime": state.arrived_at.isoformat().replace("+00:00", "Z") if state.arrived_at else None,
                "mission_clock": mission_clock_text(state.arrived_at or state.eta_datetime),
                "navigation_phase": state.phase,
                "route_phase": state.phase,
                "drive_mode": state.drive_mode,
                "current_speed_m_s": 0.0,
                "destination_id": state.destination_system_id,
                "destination_name": state.destination_name,
                "remaining_distance_km": 0.0,
                "remaining_distance_pc": 0.0,
                "remaining_distance": 0.0,
                "eta_datetime": _aware(state.eta_datetime).isoformat().replace("+00:00", "Z"),
            },
        )
    )


def _sampled_at_text(sampled_at: datetime | None) -> str | None:
    return _aware(sampled_at).isoformat().replace("+00:00", "Z") if sampled_at else None


def navigation_payload(probe: Probe, state: ProbeNavigationState | None, sampled_at: datetime | None = None) -> dict:
    sampled_at_text = _sampled_at_text(sampled_at)
    local_position = None
    if probe.current_system_id == "sol":
        local_position = {"x": probe.x, "y": probe.y, "z": probe.z}
    if state is None:
        return {
            "active": False,
            "phase": NavigationPhase.idle.value if not probe.target_id else NavigationPhase.local_navigation.value,
            "drive_mode": DriveMode.conventional.value,
            "galactic_position_pc": {"x": probe.x, "y": probe.y, "z": probe.z},
            "local_position_au": local_position,
            "display_position": {"x": probe.display_x, "y": probe.display_y, "z": probe.display_z},
            "sampled_at": sampled_at_text,
        }
    eta_datetime = _aware(state.eta_datetime).isoformat().replace("+00:00", "Z")
    started_at = _aware(state.started_at).isoformat().replace("+00:00", "Z")
    arrived_at = _aware(state.arrived_at).isoformat().replace("+00:00", "Z") if state.arrived_at else None
    schedule = state.schedule or {}
    display_start = _vector_from_payload(schedule.get("origin_display_position"), (probe.display_x, probe.display_y, probe.display_z))
    display_target = _vector_from_payload(schedule.get("destination_display_position"), (probe.display_x, probe.display_y, probe.display_z))
    display_velocity = navigation_display_velocity(state, display_start, display_target)
    return {
        "active": state.phase != NavigationPhase.arrived.value,
        "phase": state.phase,
        "drive_mode": state.drive_mode,
        "origin_system_id": state.origin_system_id,
        "destination_system_id": state.destination_system_id,
        "destination_name": state.destination_name,
        "started_at": started_at,
        "eta_datetime": eta_datetime,
        "arrived_at": arrived_at,
        "sampled_at": sampled_at_text,
        "total_distance_pc": state.total_distance_pc,
        "total_distance_km": state.total_distance_km,
        "remaining_distance_pc": state.remaining_distance_pc,
        "remaining_distance_km": state.remaining_distance_km,
        "progress": state.progress,
        "progress_percent": state.progress * 100,
        "current_speed_m_s": state.current_speed_m_s,
        "current_speed_km_s": state.current_speed_m_s / 1000,
        "cruise_speed_m_s": state.cruise_speed_m_s,
        "max_speed_m_s": state.max_speed_m_s,
        "galactic_position_pc": {"x": probe.x, "y": probe.y, "z": probe.z},
        "local_position_au": local_position,
        "display_position": {"x": probe.display_x, "y": probe.display_y, "z": probe.display_z},
        "origin_display_position": {"x": display_start[0], "y": display_start[1], "z": display_start[2]},
        "destination_display_position": {"x": display_target[0], "y": display_target[1], "z": display_target[2]},
        "display_velocity": {"x": display_velocity[0], "y": display_velocity[1], "z": display_velocity[2]},
    }
