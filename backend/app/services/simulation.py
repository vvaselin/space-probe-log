import math
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.llm.client import LLMClient
from app.llm.mock import MockLLMClient
from app.models import (
    CelestialBody,
    Discovery,
    ExplorationLog,
    MISSION_START_AT,
    Probe,
    ProbeNavigationState,
    ProbeStateHistory,
    ResourceInventory,
    Signal,
    SimulationAction,
    SimulationEvent,
    StarSystem,
)
from app.models.entities import SIM_SECONDS_PER_TICK
from app.repositories.read import active_universe, current_probe, signal_by_id, system_detail, systems
from app.repositories.settings import get_prompt_settings
from app.schemas.domain import (
    ActionContext,
    GeneratedLog,
    Interpretation,
    LogContext,
    ObservationFact,
    ProposedAction,
)
from app.services.action_validation import ValidationResult, validate_action
from app.services.reset import reset_world
from app.services.clock import advance_simulation_clock, ensure_simulation_clock
from app.services.navigation import (
    active_navigation_state,
    begin_navigation,
    latest_navigation_state,
    navigation_display_anchor,
    navigation_payload,
    synchronize_navigation,
)
from app.services.probe_spec import PROBE_ID, PROBE_LEGACY_IDS, PROBE_NAME, probe_specification
from app.services.route_hazards import display_route_hazards
from app.services.snapshots import probe_snapshot
from app.world.generator import (
    EnvironmentObjectSpec,
    SmallBodyLayerSpec,
    SystemSpec,
    frontier_shell_systems,
    generated_environment_objects,
    generated_small_body_layers,
)

LAUNCH_TARGET_ID = "outer-solar-marker"
LEGACY_FAR_OBJECTIVE_ROLE = "far_objective"
MAX_WAIT_STREAK = 1
CRUISE_LOG_COOLDOWN = 5
FUEL_LIMITS_ENABLED = False
STANDARD_SPEED_SETTING = "標準巡航"


def sim_elapsed_seconds_for_tick(mission_time: int) -> int:
    return max(0, mission_time) * SIM_SECONDS_PER_TICK


def sim_datetime_for_tick(mission_time: int) -> datetime:
    return MISSION_START_AT + timedelta(seconds=sim_elapsed_seconds_for_tick(mission_time))


def mission_time_payload(mission_time: int) -> dict:
    sim_dt = sim_datetime_for_tick(mission_time)
    return {
        "mission_clock": sim_dt.strftime("%Y/%m/%d %H:%M:%S UTC"),
        "sim_timestamp": sim_dt.isoformat().replace("+00:00", "Z"),
        "sim_elapsed_seconds": sim_elapsed_seconds_for_tick(mission_time),
    }


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(a, b, strict=True)))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _display_radius(point: tuple[float, float, float]) -> float:
    return math.sqrt(point[0] ** 2 + point[1] ** 2 + point[2] ** 2)


def _physical_radius(point: tuple[float, float, float]) -> float:
    return math.sqrt(point[0] ** 2 + point[1] ** 2 + point[2] ** 2)


def _physical_outward_score(probe: Probe, item: StarSystem) -> tuple[float, float, float]:
    probe_vector = (probe.x, probe.y, probe.z)
    item_vector = (item.x, item.y, item.z)
    probe_radius = max(_physical_radius(probe_vector), 1e-9)
    item_radius = _physical_radius(item_vector)
    dot = sum(left * right for left, right in zip(probe_vector, item_vector, strict=True)) / max(probe_radius * max(item_radius, 1e-9), 1e-9)
    forward_distance = sum((axis / probe_radius) * item_axis for axis, item_axis in zip(probe_vector, item_vector, strict=True))
    return item_radius, dot, forward_distance


def ensure_probe(db: Session) -> Probe:
    probe = current_probe(db)
    if probe is None:
        return reset_world(db)
    if probe.id in PROBE_LEGACY_IDS and db.get(Probe, PROBE_ID) is None:
        for model in [ProbeStateHistory, SimulationAction, SimulationEvent, Discovery, ResourceInventory, ProbeNavigationState]:
            db.execute(update(model).where(model.probe_id == probe.id).values(probe_id=PROBE_ID))
        probe.id = PROBE_ID
    if probe.name != PROBE_NAME:
        probe.name = PROBE_NAME
        db.commit()
        db.refresh(probe)
    return probe


def _world_seed(db: Session) -> str:
    universe = active_universe(db)
    return universe.world_seed if universe else "sol-neighborhood-001"


def _persist_system_spec(db: Session, universe_id: int, spec: SystemSpec) -> None:
    if db.get(StarSystem, spec.id) is not None:
        return
    db.add(
        StarSystem(
            id=spec.id,
            universe_id=universe_id,
            name=spec.name,
            kind=spec.kind,
            x=spec.position[0],
            y=spec.position[1],
            z=spec.position[2],
            display_x=spec.display[0],
            display_y=spec.display[1],
            display_z=spec.display[2],
            discovered=True,
            generated_seed=spec.generated_seed,
            has_life=spec.has_life,
            resources=spec.resources,
            details=spec.details,
        )
    )
    for body in spec.bodies:
        db.add(
            CelestialBody(
                id=body.id,
                system_id=spec.id,
                name=body.name,
                body_type=body.body_type,
                orbit_radius_km=body.orbit_radius_km,
                radius_km=body.radius_km,
                sim_x=body.sim[0],
                sim_y=body.sim[1],
                sim_z=body.sim[2],
                display_x=body.display[0],
                display_y=body.display[1],
                display_z=body.display[2],
                display_radius=body.display_radius,
                discovered=True,
                details=body.details,
            )
        )
    for signal in spec.signals:
        db.add(
            Signal(
                id=signal.id,
                system_id=spec.id,
                body_id=signal.body_id,
                kind=signal.kind,
                strength=signal.strength,
                x=signal.position[0],
                y=signal.position[1],
                z=signal.position[2],
                display_x=signal.display[0],
                display_y=signal.display[1],
                display_z=signal.display[2],
                discovered=True,
                investigated=False,
                details=signal.details,
            )
        )


def ensure_frontier_targets(db: Session, probe: Probe, min_unvisited: int = 4) -> None:
    universe = active_universe(db)
    if universe is None:
        return
    visited = _visited_system_ids(db, probe)
    probe_radius = _physical_radius((probe.x, probe.y, probe.z))
    known_systems = systems(db)
    available = [
        item
        for item in known_systems
        if item.id != probe.current_system_id
        and item.id not in visited
        and item.details.get("object_role") != LEGACY_FAR_OBJECTIVE_ROLE
        and _physical_outward_score(probe, item)[2] >= probe_radius + 0.5
        and _physical_outward_score(probe, item)[1] > 0.72
    ]
    if len(available) >= min_unvisited:
        return
    frontier_rings = [
        int(item.details.get("frontier_ring", 0))
        for item in known_systems
        if item.details.get("object_role") == "frontier_system"
    ]
    next_ring = max(frontier_rings, default=0) + 1
    base_radius = max(2.0, probe_radius + 0.5)
    outward_vector = (probe.x, probe.y, probe.z)
    shells_added = 0
    while len(available) < min_unvisited and shells_added < 8:
        for spec in frontier_shell_systems(_world_seed(db), next_ring, base_radius, outward_vector=outward_vector):
            _persist_system_spec(db, universe.id, spec)
        db.flush()
        known_systems = systems(db)
        available = [
            item
            for item in known_systems
            if item.id != probe.current_system_id
            and item.id not in visited
            and item.details.get("object_role") != LEGACY_FAR_OBJECTIVE_ROLE
            and _physical_outward_score(probe, item)[2] >= probe_radius + 0.5
            and _physical_outward_score(probe, item)[1] > 0.72
        ]
        next_ring += 1
        base_radius += 1.5
        shells_added += 1
    db.flush()


def _visited_system_ids(db: Session, probe: Probe) -> set[str]:
    return {
        item.snapshot.get("current_system_id")
        for item in db.scalars(select(ProbeStateHistory).where(ProbeStateHistory.probe_id == probe.id)).all()
        if item.snapshot.get("current_system_id")
    }


def _navigation_score(probe: Probe, item: StarSystem, visited: set[str]) -> tuple[int, int, int, float, str]:
    probe_radius = _physical_radius((probe.x, probe.y, probe.z))
    item_radius, outward_alignment, forward_distance = _physical_outward_score(probe, item)
    outward_penalty = 0 if forward_distance >= probe_radius + 0.5 and outward_alignment > 0.72 else 1
    visited_penalty = 1 if item.id in visited else 0
    order = int(item.details.get("navigation_order", 50))
    outward_distance = max(0.0, forward_distance - probe_radius)
    return (visited_penalty, outward_penalty, order, -outward_distance, item.id)


def action_context(db: Session, probe: Probe) -> ActionContext:
    ensure_frontier_targets(db, probe)
    current = system_detail(db, probe.current_system_id)
    prompt_settings = get_prompt_settings(db)
    nav_state = latest_navigation_state(db, probe)
    probe_context = probe_snapshot(probe)
    if nav_state:
        probe_context["navigation"] = navigation_payload(probe, nav_state)
    probe_context["specification"] = probe_specification().model_dump(mode="json")
    visible_signals = []
    if not probe.target_id and current:
        visible_signals = [
            {"id": signal.id, "kind": signal.kind, "strength": signal.strength, "details": signal.details}
            for signal in current.signals
            if not signal.investigated
        ]
    if current and current.details.get("object_role") == LEGACY_FAR_OBJECTIVE_ROLE:
        visible_signals = []
    visited = _visited_system_ids(db, probe)
    all_systems = [item for item in systems(db) if item.discovered]
    nearby = [
        {
            "id": item.id,
            "name": item.name,
            "display": [item.display_x, item.display_y, item.display_z],
            "has_life": item.has_life,
            "is_current": item.id == probe.current_system_id,
            "object_role": item.details.get("object_role", "system"),
            "navigation_order": item.details.get("navigation_order", 50),
            "distance_from_origin": _display_radius((item.display_x, item.display_y, item.display_z)),
        }
        for item in all_systems
    ]
    navigation_systems = [
        item
        for item in all_systems
        if item.id != probe.current_system_id and item.details.get("object_role") != LEGACY_FAR_OBJECTIVE_ROLE
    ]
    navigation_systems.sort(key=lambda item: _navigation_score(probe, item, visited))
    navigation_targets = [
        {
            "id": item.id,
            "name": item.name,
            "display": [item.display_x, item.display_y, item.display_z],
            "has_life": item.has_life,
            "visited": item.id in visited,
            "object_role": item.details.get("object_role", "system"),
            "navigation_order": item.details.get("navigation_order", 50),
            "distance_from_origin": _display_radius((item.display_x, item.display_y, item.display_z)),
            "outward_alignment": _physical_outward_score(probe, item)[1],
            "outward_projection_pc": _physical_outward_score(probe, item)[2],
        }
        for item in navigation_systems
    ]
    return ActionContext(
        probe=probe_context,
        nearby_systems=nearby,
        navigation_targets=navigation_targets,
        visible_signals=visible_signals,
        mission=probe.current_mission,
        prompt_settings={
            "probe_profile": prompt_settings.probe_profile,
            "action_policy": prompt_settings.action_policy,
            "log_writer_style": prompt_settings.log_writer_style,
        },
    )


async def safe_propose(llm: LLMClient, context: ActionContext) -> ProposedAction:
    try:
        return await llm.propose_action(context)
    except (ValidationError, ValueError, KeyError, TypeError):
        return ProposedAction(action="wait", reason="LLMの行動提案が不正だったため、安全待機します")
    except Exception:
        return await MockLLMClient().propose_action(context)


async def safe_generate_log(llm: LLMClient, context: LogContext) -> GeneratedLog:
    try:
        return await llm.generate_log(context)
    except Exception:
        return await MockLLMClient().generate_log(context)


def avoid_stagnation(context: ActionContext, proposed: ProposedAction) -> ProposedAction:
    probe = context.probe
    if probe.get("target_id"):
        return ProposedAction(action="move", target_id=str(probe["target_id"]), reason="既定の航行目標へ向けて航路を維持する")
    if context.visible_signals:
        return proposed
    if probe["mission_time"] < 2 or probe["propulsion"] < 25:
        return proposed
    if not context.navigation_targets:
        return proposed
    first_target = context.navigation_targets[0]
    if proposed.action == "move" and proposed.target_id == first_target["id"]:
        return proposed
    if proposed.action == "investigate_signal":
        return proposed
    if proposed.action not in {"observe", "wait", "collect_resource", "move"}:
        return proposed
    return ProposedAction(
        action="move",
        target_id=first_target["id"],
        reason=f"既知信号の調査を終え、太陽系外側へ向かうため {first_target['name']} への航行を開始する",
    )


def _first_navigation_target(context: ActionContext) -> dict | None:
    for target in context.navigation_targets:
        if not target.get("visited"):
            return target
    return context.navigation_targets[0] if context.navigation_targets else None


def _display_radius_from_mapping(target: dict) -> float:
    display = target.get("display", [0, 0, 0])
    return math.sqrt(sum(float(value) ** 2 for value in display))


def _event_times_at_current_system(db: Session, probe: Probe) -> set[int]:
    histories = db.scalars(
        select(ProbeStateHistory).where(ProbeStateHistory.probe_id == probe.id).order_by(ProbeStateHistory.mission_time)
    ).all()
    return {
        item.mission_time
        for item in histories
        if item.snapshot.get("current_system_id") == probe.current_system_id
    }


def _has_observed_current_system(db: Session, probe: Probe) -> bool:
    event_times = _event_times_at_current_system(db, probe)
    if not event_times:
        return False
    return (
        db.scalar(
            select(SimulationEvent.id)
            .where(
                SimulationEvent.probe_id == probe.id,
                SimulationEvent.event_type == "observe",
                SimulationEvent.mission_time.in_(event_times),
            )
            .limit(1)
        )
        is not None
    )


def _wait_streak(db: Session, probe: Probe) -> int:
    actions = db.scalars(
        select(SimulationAction)
        .where(SimulationAction.probe_id == probe.id)
        .order_by(SimulationAction.id.desc())
        .limit(4)
    ).all()
    streak = 0
    for action in actions:
        if action.validated_action != "wait":
            break
        streak += 1
    return streak


def _main_route_target(context: ActionContext) -> dict | None:
    probe_radius = _physical_radius((float(context.probe["x"]), float(context.probe["y"]), float(context.probe["z"])))
    candidates = [
        target
        for target in context.navigation_targets
        if not target.get("visited")
        and target.get("outward_projection_pc", 0) >= probe_radius + 0.5
        and target.get("outward_alignment", 0) > 0.72
    ]
    if not candidates:
        candidates = [target for target in context.navigation_targets if not target.get("visited")]
    frontier = [target for target in candidates if target.get("object_role") == "frontier_system"]
    if frontier:
        return sorted(frontier, key=lambda item: item.get("distance_from_origin", 0))[0]
    return candidates[0] if candidates else _first_navigation_target(context)


def main_route_target(db: Session, probe: Probe) -> StarSystem | None:
    selected = _main_route_target(action_context(db, probe))
    return system_detail(db, selected["id"]) if selected else None


def _navigation_intent(action: ProposedAction, target: dict | None = None) -> str:
    if action.action == "investigate_signal":
        return "detour_signal"
    if action.action == "observe":
        return "survey"
    if action.action == "collect_resource":
        return "resource"
    if action.action == "move":
        return "main_route"
    return "recovery"


def navigation_director(db: Session, probe: Probe, context: ActionContext, proposed: ProposedAction) -> tuple[ProposedAction, str]:
    scripted = scripted_initial_action(probe)
    if scripted:
        return scripted, "main_route"
    if probe.target_id:
        return ProposedAction(action="move", target_id=probe.target_id, reason="航行中の目標へ向けて主航路を維持します。"), "main_route"

    current = system_detail(db, probe.current_system_id)
    target = _main_route_target(context)
    if current and current.details.get("object_role") == LEGACY_FAR_OBJECTIVE_ROLE and target and probe.propulsion >= 25:
        return (
            ProposedAction(
                action="move",
                target_id=target["id"],
                reason=f"Continue outward from the outer terminus toward frontier target {target['name']}.",
            ),
            _navigation_intent(ProposedAction(action="move", target_id=target["id"], reason="frontier route"), target),
        )
    has_uninvestigated_signal = bool(context.visible_signals)
    if has_uninvestigated_signal and probe.energy >= 8 and probe.sensors >= 10 and probe.storage_used + 6 <= probe.storage_capacity:
        signal = context.visible_signals[0]
        return (
            ProposedAction(
                action="investigate_signal",
                target_id=signal["id"],
                reason="主航路からの寄り道として、現在地で未調査の信号を優先します。",
            ),
            "detour_signal",
        )

    if FUEL_LIMITS_ENABLED and probe.fuel < 18 and _can_collect_here(db, probe):
        return ProposedAction(action="collect_resource", reason="主航路へ復帰する前に推進剤として利用可能な資源を確保します。"), "resource"

    observed_current = _has_observed_current_system(db, probe)
    if current and current.bodies and not observed_current and proposed.action != "move":
        return ProposedAction(action="observe", target_id=probe.current_system_id, reason="寄り道先の主要天体を一度だけ基礎観測します。"), "survey"

    target = _main_route_target(context)
    if target and probe.propulsion >= 25:
        return (
            ProposedAction(
                action="move",
                target_id=target["id"],
                reason=f"寄り道調査を終えたため、主航路ビーコン {target['name']} へ復帰します。",
            ),
            _navigation_intent(ProposedAction(action="move", target_id=target["id"], reason="main route"), target),
        )

    if _wait_streak(db, probe) >= MAX_WAIT_STREAK and _can_collect_here(db, probe):
        return ProposedAction(action="collect_resource", reason="連続待機を避け、航行再開に必要な資源を確保します。"), "resource"
    if proposed.action == "wait" and _wait_streak(db, probe) >= MAX_WAIT_STREAK:
        target = _first_navigation_target(context)
        if target and probe.propulsion >= 25:
            return ProposedAction(action="move", target_id=target["id"], reason="連続待機を避け、外側の航行候補へ移動します。"), "main_route"

    return proposed, _navigation_intent(proposed)


def _can_collect_here(db: Session, probe: Probe) -> bool:
    if probe.target_id:
        return False
    current = system_detail(db, probe.current_system_id)
    return bool(current and current.resources and probe.energy >= 6 and probe.storage_used + 3 <= probe.storage_capacity)


def recovery_action(db: Session, probe: Probe, context: ActionContext, reason: str) -> ProposedAction:
    if probe.target_id and probe.propulsion >= 25:
        return ProposedAction(action="move", target_id=probe.target_id, reason="検証後の補正として、航行中の目標へ移動を継続します。")
    if not probe.target_id and context.visible_signals and probe.energy >= 8 and probe.sensors >= 10 and probe.storage_used + 6 <= probe.storage_capacity:
        return ProposedAction(
            action="investigate_signal",
            target_id=context.visible_signals[0]["id"],
            reason="検証後の補正として、現在地で未調査の信号を優先します。",
        )
    if FUEL_LIMITS_ENABLED and probe.fuel < 18 and _can_collect_here(db, probe):
        return ProposedAction(action="collect_resource", reason="燃料余力が低いため、現在地の資源を推進剤として確保します。")
    target = _first_navigation_target(context)
    if target and probe.propulsion >= 25:
        return ProposedAction(action="move", target_id=target["id"], reason=f"{reason} 外側の航行候補 {target['name']} へ進みます。")
    if _can_collect_here(db, probe):
        return ProposedAction(action="collect_resource", reason="航行再開に備え、現在地で利用可能な資源を確保します。")
    return ProposedAction(action="wait", reason="利用可能な代替行動がないため、エネルギー回復と姿勢維持を行います。")


def validate_with_recovery(db: Session, probe: Probe, context: ActionContext, proposed: ProposedAction) -> ValidationResult:
    validation = validate_action(db, probe, proposed)
    if not validation.fallback_used:
        return validation
    recovered = recovery_action(db, probe, context, validation.message)
    recovered_validation = validate_action(db, probe, recovered)
    if not recovered_validation.fallback_used:
        recovered_validation.status = "recovered"
        recovered_validation.message = f"{validation.message} / 代替行動を採用しました。"
        return recovered_validation
    return validation


def scripted_initial_action(probe: Probe) -> ProposedAction | None:
    if probe.target_id:
        return ProposedAction(action="move", target_id=probe.target_id, reason="航行中のため既定目標へ向けて進む")
    if probe.mission_time == 0 and probe.current_system_id == "sol":
        return ProposedAction(action="move", target_id=LAUNCH_TARGET_ID, reason="発射シークエンスを開始し、太陽系外縁へ向けて出発する。")
    return None


def log_header(snapshot: dict, event: SimulationEvent) -> str:
    log_number = int(snapshot["mission_time"])
    timestamp = utcnow().strftime("%Y/%m/%d %H:%M:%S UTC")
    position = f"x={snapshot['x']:.2f}, y={snapshot['y']:.2f}, z={snapshot['z']:.2f}"
    return (
        "---------------------\n"
        "INSOMNIA-07 航行ログ\n"
        "搭載AI: OVIS\n"
        f"LOG #{log_number:03d}\n"
        f"{timestamp} - {event.event_type}\n"
        f"位置: {snapshot['current_system_id']} / {position}\n"
        f"状況: {event.summary}\n"
        "---------------------"
    )


def _sensor_reliability(probe: Probe) -> float:
    return max(0.25, min(0.98, probe.sensors / 100))


def scripted_initial_action(probe: Probe) -> ProposedAction | None:
    if probe.target_id:
        return ProposedAction(action="move", target_id=probe.target_id, reason="航行中のため既定目標へ向けて進む")
    if probe.mission_time == 0 and probe.current_system_id == "sol":
        return ProposedAction(action="move", target_id=LAUNCH_TARGET_ID, reason="発射シークエンスを開始し、太陽系外縁へ向けて出発する。")
    return None


def log_header(snapshot: dict, event: SimulationEvent) -> str:
    log_number = int(snapshot["mission_time"])
    timestamp = utcnow().strftime("%Y/%m/%d %H:%M:%S UTC")
    position = f"x={snapshot['x']:.2f}, y={snapshot['y']:.2f}, z={snapshot['z']:.2f}"
    return (
        "---------------------\n"
        "INSOMNIA-07 航行ログ\n"
        "搭載AI: OVIS\n"
        f"LOG #{log_number:03d}\n"
        f"{timestamp} - {event.event_type}\n"
        f"位置: {snapshot['current_system_id']} / {position}\n"
        f"状況: {event.summary}\n"
        "---------------------"
    )


def scripted_initial_action(probe: Probe) -> ProposedAction | None:
    if probe.target_id:
        return ProposedAction(action="move", target_id=probe.target_id, reason="航行中の目標へ向けて巡航を継続する。")
    if probe.mission_time == 0 and probe.current_system_id == "sol":
        return ProposedAction(action="move", target_id=LAUNCH_TARGET_ID, reason="発射シークエンスを完了し、太陽系外縁への航路へ入る。")
    return None


def log_header(snapshot: dict, event: SimulationEvent) -> str:
    log_number = int(snapshot.get("log_number", snapshot["mission_time"]))
    timestamp = snapshot.get("mission_clock") or event.data.get("mission_clock") or "2080/05/02 12:00:00 UTC"
    position = f"x={snapshot['x']:.2f}, y={snapshot['y']:.2f}, z={snapshot['z']:.2f}"
    return (
        "# INSOMNIA 航行ログ\n"
        "**探査機: INSOMNIA-07**\n"
        "**搭載AI: OVIS**\n\n"
        f"## LOG #{log_number:03d}\n"
        f"**{timestamp} - {event.event_type}**\n"
        f"**位置: {snapshot['current_system_id']} / {position}**\n"
        f"**状況: {event.summary}**"
    )


def _vector_from_probe(probe: Probe) -> tuple[float, float, float]:
    return probe.display_x, probe.display_y, probe.display_z


def _vector_from_system(system: StarSystem) -> tuple[float, float, float]:
    return system.display_x, system.display_y, system.display_z


def _point_to_segment_distance(
    point: tuple[float, float, float],
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> float:
    segment = tuple(right - left for left, right in zip(start, end, strict=True))
    length_squared = sum(axis * axis for axis in segment)
    if length_squared <= 1e-9:
        return _distance(point, start)
    offset = tuple(value - origin for value, origin in zip(point, start, strict=True))
    fraction = max(0.0, min(1.0, sum(left * right for left, right in zip(offset, segment, strict=True)) / length_squared))
    closest = tuple(origin + axis * fraction for origin, axis in zip(start, segment, strict=True))
    return _distance(point, closest)


def _route_environment_objects(db: Session, probe: Probe, target: StarSystem) -> list[EnvironmentObjectSpec]:
    start = _vector_from_probe(probe)
    end = _vector_from_system(target)
    candidates: list[tuple[float, EnvironmentObjectSpec]] = []
    for item in generated_environment_objects(_world_seed(db), systems(db)):
        route_distance = _point_to_segment_distance(item.display, start, end)
        extent = max(item.scale)
        if route_distance <= extent * 1.5:
            candidates.append((route_distance / max(extent, 1.0), item))
    return [item for _, item in sorted(candidates, key=lambda entry: (entry[0], entry[1].id))]


def _route_small_body_layers(db: Session, probe: Probe, target: StarSystem) -> list[SmallBodyLayerSpec]:
    start = _vector_from_probe(probe)
    end = navigation_display_anchor(db, target)
    layers = generated_small_body_layers(_world_seed(db))
    hazard_ids = {item.id for item in display_route_hazards(start, end, layers)}
    return [item for item in layers if item.id in hazard_ids]


def _route_small_body_hazards(db: Session, probe: Probe, target: StarSystem) -> list[dict]:
    hazards = display_route_hazards(
        _vector_from_probe(probe),
        navigation_display_anchor(db, target),
        generated_small_body_layers(_world_seed(db)),
    )
    return [item.model_dump(mode="json") for item in hazards]


def _nearby_route_bodies(db: Session, probe: Probe, target: StarSystem, route_phase: str | None) -> list[CelestialBody]:
    phase = route_phase or "interstellar_cruise"
    system_ids: list[str]
    if phase in {"course_plotted", "system_departure", "accelerating"}:
        system_ids = [probe.current_system_id]
    elif phase in {"decelerating", "system_arrival", "arrived"}:
        system_ids = [target.id]
    else:
        system_ids = [probe.current_system_id, target.id]

    probe_point = _vector_from_probe(probe)
    bodies: list[CelestialBody] = []
    seen: set[str] = set()
    for system_id in system_ids:
        detail = system_detail(db, system_id)
        if detail is None:
            continue
        for body in detail.bodies:
            if body.id in seen or not body.discovered:
                continue
            if phase == "interstellar_cruise" and _distance(probe_point, (body.display_x, body.display_y, body.display_z)) > 30:
                continue
            seen.add(body.id)
            bodies.append(body)
    return sorted(
        bodies,
        key=lambda body: (_distance(probe_point, (body.display_x, body.display_y, body.display_z)), -body.radius_km, body.id),
    )


def _recent_scene_usage(db: Session, limit: int = 3) -> tuple[dict[str, int], dict[str, int]]:
    recent_logs = db.scalars(select(ExplorationLog).order_by(ExplorationLog.id.desc()).limit(limit)).all()
    source_age: dict[str, int] = {}
    category_age: dict[str, int] = {}
    for age, log in enumerate(recent_logs):
        for body_id in log.related_body_ids or []:
            source_age.setdefault(body_id, age)
        if not log.related_event_ids:
            continue
        events = db.scalars(select(SimulationEvent).where(SimulationEvent.id.in_(log.related_event_ids))).all()
        for event in events:
            for item in event.data.get("observations", []):
                source = item.get("source")
                category = item.get("scene_category")
                if source:
                    source_age.setdefault(str(source), age)
                if category:
                    category_age.setdefault(str(category), age)
    return source_age, category_age


def _environment_scene_category(item: EnvironmentObjectSpec) -> str:
    nebula_type = str(item.details.get("nebula_type") or "")
    if item.object_type == "dust_cloud" or nebula_type == "dark":
        return "environment:dark_dust"
    if item.object_type == "nebula":
        return f"environment:nebula:{nebula_type or 'unknown'}"
    return f"environment:{item.object_type}"


def _body_scene_category(body_type: str) -> str:
    return f"body:{body_type}"


def _passive_environment_observation(item: EnvironmentObjectSpec, reliability: float) -> ObservationFact:
    nebula_type = str(item.details.get("nebula_type") or "")
    if item.object_type == "dust_cloud" or nebula_type == "dark":
        value = f"{item.name}の方向で恒星光の遮蔽と弱い赤化を受動検出した"
    elif nebula_type == "reflection":
        value = f"{item.name}から広がる淡い散乱光を受動検出した"
    elif item.object_type == "nebula":
        value = f"{item.name}の方向に拡散光と弱い分光上の兆候を捉えた"
    elif item.object_type == "anomaly_region":
        value = f"{item.name}の方向で背景光の不規則な変化を受動検出した"
    else:
        value = f"{item.name}の方向で弱い散乱光の変化を受動検出した"
    return ObservationFact(
        type="passive_sighting",
        value=value,
        reliability=max(0.2, reliability * 0.78),
        sighting_level="detected",
        source=item.id,
        distance_hint="航路周辺",
        object_type=item.object_type,
        scene_category=_environment_scene_category(item),
    )


def _passive_small_body_observation(layer: SmallBodyLayerSpec, reliability: float) -> ObservationFact:
    if layer.layer_type == "asteroid_belt":
        value = f"{layer.name}の方向で断続的な反射光と微小な遮蔽を受動検出した"
    elif layer.layer_type == "comet_population":
        value = f"{layer.name}に一時的な散乱光とコマ状の分光上の兆候を捉えた"
    else:
        value = f"{layer.name}の球殻方向に希薄な散乱光と遠赤外線側の弱い兆候を受動検出した"
    return ObservationFact(
        type="passive_sighting",
        value=value,
        reliability=max(0.2, reliability * 0.74),
        sighting_level="detected",
        source=layer.id,
        distance_hint="太陽系小天体領域",
        object_type=layer.layer_type,
        scene_category=f"small_body:{layer.layer_type}",
    )


def _passive_body_observation(body: CelestialBody, reliability: float) -> ObservationFact:
    body_type = body.body_type
    if body_type == "star":
        value = f"{body.name}の光に航行に伴う視差変化を記録した"
    elif body_type in {"rocky_planet", "terrestrial_planet", "gas_giant", "ice_planet", "ice_world", "ocean_world", "dwarf_planet"}:
        value = f"{body.name}からの弱い反射光と未分離の分光上の兆候を捉えた"
    elif body_type in {"moon", "satellite"}:
        value = f"{body.name}の反射光に小さな視差変化を受動検出した"
    elif body_type == "comet":
        value = f"{body.name}の方向に断続的な散乱光と弱い分光上の兆候を捉えた"
    elif body_type in {"asteroid", "asteroid_belt", "debris_belt", "debris_field"}:
        value = f"{body.name}の方向で断続的な反射光と微小な遮蔽を受動検出した"
    elif body_type in {"ring", "ring_system", "planetary_ring"}:
        value = f"{body.name}の方向に薄い散乱光と帯状の遮蔽を受動検出した"
    else:
        value = f"{body.name}の方向で弱い光学変化と分光上の兆候を受動検出した"
    return ObservationFact(
        type="passive_sighting",
        value=value,
        reliability=max(0.2, reliability * 0.82),
        sighting_level="resolved",
        source=body.id,
        distance_hint="近傍天体",
        body_type=body_type,
        scene_category=_body_scene_category(body_type),
    )


def _confirmed_body_observation(body: CelestialBody, reliability: float) -> ObservationFact:
    body_type = body.body_type
    if body_type == "star":
        value = f"{body.name}の恒星光を分光観測し、光度分布を確認した"
    elif body_type in {"rocky_planet", "terrestrial_planet", "dwarf_planet"}:
        value = f"{body.name}の反射スペクトルと表面の明暗分布を確認した"
    elif body_type == "gas_giant":
        value = f"{body.name}の大気帯による色調差と反射スペクトルを確認した"
    elif body_type in {"ice_planet", "ice_world"}:
        value = f"{body.name}の高反射領域と低温側の赤外線分布を確認した"
    elif body_type == "ocean_world":
        value = f"{body.name}の反射光分布と大気による分光変化を確認した"
    elif body_type in {"moon", "satellite"}:
        value = f"{body.name}の位相と表面反射率の差を確認した"
    elif body_type == "comet":
        value = f"{body.name}のコマ状散乱光と分光成分を確認した"
    elif body_type in {"asteroid", "asteroid_belt"}:
        value = f"{body.name}の断続的な反射光と遮蔽頻度を確認した"
    elif body_type in {"ring", "ring_system", "planetary_ring"}:
        value = f"{body.name}の帯状構造による散乱光と遮蔽を確認した"
    elif body_type in {"debris_belt", "debris_field"}:
        value = f"{body.name}の不規則な反射光と微小遮蔽の分布を確認した"
    else:
        value = f"{body.name} ({body_type}) の角直径と反射光分布を確認した"

    details: list[str] = []
    spectral_type = body.details.get("spectral_type")
    temperature = body.details.get("surface_temperature_k")
    atmosphere = body.details.get("atmosphere")
    if spectral_type:
        details.append(f"スペクトル型 {spectral_type}")
    if isinstance(temperature, int | float):
        details.append(f"表面温度 {temperature:g} K")
    if atmosphere:
        details.append(f"大気情報 {atmosphere}")
    if details:
        value = f"{value}（{'、'.join(details)}）"
    return ObservationFact(
        type="celestial_body",
        value=value,
        reliability=reliability,
        sighting_level="confirmed",
        source=body.id,
        body_type=body_type,
        scene_category=_body_scene_category(body_type),
    )


def _nearest_side_system(db: Session, probe: Probe, target: StarSystem) -> StarSystem | None:
    probe_point = _vector_from_probe(probe)
    candidates = [
        item
        for item in systems(db)
        if item.discovered
        and item.kind != "waypoint"
        and item.id not in {probe.current_system_id, target.id}
        and _distance(probe_point, _vector_from_system(item)) <= 220
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (_distance(probe_point, _vector_from_system(item)), item.id))[0]


def _passive_signal_hint(db: Session, probe: Probe, target: StarSystem) -> Signal | None:
    probe_point = _vector_from_probe(probe)
    candidates: list[Signal] = []
    for system in systems(db):
        if system.id in {probe.current_system_id, target.id} or _distance(probe_point, _vector_from_system(system)) <= 120:
            detail = system_detail(db, system.id)
            if detail:
                candidates.extend(signal for signal in detail.signals if not signal.investigated)
    if not candidates:
        return None
    return sorted(candidates, key=lambda signal: (-signal.strength, signal.id))[0]


def _recent_log_exists(db: Session, probe: Probe, within: int = CRUISE_LOG_COOLDOWN) -> bool:
    latest = db.scalar(
        select(ExplorationLog)
        .where(ExplorationLog.mission_time >= max(0, probe.mission_time - within))
        .order_by(ExplorationLog.mission_time.desc())
        .limit(1)
    )
    return latest is not None


def _phase_logged(db: Session, phase: str) -> bool:
    events = db.scalars(select(SimulationEvent).order_by(SimulationEvent.id.desc()).limit(200)).all()
    return any(event.data.get("log_phase") == phase for event in events)


def _log_exists_for_event(db: Session, event_id: int) -> bool:
    logs = db.scalars(select(ExplorationLog).order_by(ExplorationLog.id.desc()).limit(200)).all()
    return any(event_id in (log.related_event_ids or []) for log in logs)


def _pending_navigation_arrival_event(db: Session, probe: Probe) -> SimulationEvent | None:
    event = db.scalar(
        select(SimulationEvent)
        .where(SimulationEvent.probe_id == probe.id, SimulationEvent.event_type == "navigation_arrived")
        .order_by(SimulationEvent.id.desc())
        .limit(1)
    )
    if event is None or event.data.get("log_phase") == "arrival" or _phase_logged(db, "arrival") or _log_exists_for_event(db, event.id):
        return None
    return event


def _log_decision(
    db: Session,
    probe: Probe,
    action: SimulationAction,
    event: SimulationEvent,
    observations: list[ObservationFact],
    force_log: bool = False,
) -> tuple[bool, str | None]:
    if force_log:
        return True, "manual_step"
    if event.event_type in {"investigate_signal", "collect_resource", "observe"}:
        return True, event.event_type
    if action.validated_action != "move":
        return False, None
    if event.mission_time == 1:
        return True, "launch"
    if event.data.get("route_phase") == "arrived" or event.data.get("navigation_phase") == "arrived":
        return True, "arrival"
    if any(obs.type == "navigation" and "到着" in obs.value for obs in observations):
        return True, "arrival"
    if probe.hull < 35 or probe.communication < 35 or probe.energy < 10:
        return True, "serious_degradation"
    if _recent_log_exists(db, probe):
        return False, None
    return False, None


async def _persist_log(
    db: Session,
    llm: LLMClient,
    context: ActionContext,
    action: SimulationAction,
    event: SimulationEvent,
    observations: list[ObservationFact],
    interpretations: list[Interpretation],
) -> ExplorationLog:
    snapshot = probe_snapshot(current_probe(db))
    generated = await safe_generate_log(
        llm,
        LogContext(
            action={"id": action.id, "action": action.validated_action, "reason": action.reason, "navigation_intent": action.raw_payload.get("navigation_intent")},
            event={"id": event.id, "event_type": event.event_type, "summary": event.summary},
            probe_snapshot=snapshot,
            observations=observations,
            interpretations=interpretations,
            prompt_settings=context.prompt_settings,
        ),
    )
    body_markdown = generated.body_markdown
    if not body_markdown.lstrip().startswith("# INSOMNIA 航行ログ"):
        body_markdown = f"{log_header(snapshot, event)}\n\n{body_markdown}"
    body_markdown = re.sub(r"LOG #\d+", f"LOG #{snapshot['log_number']:03d}", body_markdown, count=1)
    log = ExplorationLog(
        title=generated.title,
        summary=generated.summary,
        body_markdown=body_markdown,
        mission_time=snapshot["mission_time"],
        probe_position={"x": snapshot["x"], "y": snapshot["y"], "z": snapshot["z"], "system_id": snapshot["current_system_id"], "target_id": snapshot["target_id"]},
        related_event_ids=[event.id],
        related_body_ids=[event.related_body_id] if event.related_body_id else [],
        probe_state_snapshot=snapshot,
        communication_status="nominal" if snapshot["communication"] > 40 else "degraded",
        reliability=generated.reliability,
    )
    db.add(log)
    db.flush()
    return log


def _navigation_route_state(probe: Probe, nav_state: ProbeNavigationState | None, sampled_at: datetime | None = None) -> dict | None:
    if nav_state is None:
        return None
    nav_payload = navigation_payload(probe, nav_state, sampled_at)
    if not nav_payload.get("destination_system_id"):
        return None
    remaining_display_distance = 0.0
    destination = nav_payload.get("destination_display_position")
    if isinstance(destination, dict):
        remaining_display_distance = _distance(
            (probe.display_x, probe.display_y, probe.display_z),
            (float(destination["x"]), float(destination["y"]), float(destination["z"])),
        )
    route_phase = (
        "course_plotted"
        if probe.mission_time == 0 and nav_payload["phase"] == "system_departure" and nav_payload["progress"] <= 0.0
        else nav_payload["phase"]
    )
    return {
        "target_id": nav_payload["destination_system_id"],
        "target_name": nav_payload.get("destination_name") or nav_state.destination_name,
        "phase": route_phase,
        "velocity": nav_payload["current_speed_m_s"],
        "current_speed_m_s": nav_payload["current_speed_m_s"],
        "speed_setting": STANDARD_SPEED_SETTING,
        "drive_mode": nav_payload["drive_mode"],
        "progress": nav_payload["progress"],
        "remaining_distance": remaining_display_distance,
        "remaining_distance_km": nav_payload["remaining_distance_km"],
        "remaining_distance_pc": nav_payload["remaining_distance_pc"],
        "eta_datetime": nav_payload.get("eta_datetime"),
    }

def scripted_initial_action(probe: Probe) -> ProposedAction | None:
    if probe.target_id:
        return ProposedAction(action="move", target_id=probe.target_id, reason="設定済みの航路を継続する。")
    if probe.mission_time == 0 and probe.current_system_id == "sol":
        return ProposedAction(action="move", target_id=LAUNCH_TARGET_ID, reason="発射シークエンスを完了し、太陽系外縁への航路を設定する。")
    return None


def log_header(snapshot: dict, event: SimulationEvent) -> str:
    log_number = int(snapshot.get("log_number", snapshot["mission_time"]))
    timestamp = snapshot.get("mission_clock") or "2080/05/02 12:00:00 UTC"
    position = f"x={snapshot['x']:.2f}, y={snapshot['y']:.2f}, z={snapshot['z']:.2f}"
    return (
        "# INSOMNIA 航行ログ\n"
        "**探査機: INSOMNIA-07**\n"
        "**搭載AI: OVIS**\n\n"
        f"## LOG #{log_number:03d}\n"
        f"**{timestamp} - {event.event_type}**\n"
        f"**位置: {snapshot['current_system_id']} / {position}**\n"
        f"**状況: {event.summary}**"
    )


def passive_observations_during_move(
    db: Session,
    probe: Probe,
    target: StarSystem,
    remaining_before_step: float,
    reliability: float,
    route_phase: str | None = None,
) -> tuple[list[ObservationFact], list[Interpretation]]:
    candidates: list[ObservationFact] = []
    interpretations = [
        Interpretation(
            hypothesis="受動観測は航路維持に利用できるが、単独では発見確定には不足している",
            confidence=min(0.82, reliability * 0.72),
        )
    ]

    candidates.extend(_passive_environment_observation(item, reliability) for item in _route_environment_objects(db, probe, target))
    candidates.extend(_passive_small_body_observation(item, reliability) for item in _route_small_body_layers(db, probe, target))
    candidates.extend(_passive_body_observation(body, reliability) for body in _nearby_route_bodies(db, probe, target, route_phase))

    signal = _passive_signal_hint(db, probe, target)
    if signal:
        candidates.append(
            ObservationFact(
                type="passive_signal",
                value=f"{signal.kind}の微弱な反射を受動検出した",
                reliability=max(0.2, min(0.95, reliability * signal.strength)),
                sighting_level="detected",
                source=signal.id,
                distance_hint="航路周辺",
                scene_category=f"signal:{signal.kind}",
            )
        )
        interpretations.append(
            Interpretation(
                hypothesis="受動検出された信号は、到着後に寄り道調査の候補になり得る",
                confidence=max(0.2, min(0.75, reliability * signal.strength * 0.72)),
            )
        )

    side_system = _nearest_side_system(db, probe, target)
    if side_system:
        candidates.append(
            ObservationFact(
                type="passive_sighting",
                value=f"側方星野で{side_system.name}の恒星光に視差変化を記録した",
                reliability=max(0.2, reliability * 0.8),
                sighting_level="resolved",
                source=side_system.id,
                distance_hint="側方視野",
                scene_category="system:parallax",
            )
        )

    source_age, category_age = _recent_scene_usage(db)

    def repetition_key(observation: ObservationFact) -> tuple[int, int, str]:
        source_recency = source_age.get(observation.source or "", -1)
        category_recency = category_age.get(observation.scene_category or "", -1)
        use_ages = [age for age in (source_recency, category_recency) if age >= 0]
        most_recent_use = min(use_ages, default=-1)
        return (1 if use_ages else 0, -most_recent_use, observation.source or "")

    selected: list[ObservationFact] = []
    selected_categories: set[str] = set()
    for observation in sorted(candidates, key=repetition_key):
        category = observation.scene_category or observation.type
        if category in selected_categories:
            continue
        selected.append(observation)
        selected_categories.add(category)
        if len(selected) == 3:
            break

    if not selected:
        target_kind = "航路標の微光" if target.kind == "waypoint" else "恒星光"
        selected.append(
            ObservationFact(
                type="passive_sighting",
                value=f"航路前方に{target.name}の{target_kind}を捉えた",
                reliability=reliability,
                sighting_level="detected" if target.kind == "waypoint" else "resolved",
                source=target.id,
                distance_hint=f"残距離推定 {remaining_before_step:.1f}",
                scene_category="system:route_target",
            )
        )
    return selected, interpretations


def apply_action(db: Session, probe: Probe, action: ProposedAction) -> tuple[SimulationEvent, list[ObservationFact], list[Interpretation]]:
    observations: list[ObservationFact] = []
    interpretations: list[Interpretation] = []
    related_body_id: str | None = None
    related_signal_id: str | None = None
    summary = "探査機は待機し、姿勢制御と通信同期を維持しました。"
    event_type = action.action
    route_state: dict | None = None
    nav_state = active_navigation_state(db, probe)
    clock, _ = advance_simulation_clock(db) if probe.mission_time > 0 else (ensure_simulation_clock(db), 0.0)
    simulation_datetime = clock.simulation_datetime
    if simulation_datetime.tzinfo is None:
        simulation_datetime = simulation_datetime.replace(tzinfo=UTC)
    reliability = _sensor_reliability(probe)

    if nav_state is not None:
        nav_target = system_detail(db, nav_state.destination_system_id)
        synchronize_navigation(db, probe, nav_state, nav_target, simulation_datetime)

    if action.action == "move" and action.target_id:
        target = system_detail(db, action.target_id)
        assert target is not None
        nav_state = active_navigation_state(db, probe)
        if nav_state is None or nav_state.destination_system_id != target.id:
            nav_state = begin_navigation(db, probe, target, simulation_datetime)
        synchronize_navigation(db, probe, nav_state, target, simulation_datetime)
        route_state = _navigation_route_state(probe, nav_state, simulation_datetime)
        if nav_state.phase == "arrived":
            summary = f"{target.name}へ到着し、航行目標を解除しました。"
            observations.append(ObservationFact(type="navigation", value=f"{target.name}へ到着", reliability=reliability))
            ensure_frontier_targets(db, probe, min_unvisited=6)
        elif nav_state.progress <= 0.0 and nav_state.phase == "system_departure":
            if probe.mission_time == 0 and target.id == LAUNCH_TARGET_ID:
                summary = f"発射シークエンスを完了し、{target.name}への航行を設定しました。位置更新はシミュレーション時刻から計算します。"
            else:
                summary = f"{target.name}への航行を設定しました。位置更新はシミュレーション時刻から計算します。"
            observations.append(ObservationFact(type="navigation", value=f"{target.name}への航行を設定", reliability=reliability))
        else:
            phase_label = {
                "system_departure": "恒星系離脱",
                "accelerating": "加速",
                "interstellar_cruise": "巡航",
                "decelerating": "減速",
                "system_arrival": "到着処理",
            }.get(nav_state.phase, "航行")
            summary = f"{target.name}へ向けて{phase_label}中。"
            observations.append(ObservationFact(type="navigation", value=f"{target.name}へ向けた航行を継続", reliability=reliability))
        if route_state:
            passive_observations, passive_interpretations = passive_observations_during_move(
                db,
                probe,
                target,
                float(route_state.get("remaining_distance", 0.0)),
                reliability,
                str(route_state.get("phase") or nav_state.phase),
            )
            observations.extend(passive_observations)
            interpretations.extend(passive_interpretations)
            interpretations.append(Interpretation(hypothesis="航行位置はProbeNavigationStateの時刻ベース計算に同期している", confidence=min(0.86, reliability * 0.78)))
        probe.energy = max(0, probe.energy - 0.05 if nav_state.current_speed_m_s > 0 else probe.energy)

    elif action.action == "observe":
        current = system_detail(db, probe.current_system_id)
        if current and current.bodies:
            for body in current.bodies[:3]:
                related_body_id = related_body_id or body.id
                observations.append(_confirmed_body_observation(body, reliability))
            interpretations.append(Interpretation(hypothesis=f"{current.name}は継続調査に値する安定した観測対象である", confidence=reliability * 0.7))
        probe.energy = max(0, probe.energy - 4)
        probe.storage_used = min(probe.storage_capacity, probe.storage_used + 4)
        summary = "周辺天体の分光観測と測距観測を実行しました。"

    elif action.action == "investigate_signal" and action.target_id:
        signal = signal_by_id(db, action.target_id)
        assert signal is not None
        reliability = min(0.99, _sensor_reliability(probe) * signal.strength)
        frequency = signal.details.get("frequency") or signal.details.get("fictional_data", {}).get("frequency") or "未知周波数"
        observations.append(ObservationFact(type=signal.kind, value=f"{frequency}付近の信号を確認", reliability=reliability))
        interpretations.append(Interpretation(hypothesis="人工的なビーコンである可能性", confidence=min(0.85, reliability * 0.72)))
        signal.investigated = True
        related_signal_id = signal.id
        related_body_id = signal.body_id
        probe.energy = max(0, probe.energy - 8)
        probe.storage_used = min(probe.storage_capacity, probe.storage_used + 6)
        summary = f"{signal.id}の周期性と強度変化を記録しました。"

    elif action.action == "collect_resource":
        current = db.get(StarSystem, probe.current_system_id)
        resource_name = max(current.resources, key=lambda key: current.resources[key]) if current and current.resources else "water_ice"
        quantity = 1.5
        probe.collected_resources = {**probe.collected_resources, resource_name: probe.collected_resources.get(resource_name, 0) + quantity}
        inventory = db.scalar(select(ResourceInventory).where(ResourceInventory.probe_id == probe.id, ResourceInventory.resource_name == resource_name))
        if inventory is None:
            inventory = ResourceInventory(probe_id=probe.id, resource_name=resource_name, quantity=0)
            db.add(inventory)
        inventory.quantity += quantity
        probe.energy = max(0, probe.energy - 6)
        probe.storage_used = min(probe.storage_capacity, probe.storage_used + 3)
        observations.append(ObservationFact(type="resource", value=f"{resource_name}を{quantity:.1f}単位採取", reliability=0.9))
        interpretations.append(Interpretation(hypothesis="推進剤または修復材料として利用できる可能性", confidence=0.65))
        summary = f"{resource_name}を{quantity:.1f}単位採取し、航行継続用の材料へ回しました。"

    else:
        probe.energy = min(100, probe.energy + 2)
        probe.velocity = 0 if not probe.target_id else probe.velocity

    probe.mission_time += 1
    probe.last_updated_at = utcnow()
    sim_timestamp = simulation_datetime.isoformat().replace("+00:00", "Z")
    event_payload = {
        "observations": [item.model_dump() for item in observations],
        "interpretations": [item.model_dump() for item in interpretations],
        "mission_clock": simulation_datetime.strftime("%Y/%m/%d %H:%M:%S UTC"),
        "sim_timestamp": sim_timestamp,
        "sim_elapsed_seconds": max(0, int((simulation_datetime - MISSION_START_AT).total_seconds())),
        "simulation_datetime": sim_timestamp,
    }
    if nav_state:
        nav_payload = navigation_payload(probe, nav_state, simulation_datetime)
        route_state = route_state or _navigation_route_state(probe, nav_state, simulation_datetime)
        event_payload.update(
            {
                "navigation_state": nav_payload,
                "navigation_phase": nav_payload["phase"],
                "drive_mode": nav_payload["drive_mode"],
                "current_speed_m_s": nav_payload["current_speed_m_s"],
                "destination_id": nav_payload["destination_system_id"],
                "destination_name": nav_payload["destination_name"],
                "remaining_distance_km": nav_payload["remaining_distance_km"],
                "remaining_distance_pc": nav_payload["remaining_distance_pc"],
                "eta_datetime": nav_payload.get("eta_datetime"),
                "mission_elapsed_seconds": max(0, (simulation_datetime - MISSION_START_AT).total_seconds()),
            }
        )
    if route_state:
        event_payload.update(
            {
                "route_state": route_state,
                "route_phase": route_state["phase"],
                "speed_setting": route_state["speed_setting"],
                "remaining_distance": route_state["remaining_distance"],
                "next_target_name": route_state["target_name"],
            }
        )
    event = SimulationEvent(
        probe_id=probe.id,
        event_type=event_type,
        mission_time=probe.mission_time,
        summary=summary,
        related_body_id=related_body_id,
        related_signal_id=related_signal_id,
        data=event_payload,
    )
    db.add(event)
    db.flush()
    for obs in observations:
        if obs.sighting_level != "confirmed":
            continue
        observation_body_id = obs.source if obs.source and db.get(CelestialBody, obs.source) is not None else None
        db.add(
            Discovery(
                probe_id=probe.id,
                event_id=event.id,
                target_id=observation_body_id or related_signal_id or related_body_id or probe.target_id,
                observation_type=obs.type,
                value=obs.value,
                reliability=obs.reliability,
                interpretations=[item.model_dump() for item in interpretations],
            )
        )
    return event, observations, interpretations

def _route_state(db: Session, probe: Probe) -> dict | None:
    nav_state = latest_navigation_state(db, probe)
    if nav_state is None:
        return None
    return _navigation_route_state(probe, nav_state)

def _deterministic_cruise_action(db: Session, probe: Probe, context: ActionContext) -> tuple[ProposedAction, str]:
    scripted = scripted_initial_action(probe)
    if scripted:
        return scripted, "main_route"
    if context.visible_signals and probe.energy >= 8 and probe.sensors >= 10 and probe.storage_used + 6 <= probe.storage_capacity:
        signal = context.visible_signals[0]
        return ProposedAction(action="investigate_signal", target_id=signal["id"], reason="現在地で未調査の信号を確認する。"), "detour_signal"
    if FUEL_LIMITS_ENABLED and probe.fuel < 18 and _can_collect_here(db, probe):
        return ProposedAction(action="collect_resource", reason="巡航継続に必要な燃料を確保する。"), "resource"
    target = _main_route_target(context)
    if target and probe.propulsion >= 25:
        return ProposedAction(action="move", target_id=target["id"], reason=f"{target['name']}へ向けて主航路を設定する。"), "main_route"
    return ProposedAction(action="wait", reason="実行可能な巡航行動がないため、姿勢制御と通信同期を維持する。"), "recovery"


def _log_decision(
    db: Session,
    probe: Probe,
    action: SimulationAction,
    event: SimulationEvent,
    observations: list[ObservationFact],
    force_log: bool = False,
) -> tuple[bool, str | None]:
    if force_log:
        return True, "manual_step"
    if event.event_type in {"investigate_signal", "collect_resource", "observe"}:
        return True, event.event_type
    if action.validated_action != "move":
        return False, None
    if probe.hull < 35 or probe.communication < 35 or probe.energy < 10:
        return True, "serious_degradation"
    return False, None


def _snapshot_with_event_data(probe: Probe, event: SimulationEvent | None = None) -> dict:
    snapshot = {**probe_snapshot(probe), **mission_time_payload(probe.mission_time)}
    if event:
        for key in ["mission_clock", "sim_timestamp", "sim_elapsed_seconds", "simulation_datetime"]:
            if key in event.data:
                snapshot[key] = event.data[key]
        route_keys = [
            "route_phase",
            "route_started_at_tick",
            "route_from",
            "route_to",
            "route_distance",
            "speed_setting",
            "remaining_distance",
            "next_target_name",
            "navigation_state",
            "navigation_phase",
            "drive_mode",
            "current_speed_m_s",
            "destination_id",
            "destination_name",
            "remaining_distance_km",
            "remaining_distance_pc",
            "eta_datetime",
            "mission_elapsed_seconds",
        ]
        for key in route_keys:
            if key in event.data:
                snapshot[key] = event.data[key]
    return snapshot


def _related_body_ids(db: Session, event: SimulationEvent, observations: list[ObservationFact]) -> list[str]:
    candidates = [event.related_body_id, *(observation.source for observation in observations)]
    result: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in result and db.get(CelestialBody, candidate) is not None:
            result.append(candidate)
    return result


def _log_scenery_context(
    db: Session,
    probe: Probe,
    event: SimulationEvent,
    snapshot: dict,
    observations: list[ObservationFact],
) -> tuple[list[dict], list[dict], dict]:
    destination_id = event.data.get("destination_id") or snapshot.get("target_id")
    target = system_detail(db, str(destination_id)) if destination_id else None
    probe_view = SimpleNamespace(
        current_system_id=snapshot.get("current_system_id", probe.current_system_id),
        display_x=float(snapshot.get("display_x", probe.display_x)),
        display_y=float(snapshot.get("display_y", probe.display_y)),
        display_z=float(snapshot.get("display_z", probe.display_z)),
    )

    body_ids = {observation.source for observation in observations if observation.body_type and observation.source}
    route_bodies: list[CelestialBody] = []
    if target is not None:
        route_bodies = _nearby_route_bodies(db, probe_view, target, event.data.get("route_phase"))
        body_ids.update(body.id for body in route_bodies[:8])
    nearby_bodies = []
    for body_id in sorted(body_ids):
        body = db.get(CelestialBody, body_id)
        if body is None:
            continue
        nearby_bodies.append(
            {
                "id": body.id,
                "name": body.name,
                "body_type": body.body_type,
                "system_id": body.system_id,
                "radius_km": body.radius_km,
                "orbit_radius_km": body.orbit_radius_km,
                "details": body.details,
            }
        )

    environment_items = _route_environment_objects(db, probe_view, target) if target is not None else []
    small_body_items = _route_small_body_layers(db, probe_view, target) if target is not None else []
    route_hazards = _route_small_body_hazards(db, probe_view, target) if target is not None else []
    observed_environment_ids = {observation.source for observation in observations if observation.object_type and observation.source}
    nearby_environment_objects = [
        {
            "id": item.id,
            "name": item.name,
            "object_type": item.object_type,
            "nebula_type": item.details.get("nebula_type"),
            "details": item.details,
        }
        for item in environment_items
        if item.id in observed_environment_ids or len(observed_environment_ids) == 0
    ]
    nearby_environment_objects.extend(
        {
            "id": item.id,
            "name": item.name,
            "object_type": item.layer_type,
            "inner_radius": item.inner_radius,
            "outer_radius": item.outer_radius,
            "details": item.details,
        }
        for item in small_body_items
        if item.id in observed_environment_ids or len(observed_environment_ids) == 0
    )
    nearby_environment_objects.sort(key=lambda item: (item["id"] not in observed_environment_ids, item["id"]))
    nearby_environment_objects = nearby_environment_objects[:8]
    route_context = {
        "origin_system_id": event.data.get("origin_system_id") or snapshot.get("current_system_id"),
        "destination_system_id": destination_id,
        "destination_name": event.data.get("destination_name") or event.data.get("next_target_name"),
        "route_phase": event.data.get("route_phase") or event.data.get("navigation_phase"),
        "remaining_distance": event.data.get("remaining_distance"),
        "remaining_distance_km": event.data.get("remaining_distance_km"),
        "remaining_distance_pc": event.data.get("remaining_distance_pc"),
        "current_speed_m_s": event.data.get("current_speed_m_s"),
        "position": {
            "x": snapshot.get("x"),
            "y": snapshot.get("y"),
            "z": snapshot.get("z"),
            "display_x": snapshot.get("display_x"),
            "display_y": snapshot.get("display_y"),
            "display_z": snapshot.get("display_z"),
        },
        "route_hazards": route_hazards,
    }
    return nearby_bodies, nearby_environment_objects, route_context


async def _persist_log(
    db: Session,
    llm: LLMClient,
    context: ActionContext,
    action: SimulationAction,
    event: SimulationEvent,
    observations: list[ObservationFact],
    interpretations: list[Interpretation],
    snapshot_override: dict | None = None,
) -> ExplorationLog:
    probe = current_probe(db)
    snapshot = snapshot_override or _snapshot_with_event_data(probe, event)
    snapshot["log_number"] = db.query(ExplorationLog).count() + 1
    nearby_bodies, nearby_environment_objects, route_context = _log_scenery_context(db, probe, event, snapshot, observations)
    generated = await safe_generate_log(
        llm,
        LogContext(
            action={
                "id": action.id,
                "action": action.validated_action,
                "reason": action.reason,
                "navigation_intent": action.raw_payload.get("navigation_intent"),
                "route_phase": event.data.get("route_phase"),
                "log_phase": event.data.get("log_phase"),
                "progress_percent": event.data.get("progress_percent"),
                "velocity": probe.velocity,
                "navigation_phase": event.data.get("navigation_phase"),
                "current_speed_m_s": event.data.get("current_speed_m_s"),
                "drive_mode": event.data.get("drive_mode"),
                "speed_setting": event.data.get("speed_setting", STANDARD_SPEED_SETTING),
                "remaining_distance": event.data.get("remaining_distance"),
                "remaining_distance_km": event.data.get("remaining_distance_km"),
                "remaining_distance_pc": event.data.get("remaining_distance_pc"),
                "eta_datetime": event.data.get("eta_datetime"),
                "next_target_name": event.data.get("next_target_name"),
            },
            event={
                "id": event.id,
                "event_type": event.event_type,
                "summary": event.summary,
                "mission_clock": event.data.get("mission_clock"),
                "sim_timestamp": event.data.get("sim_timestamp"),
                "sim_elapsed_seconds": event.data.get("sim_elapsed_seconds"),
                "simulation_datetime": event.data.get("simulation_datetime"),
                "route_phase": event.data.get("route_phase"),
                "log_phase": event.data.get("log_phase"),
                "progress_percent": event.data.get("progress_percent"),
                "velocity": probe.velocity,
                "navigation_phase": event.data.get("navigation_phase"),
                "current_speed_m_s": event.data.get("current_speed_m_s"),
                "drive_mode": event.data.get("drive_mode"),
                "speed_setting": event.data.get("speed_setting", STANDARD_SPEED_SETTING),
                "remaining_distance": event.data.get("remaining_distance"),
                "remaining_distance_km": event.data.get("remaining_distance_km"),
                "remaining_distance_pc": event.data.get("remaining_distance_pc"),
                "eta_datetime": event.data.get("eta_datetime"),
                "next_target_name": event.data.get("next_target_name"),
            },
            probe_snapshot=snapshot,
            observations=observations,
            interpretations=interpretations,
            nearby_bodies=nearby_bodies,
            nearby_environment_objects=nearby_environment_objects,
            route_context=route_context,
            prompt_settings=context.prompt_settings,
        ),
    )
    body_markdown = generated.body_markdown
    if not body_markdown.lstrip().startswith("# INSOMNIA 航行ログ"):
        body_markdown = f"{log_header(snapshot, event)}\n\n{body_markdown}"
    body_markdown = re.sub(r"LOG #\d+", f"LOG #{snapshot['log_number']:03d}", body_markdown, count=1)
    log = ExplorationLog(
        title=generated.title,
        summary=generated.summary,
        body_markdown=body_markdown,
        mission_time=snapshot["mission_time"],
        probe_position={
            "x": snapshot["x"],
            "y": snapshot["y"],
            "z": snapshot["z"],
            "system_id": snapshot["current_system_id"],
            "target_id": snapshot["target_id"],
            "mission_clock": snapshot.get("mission_clock"),
            "sim_timestamp": snapshot.get("sim_timestamp"),
            "sim_elapsed_seconds": snapshot.get("sim_elapsed_seconds"),
        },
        related_event_ids=[event.id],
        related_body_ids=_related_body_ids(db, event, observations),
        probe_state_snapshot=snapshot,
        communication_status="nominal" if snapshot["communication"] > 40 else "degraded",
        reliability=generated.reliability,
    )
    db.add(log)
    db.flush()
    return log


def _pending_navigation_milestone_events(db: Session, probe: Probe) -> list[SimulationEvent]:
    logged_event_ids = {
        event_id
        for related_event_ids in db.scalars(select(ExplorationLog.related_event_ids)).all()
        for event_id in (related_event_ids or [])
    }
    events = db.scalars(
        select(SimulationEvent)
        .where(SimulationEvent.probe_id == probe.id, SimulationEvent.event_type == "navigation_progress")
        .order_by(SimulationEvent.id)
    ).all()
    return [event for event in events if event.id not in logged_event_ids]


def _milestone_snapshot(probe: Probe, event: SimulationEvent) -> dict:
    snapshot = _snapshot_with_event_data(probe, event)
    physical = event.data["physical_position"]
    display = event.data["display_position"]
    sampled_at = str(event.data["sampled_at"])
    sampled_datetime = datetime.fromisoformat(sampled_at.replace("Z", "+00:00"))
    snapshot.update(
        {
            "current_system_id": event.data.get("origin_system_id", probe.current_system_id),
            "target_id": event.data.get("destination_id"),
            "x": physical["x"],
            "y": physical["y"],
            "z": physical["z"],
            "display_x": display["x"],
            "display_y": display["y"],
            "display_z": display["z"],
            "velocity": event.data.get("current_speed_m_s", 0.0),
            "current_mission": event.summary,
            "mission_clock": event.data.get("mission_clock"),
            "sim_timestamp": sampled_at,
            "simulation_datetime": sampled_at,
            "sim_elapsed_seconds": max(0, int((sampled_datetime - MISSION_START_AT).total_seconds())),
            "navigation_phase": event.data.get("navigation_phase"),
            "route_phase": event.data.get("route_phase"),
            "progress_percent": event.data.get("progress_percent"),
        }
    )
    return snapshot


async def _persist_pending_navigation_milestones(
    db: Session,
    llm: LLMClient,
    context: ActionContext,
    probe: Probe,
) -> list[ExplorationLog]:
    logs: list[ExplorationLog] = []
    for event in _pending_navigation_milestone_events(db, probe):
        phase_text = {
            "progress_01": "出発後の加速記録",
            "progress_50": "航路中間域の定期観測",
            "progress_99": "到着前の減速記録",
        }.get(event.data.get("log_phase"), "航路上の定期観測")
        action = SimulationAction(
            probe_id=probe.id,
            proposed_action="move",
            validated_action="move",
            target_id=event.data.get("destination_id"),
            reason=f"{phase_text}を航行記録として保存します。",
            status="accepted",
            validation_message="",
            raw_payload={
                "action": "move",
                "target_id": event.data.get("destination_id"),
                "navigation_intent": "main_route",
                "log_phase": event.data.get("log_phase"),
            },
        )
        db.add(action)
        db.flush()
        event.action_id = action.id
        milestone_snapshot = _milestone_snapshot(probe, event)
        observations = [
            ObservationFact(
                type="navigation",
                value=f"{event.data.get('destination_name', '目的地')}への航路における{phase_text}",
                reliability=_sensor_reliability(probe),
            )
        ]
        interpretations = [Interpretation(hypothesis="航路計画どおりの進捗を維持している", confidence=0.9)]
        target = system_detail(db, str(event.data.get("destination_id") or ""))
        if target is not None:
            probe_view = SimpleNamespace(
                current_system_id=milestone_snapshot["current_system_id"],
                display_x=milestone_snapshot["display_x"],
                display_y=milestone_snapshot["display_y"],
                display_z=milestone_snapshot["display_z"],
            )
            passive, passive_interpretations = passive_observations_during_move(
                db,
                probe_view,
                target,
                float(event.data.get("remaining_distance_pc") or 0.0),
                _sensor_reliability(probe),
                str(event.data.get("route_phase") or event.data.get("navigation_phase") or "interstellar_cruise"),
            )
            observations.extend(passive)
            interpretations.extend(passive_interpretations)
        event.data = {
            **event.data,
            "observations": [item.model_dump() for item in observations],
            "interpretations": [item.model_dump() for item in interpretations],
        }
        logs.append(
            await _persist_log(
                db,
                llm,
                context,
                action,
                event,
                observations,
                interpretations,
                snapshot_override=milestone_snapshot,
            )
        )
    return logs


async def _execute_action(
    db: Session,
    llm: LLMClient,
    proposed: ProposedAction,
    navigation_intent: str,
    context: ActionContext,
    force_log: bool = False,
) -> tuple[SimulationAction, SimulationEvent, ExplorationLog | None, Probe, dict | None]:
    probe = ensure_probe(db)
    validation = validate_with_recovery(db, probe, context, proposed)
    action = SimulationAction(
        probe_id=probe.id,
        proposed_action=proposed.action,
        validated_action=validation.action.action,
        target_id=validation.action.target_id,
        reason=validation.action.reason,
        status=validation.status,
        validation_message=validation.message,
        raw_payload={**proposed.model_dump(), "navigation_intent": navigation_intent},
    )
    db.add(action)
    db.flush()
    event, observations, interpretations = apply_action(db, probe, validation.action)
    event.action_id = action.id
    log_worthy, log_phase = _log_decision(db, probe, action, event, observations, force_log=force_log)
    event.data = {**event.data, "navigation_intent": navigation_intent, "log_worthy": log_worthy, "log_phase": log_phase}
    action.raw_payload = {**action.raw_payload, **{key: event.data[key] for key in event.data if key.startswith("route_") or key in {"speed_setting", "remaining_distance", "next_target_name"}}}
    snapshot = _snapshot_with_event_data(probe, event)
    db.add(ProbeStateHistory(probe_id=probe.id, mission_time=probe.mission_time, snapshot=snapshot))
    milestone_logs = await _persist_pending_navigation_milestones(db, llm, context, probe)
    log = milestone_logs[-1] if milestone_logs else None
    if log_worthy:
        log = await _persist_log(db, llm, context, action, event, observations, interpretations)
    route = event.data.get("route_state") or _route_state(db, probe)
    db.commit()
    db.refresh(probe)
    db.refresh(event)
    db.refresh(action)
    if log:
        db.refresh(log)
    return action, event, log, probe, route

async def run_step(db: Session, llm: LLMClient) -> tuple[SimulationAction, SimulationEvent, ExplorationLog, Probe]:
    probe = ensure_probe(db)
    context = action_context(db, probe)
    scripted = scripted_initial_action(probe)
    if scripted:
        proposed = scripted
        navigation_intent = "main_route"
    else:
        llm_proposed = await safe_propose(llm, context)
        proposed, navigation_intent = navigation_director(db, probe, context, llm_proposed)
    action, event, log, probe, _ = await _execute_action(db, llm, proposed, navigation_intent, context, force_log=True)
    assert log is not None
    return action, event, log, probe


async def _log_pending_navigation_arrival(
    db: Session,
    llm: LLMClient,
    probe: Probe,
    event: SimulationEvent,
    context: ActionContext,
) -> tuple[SimulationAction, SimulationEvent, ExplorationLog, Probe, dict | None]:
    destination_id = event.data.get("destination_id")
    destination_name = event.data.get("destination_name") or destination_id or "目的地"
    action = SimulationAction(
        probe_id=probe.id,
        proposed_action="move",
        validated_action="move",
        target_id=destination_id,
        reason="到着済みの航行イベントをログへ確定します。",
        status="accepted",
        validation_message="",
        raw_payload={"action": "move", "target_id": destination_id, "navigation_intent": "main_route"},
    )
    db.add(action)
    db.flush()
    event.action_id = action.id
    event.data = {
        **event.data,
        "navigation_intent": "main_route",
        "route_phase": "arrived",
        "navigation_phase": "arrived",
        "log_worthy": True,
        "log_phase": "arrival",
    }
    observations = [ObservationFact(type="navigation", value=f"{destination_name}に到着", reliability=_sensor_reliability(probe))]
    interpretations = [Interpretation(hypothesis="航行状態は到着済みとして確定している", confidence=0.86)]
    snapshot = _snapshot_with_event_data(probe, event)
    db.add(ProbeStateHistory(probe_id=probe.id, mission_time=probe.mission_time, snapshot=snapshot))
    log = await _persist_log(db, llm, context, action, event, observations, interpretations)
    route = _route_state(db, probe)
    db.commit()
    db.refresh(probe)
    db.refresh(event)
    db.refresh(action)
    db.refresh(log)
    return action, event, log, probe, route


async def run_tick(db: Session, llm: LLMClient) -> tuple[SimulationAction, SimulationEvent, ExplorationLog | None, Probe, dict | None]:
    probe = ensure_probe(db)
    context = action_context(db, probe)
    proposed, navigation_intent = _deterministic_cruise_action(db, probe, context)
    return await _execute_action(db, llm, proposed, navigation_intent, context, force_log=False)

