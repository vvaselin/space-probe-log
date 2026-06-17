import math
import random
import re
from datetime import UTC, datetime, timedelta

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
    Probe,
    ProbeNavigationState,
    ProbeStateHistory,
    ResourceInventory,
    Signal,
    SimulationAction,
    SimulationEvent,
    StarSystem,
)
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
    navigation_payload,
    synchronize_navigation,
)
from app.services.probe_spec import PROBE_ID, PROBE_LEGACY_IDS, PROBE_NAME, probe_specification
from app.services.snapshots import probe_snapshot
from app.world.generator import SystemSpec, frontier_shell_systems, stable_seed

DISPLAY_STEP_DISTANCE = 13.0
ARRIVAL_DISTANCE = 2.4
LAUNCH_TARGET_ID = "outer-solar-marker"
MAIN_BEACON_ROLE = "far_objective"
MAX_WAIT_STREAK = 1
CRUISE_LOG_COOLDOWN = 5
FUEL_LIMITS_ENABLED = False


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(a, b, strict=True)))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _display_radius(point: tuple[float, float, float]) -> float:
    return math.sqrt(point[0] ** 2 + point[1] ** 2 + point[2] ** 2)


def _physical_radius(point: tuple[float, float, float]) -> float:
    return math.sqrt(point[0] ** 2 + point[1] ** 2 + point[2] ** 2)


def _physical_outward_score(probe: Probe, item: StarSystem) -> tuple[float, float]:
    probe_vector = (probe.x, probe.y, probe.z)
    item_vector = (item.x, item.y, item.z)
    probe_radius = max(_physical_radius(probe_vector), 1e-9)
    item_radius = _physical_radius(item_vector)
    dot = sum(left * right for left, right in zip(probe_vector, item_vector, strict=True)) / max(probe_radius * max(item_radius, 1e-9), 1e-9)
    return item_radius, dot


def display_probe_offset(target: StarSystem) -> tuple[float, float, float]:
    """Keep the visual probe marker readable near large stars or planets."""
    if target.kind == "waypoint" or target.details.get("object_role") == "navigation_waypoint":
        return target.display_x, target.display_y, target.display_z
    rng = random.Random(stable_seed(target.id, "probe-display-offset"))
    x = target.display_x
    y = target.display_y
    z = target.display_z
    length = math.sqrt(x * x + y * y + z * z)
    if length < 0.01:
        direction = (0.78, 0.36, 0.52)
    else:
        direction = (x / length, y / length, z / length)
    angle = rng.uniform(-0.28, 0.28)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    dx = direction[0] * cos_a - direction[2] * sin_a
    dz = direction[0] * sin_a + direction[2] * cos_a
    dy = max(0.18, direction[1]) + 0.14
    magnitude = 7.2 if target.details.get("object_role") == "far_objective" else 5.4
    return x + dx * magnitude, y + dy * magnitude, z + dz * magnitude


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
        and _physical_outward_score(probe, item)[0] >= probe_radius + 0.5
        and _physical_outward_score(probe, item)[1] > 0.05
    ]
    if len(available) >= min_unvisited:
        return
    frontier_rings = [
        int(item.details.get("frontier_ring", 0))
        for item in known_systems
        if item.details.get("object_role") == "frontier_system"
    ]
    next_ring = max(frontier_rings, default=0) + 1
    farthest_radius = max([probe_radius, *[_physical_radius((item.x, item.y, item.z)) for item in known_systems]])
    base_radius = max(10.0, farthest_radius + 1.5)
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
            and _physical_outward_score(probe, item)[0] >= probe_radius + 0.5
            and _physical_outward_score(probe, item)[1] > 0.05
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
    item_radius, outward_alignment = _physical_outward_score(probe, item)
    outward_penalty = 0 if item_radius >= probe_radius + 0.5 and outward_alignment > 0.05 else 1
    visited_penalty = 1 if item.id in visited else 0
    order = int(item.details.get("navigation_order", 50))
    outward_distance = max(0.0, item_radius - probe_radius)
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
    if current and current.details.get("object_role") == MAIN_BEACON_ROLE:
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
    navigation_systems = [item for item in all_systems if item.id != probe.current_system_id]
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
    probe_radius = _display_radius_from_mapping({"display": [context.probe["display_x"], context.probe["display_y"], context.probe["display_z"]]})
    candidates = [
        target
        for target in context.navigation_targets
        if not target.get("visited") and target.get("distance_from_origin", 0) >= probe_radius + 0.5
    ]
    if not candidates:
        candidates = [target for target in context.navigation_targets if not target.get("visited")]
    far_objectives = [target for target in candidates if target.get("object_role") == MAIN_BEACON_ROLE]
    if far_objectives:
        return sorted(far_objectives, key=lambda item: item.get("distance_from_origin", 0))[0]
    frontier = [target for target in candidates if target.get("object_role") == "frontier_system"]
    if frontier:
        return sorted(frontier, key=lambda item: item.get("distance_from_origin", 0))[0]
    return candidates[0] if candidates else _first_navigation_target(context)


def _navigation_intent(action: ProposedAction, target: dict | None = None) -> str:
    if action.action == "investigate_signal":
        return "detour_signal"
    if action.action == "observe":
        return "survey"
    if action.action == "collect_resource":
        return "resource"
    if action.action == "move" and target and target.get("object_role") == MAIN_BEACON_ROLE:
        return "main_route"
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
    if current and current.details.get("object_role") == MAIN_BEACON_ROLE and target and probe.propulsion >= 25:
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


def _advance_toward_target(db: Session, probe: Probe, target: StarSystem) -> tuple[bool, float]:
    start_display = (probe.display_x, probe.display_y, probe.display_z)
    end_display = display_probe_offset(target)
    distance = _distance(start_display, end_display)
    if distance <= ARRIVAL_DISTANCE:
        fraction = 1.0
    else:
        fraction = min(1.0, DISPLAY_STEP_DISTANCE / distance)

    probe.x = _lerp(probe.x, target.x, fraction)
    probe.y = _lerp(probe.y, target.y, fraction)
    probe.z = _lerp(probe.z, target.z, fraction)
    probe.display_x = _lerp(probe.display_x, end_display[0], fraction)
    probe.display_y = _lerp(probe.display_y, end_display[1], fraction)
    probe.display_z = _lerp(probe.display_z, end_display[2], fraction)

    arrived = fraction >= 1.0 or _distance((probe.display_x, probe.display_y, probe.display_z), end_display) <= ARRIVAL_DISTANCE
    if arrived:
        probe.x, probe.y, probe.z = target.x, target.y, target.z
        probe.display_x, probe.display_y, probe.display_z = end_display
        probe.current_system_id = target.id
        probe.target_id = None
        probe.velocity = 0.0
    else:
        probe.target_id = target.id
        probe.velocity = 1.0
    db.flush()
    return arrived, distance


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
    timestamp = utcnow().strftime("%Y/%m/%d %H:%M:%S UTC")
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


def passive_observations_during_move(
    db: Session,
    probe: Probe,
    target: StarSystem,
    remaining_before_step: float,
    reliability: float,
) -> tuple[list[ObservationFact], list[Interpretation]]:
    observations = [
        ObservationFact(
            type="passive_sighting",
            value=f"航路前方に{target.name}の{'航路標の微光' if target.kind == 'waypoint' else '恒星光'}を捉えた",
            reliability=reliability,
            sighting_level="detected" if target.kind == "waypoint" else "resolved",
            source=target.id,
            distance_hint=f"残距離指標 {remaining_before_step:.1f}",
        )
    ]
    interpretations = [
        Interpretation(
            hypothesis="受動観測は航路維持と周辺把握に利用できるが、単独では発見確定には不足している",
            confidence=min(0.82, reliability * 0.72),
        )
    ]

    probe_radius = _display_radius(_vector_from_probe(probe))
    if probe.current_system_id != "sol" and probe_radius > 18:
        observations.append(
            ObservationFact(
                type="passive_sighting",
                value="後方の太陽系を青白い点像として分離した",
                reliability=max(0.2, reliability * 0.88),
                sighting_level="resolved",
                source="sol",
                distance_hint="後方視野",
            )
        )
    elif probe_radius > 9:
        observations.append(
            ObservationFact(
                type="passive_sighting",
                value="後方視野で太陽系内の光度がゆっくり低下している",
                reliability=max(0.2, reliability * 0.82),
                sighting_level="detected",
                source="sol",
                distance_hint="後方視野",
            )
        )

    side_system = _nearest_side_system(db, probe, target)
    if side_system and len(observations) < 3:
        observations.append(
            ObservationFact(
                type="passive_sighting",
                value=f"側方星野で{side_system.name}の恒星光に視差変化を記録した",
                reliability=max(0.2, reliability * 0.8),
                sighting_level="resolved",
                source=side_system.id,
                distance_hint="側方視野",
            )
        )

    signal = _passive_signal_hint(db, probe, target)
    if signal and len(observations) < 3:
        observations.append(
            ObservationFact(
                type="passive_signal",
                value=f"{signal.kind}の微弱な反復を受動検出した",
                reliability=max(0.2, min(0.95, reliability * signal.strength)),
                sighting_level="detected",
                source=signal.id,
                distance_hint="航路周辺",
            )
        )
        interpretations.append(
            Interpretation(
                hypothesis="受動検出された信号は、到着後に寄り道調査の候補になる",
                confidence=max(0.2, min(0.75, reliability * signal.strength * 0.72)),
            )
        )
    return observations[:3], interpretations


def passive_observations_during_move(
    db: Session,
    probe: Probe,
    target: StarSystem,
    remaining_before_step: float,
    reliability: float,
) -> tuple[list[ObservationFact], list[Interpretation]]:
    target_kind = "航路標の微光" if target.kind == "waypoint" else "恒星光"
    observations = [
        ObservationFact(
            type="passive_sighting",
            value=f"航路前方に{target.name}の{target_kind}を捉えた",
            reliability=reliability,
            sighting_level="detected" if target.kind == "waypoint" else "resolved",
            source=target.id,
            distance_hint=f"残距離推定 {remaining_before_step:.1f}",
        )
    ]
    interpretations = [
        Interpretation(
            hypothesis="受動観測は航路維持に利用できるが、単独では発見確定には不足している",
            confidence=min(0.82, reliability * 0.72),
        )
    ]

    probe_radius = _display_radius(_vector_from_probe(probe))
    if probe.current_system_id != "sol" and probe_radius > 18:
        observations.append(
            ObservationFact(
                type="passive_sighting",
                value="後方視野で太陽系を淡い白点として分離した",
                reliability=max(0.2, reliability * 0.88),
                sighting_level="resolved",
                source="sol",
                distance_hint="後方視野",
            )
        )
    elif probe_radius > 9:
        observations.append(
            ObservationFact(
                type="passive_sighting",
                value="後方視野で太陽系内の光度がゆっくり低下している",
                reliability=max(0.2, reliability * 0.82),
                sighting_level="detected",
                source="sol",
                distance_hint="後方視野",
            )
        )

    side_system = _nearest_side_system(db, probe, target)
    if side_system and len(observations) < 3:
        observations.append(
            ObservationFact(
                type="passive_sighting",
                value=f"側方星野で{side_system.name}の恒星光に視差変化を記録した",
                reliability=max(0.2, reliability * 0.8),
                sighting_level="resolved",
                source=side_system.id,
                distance_hint="側方視野",
            )
        )

    signal = _passive_signal_hint(db, probe, target)
    if signal and len(observations) < 3:
        observations.append(
            ObservationFact(
                type="passive_signal",
                value=f"{signal.kind}の微弱な反射を受動検出した",
                reliability=max(0.2, min(0.95, reliability * signal.strength)),
                sighting_level="detected",
                source=signal.id,
                distance_hint="航路周辺",
            )
        )
        interpretations.append(
            Interpretation(
                hypothesis="受動検出された信号は、到着後に寄り道調査の候補になり得る",
                confidence=max(0.2, min(0.75, reliability * signal.strength * 0.72)),
            )
        )
    return observations[:3], interpretations


def apply_action(db: Session, probe: Probe, action: ProposedAction) -> tuple[SimulationEvent, list[ObservationFact], list[Interpretation]]:
    observations: list[ObservationFact] = []
    interpretations: list[Interpretation] = []
    related_body_id: str | None = None
    related_signal_id: str | None = None
    summary = "探査機は待機し、姿勢制御と通信同期を維持した。"
    event_type = action.action
    if action.action == "move" and action.target_id:
        target = system_detail(db, action.target_id)
        assert target is not None
        previous_target = probe.target_id
        mission_time_before = probe.mission_time
        arrived, remaining_before_step = _advance_toward_target(db, probe, target)
        probe.fuel = max(0, probe.fuel - 2)
        probe.energy = max(0, probe.energy - 1.5)
        reliability = _sensor_reliability(probe)
        if arrived:
            summary = f"{target.name} へ到着し、航行目標を解除した。"
            observations.append(ObservationFact(type="navigation", value=f"{target.name} へ到着", reliability=reliability))
        elif previous_target == target.id:
            summary = f"{target.name} へ向けて外縁航路を維持した。残距離指標 {remaining_before_step:.1f}。"
            observations.append(ObservationFact(type="navigation", value=f"{target.name} へ向けた外向き航行を継続", reliability=reliability))
        elif mission_time_before == 0 and target.id == LAUNCH_TARGET_ID:
            summary = f"発射シークエンスを完了し、{target.name} への外向き航行を開始した。"
            observations.append(ObservationFact(type="navigation", value="地球付近から太陽系外縁への航路へ移行", reliability=reliability))
        else:
            summary = f"{target.name} への外向き航行を開始した。太陽系離脱軌道へ段階的に移行する。"
            observations.append(ObservationFact(type="navigation", value=f"{target.name} への航路を設定", reliability=reliability))
        passive_observations, passive_interpretations = passive_observations_during_move(
            db,
            probe,
            target,
            remaining_before_step,
            reliability,
        )
        observations.extend(passive_observations)
        interpretations.extend(passive_interpretations)
        interpretations.append(Interpretation(hypothesis="外側へ向かう航路は継続可能である", confidence=min(0.86, reliability * 0.78)))
    elif action.action == "observe":
        current = system_detail(db, probe.current_system_id)
        reliability = _sensor_reliability(probe)
        if current and current.bodies:
            for body in current.bodies[:3]:
                related_body_id = related_body_id or body.id
                observations.append(
                    ObservationFact(type="celestial_body", value=f"{body.name} ({body.body_type}) を確認", reliability=reliability)
                )
            interpretations.append(Interpretation(hypothesis=f"{current.name} は継続調査に値する安定した観測対象である", confidence=reliability * 0.7))
        elif probe.target_id:
            observations.append(ObservationFact(type="navigation", value=f"{probe.target_id} へ向けた航行姿勢を維持", reliability=reliability))
            interpretations.append(Interpretation(hypothesis="太陽系外縁へ向かう航路は安定している", confidence=reliability * 0.62))
        probe.energy = max(0, probe.energy - 4)
        probe.storage_used = min(probe.storage_capacity, probe.storage_used + 4)
        summary = "周辺天体の分光・測距観測を実施した。"
    elif action.action == "investigate_signal" and action.target_id:
        signal = signal_by_id(db, action.target_id)
        assert signal is not None
        reliability = min(0.99, _sensor_reliability(probe) * signal.strength)
        observations.append(
            ObservationFact(type=signal.kind, value=f"{signal.details.get('frequency', '未知周波数')} 付近の信号を確認", reliability=reliability)
        )
        interpretations.append(Interpretation(hypothesis="人工的なビーコンである可能性", confidence=min(0.85, reliability * 0.72)))
        signal.investigated = True
        related_signal_id = signal.id
        related_body_id = signal.body_id
        probe.energy = max(0, probe.energy - 8)
        probe.storage_used = min(probe.storage_capacity, probe.storage_used + 6)
        summary = f"{signal.id} の周期性と強度変化を記録した。"
    elif action.action == "collect_resource":
        current = db.get(StarSystem, probe.current_system_id)
        resource_name = "water_ice"
        quantity = 1.5
        if current and current.resources:
            resource_name = max(current.resources, key=lambda key: current.resources[key])
        probe.collected_resources = {**probe.collected_resources, resource_name: probe.collected_resources.get(resource_name, 0) + quantity}
        inventory = db.scalar(select(ResourceInventory).where(ResourceInventory.probe_id == probe.id, ResourceInventory.resource_name == resource_name))
        if inventory is None:
            inventory = ResourceInventory(probe_id=probe.id, resource_name=resource_name, quantity=0)
            db.add(inventory)
        inventory.quantity += quantity
        fuel_gain = 14.0 if resource_name in {"water_ice", "hydrogen"} else 6.0
        probe.fuel = min(100, probe.fuel + fuel_gain)
        probe.energy = max(0, probe.energy - 6)
        probe.storage_used = min(probe.storage_capacity, probe.storage_used + 3)
        observations.append(ObservationFact(type="resource", value=f"{resource_name} を {quantity:.1f} 単位採取し、燃料を {fuel_gain:.1f} 回復", reliability=0.9))
        interpretations.append(Interpretation(hypothesis="推進剤または修復・冷却材として利用できる可能性", confidence=0.65))
        summary = f"{resource_name} を {quantity:.1f} 単位採取し、航行継続用の燃料へ回した。"
    else:
        probe.energy = min(100, probe.energy + 2)
        probe.velocity = 0 if not probe.target_id else probe.velocity
    probe.mission_time += 1
    probe.last_updated_at = utcnow()
    event = SimulationEvent(
        probe_id=probe.id,
        event_type=event_type,
        mission_time=probe.mission_time,
        summary=summary,
        related_body_id=related_body_id,
        related_signal_id=related_signal_id,
        data={"observations": [item.model_dump() for item in observations], "interpretations": [item.model_dump() for item in interpretations]},
    )
    db.add(event)
    db.flush()
    for obs in observations:
        if obs.sighting_level != "confirmed":
            continue
        db.add(
            Discovery(
                probe_id=probe.id,
                event_id=event.id,
                target_id=related_signal_id or related_body_id or probe.target_id,
                observation_type=obs.type,
                value=obs.value,
                reliability=obs.reliability,
                interpretations=[item.model_dump() for item in interpretations],
            )
        )
    return event, observations, interpretations


def apply_action(db: Session, probe: Probe, action: ProposedAction) -> tuple[SimulationEvent, list[ObservationFact], list[Interpretation]]:
    observations: list[ObservationFact] = []
    interpretations: list[Interpretation] = []
    related_body_id: str | None = None
    related_signal_id: str | None = None
    summary = "探査機は待機し、姿勢制御と通信同期を維持した。"
    event_type = action.action

    if action.action == "move" and action.target_id:
        target = system_detail(db, action.target_id)
        assert target is not None
        previous_target = probe.target_id
        mission_time_before = probe.mission_time
        arrived, remaining_before_step = _advance_toward_target(db, probe, target)
        probe.fuel = max(0, probe.fuel - 2)
        probe.energy = max(0, probe.energy - 1.5)
        reliability = _sensor_reliability(probe)
        if arrived:
            summary = f"{target.name}へ到着し、航行目標を解除した。"
            observations.append(ObservationFact(type="navigation", value=f"{target.name}へ到着", reliability=reliability))
        elif previous_target == target.id:
            summary = f"{target.name}へ向けて外向き航路を継続した。残距離推定 {remaining_before_step:.1f}。"
            observations.append(ObservationFact(type="navigation", value=f"{target.name}へ向けた外向き航行を継続", reliability=reliability))
        elif mission_time_before == 0 and target.id == LAUNCH_TARGET_ID:
            summary = f"発射シークエンスを完了し、{target.name}への外向き航行を開始した。"
            observations.append(ObservationFact(type="navigation", value="地球付近から太陽系外縁への航路へ移行", reliability=reliability))
        else:
            summary = f"{target.name}への外向き航行を開始した。"
            observations.append(ObservationFact(type="navigation", value=f"{target.name}への航路を設定", reliability=reliability))
        passive_observations, passive_interpretations = passive_observations_during_move(
            db,
            probe,
            target,
            remaining_before_step,
            reliability,
        )
        observations.extend(passive_observations)
        interpretations.extend(passive_interpretations)
        interpretations.append(Interpretation(hypothesis="外側へ向かう航路は継続可能である", confidence=min(0.86, reliability * 0.78)))

    elif action.action == "observe":
        current = system_detail(db, probe.current_system_id)
        reliability = _sensor_reliability(probe)
        if current and current.bodies:
            for body in current.bodies[:3]:
                related_body_id = related_body_id or body.id
                observations.append(ObservationFact(type="celestial_body", value=f"{body.name} ({body.body_type})を確認", reliability=reliability))
            interpretations.append(Interpretation(hypothesis=f"{current.name}は継続調査に値する安定した観測対象である", confidence=reliability * 0.7))
        elif probe.target_id:
            observations.append(ObservationFact(type="navigation", value=f"{probe.target_id}へ向けた航行姿勢を維持", reliability=reliability))
            interpretations.append(Interpretation(hypothesis="太陽系外縁へ向かう航路は安定している", confidence=reliability * 0.62))
        probe.energy = max(0, probe.energy - 4)
        probe.storage_used = min(probe.storage_capacity, probe.storage_used + 4)
        summary = "周辺天体の分類・測距観測を実行した。"

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
        summary = f"{signal.id}の周期性と強度変化を記録した。"

    elif action.action == "collect_resource":
        current = db.get(StarSystem, probe.current_system_id)
        resource_name = "water_ice"
        quantity = 1.5
        if current and current.resources:
            resource_name = max(current.resources, key=lambda key: current.resources[key])
        probe.collected_resources = {**probe.collected_resources, resource_name: probe.collected_resources.get(resource_name, 0) + quantity}
        inventory = db.scalar(select(ResourceInventory).where(ResourceInventory.probe_id == probe.id, ResourceInventory.resource_name == resource_name))
        if inventory is None:
            inventory = ResourceInventory(probe_id=probe.id, resource_name=resource_name, quantity=0)
            db.add(inventory)
        inventory.quantity += quantity
        fuel_gain = 14.0 if resource_name in {"water_ice", "hydrogen"} else 6.0
        probe.fuel = min(100, probe.fuel + fuel_gain)
        probe.energy = max(0, probe.energy - 6)
        probe.storage_used = min(probe.storage_capacity, probe.storage_used + 3)
        observations.append(ObservationFact(type="resource", value=f"{resource_name}を{quantity:.1f}単位採取し、燃料を{fuel_gain:.1f}回復", reliability=0.9))
        interpretations.append(Interpretation(hypothesis="推進剤または修復・冷却材として利用できる可能性", confidence=0.65))
        summary = f"{resource_name}を{quantity:.1f}単位採取し、航行継続用の燃料へ回した。"

    else:
        probe.energy = min(100, probe.energy + 2)
        probe.velocity = 0 if not probe.target_id else probe.velocity

    probe.mission_time += 1
    probe.last_updated_at = utcnow()
    event = SimulationEvent(
        probe_id=probe.id,
        event_type=event_type,
        mission_time=probe.mission_time,
        summary=summary,
        related_body_id=related_body_id,
        related_signal_id=related_signal_id,
        data={"observations": [item.model_dump() for item in observations], "interpretations": [item.model_dump() for item in interpretations]},
    )
    db.add(event)
    db.flush()
    for obs in observations:
        if obs.sighting_level != "confirmed":
            continue
        db.add(
            Discovery(
                probe_id=probe.id,
                event_id=event.id,
                target_id=related_signal_id or related_body_id or probe.target_id,
                observation_type=obs.type,
                value=obs.value,
                reliability=obs.reliability,
                interpretations=[item.model_dump() for item in interpretations],
            )
        )
    return event, observations, interpretations


def _route_state(db: Session, probe: Probe) -> dict | None:
    if not probe.target_id:
        return None
    target = system_detail(db, probe.target_id)
    if target is None:
        return None
    current = (probe.display_x, probe.display_y, probe.display_z)
    destination = display_probe_offset(target)
    remaining = _distance(current, destination)
    origin_radius = _display_radius(current)
    target_radius = _display_radius(destination)
    total_hint = max(remaining, abs(target_radius - origin_radius), 1.0)
    progress = max(0.0, min(0.99, 1.0 - remaining / (remaining + total_hint)))
    return {
        "target_id": target.id,
        "target_name": target.name,
        "progress": progress,
        "remaining_distance": remaining,
    }


def _deterministic_cruise_action(db: Session, probe: Probe, context: ActionContext) -> tuple[ProposedAction, str]:
    scripted = scripted_initial_action(probe)
    if scripted:
        return scripted, "main_route"
    current = system_detail(db, probe.current_system_id)
    target = _main_route_target(context)
    if current and current.details.get("object_role") == MAIN_BEACON_ROLE and target and probe.propulsion >= 25:
        return ProposedAction(action="move", target_id=target["id"], reason=f"Continue outward from the outer terminus toward frontier target {target['name']}."), "main_route"
    current = system_detail(db, probe.current_system_id)
    target = _main_route_target(context)
    if current and current.details.get("object_role") == MAIN_BEACON_ROLE and target and probe.propulsion >= 25:
        return ProposedAction(action="move", target_id=target["id"], reason=f"Continue outward from the outer terminus toward frontier target {target['name']}."), "main_route"
    if context.visible_signals and probe.energy >= 8 and probe.sensors >= 10 and probe.storage_used + 6 <= probe.storage_capacity:
        signal = context.visible_signals[0]
        return ProposedAction(action="investigate_signal", target_id=signal["id"], reason="現在地で未調査の信号を確認する。"), "detour_signal"
    if FUEL_LIMITS_ENABLED and probe.fuel < 18 and _can_collect_here(db, probe):
        return ProposedAction(action="collect_resource", reason="巡航継続に必要な燃料を確保する。"), "resource"
    if target and probe.propulsion >= 25:
        return ProposedAction(action="move", target_id=target["id"], reason=f"{target['name']}へ向けて主航路を進む。"), "main_route"
    return ProposedAction(action="wait", reason="実行可能な巡航行動がないため、姿勢制御と通信同期を維持する。"), "recovery"


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


def _deterministic_cruise_action(db: Session, probe: Probe, context: ActionContext) -> tuple[ProposedAction, str]:
    scripted = scripted_initial_action(probe)
    if scripted:
        return scripted, "main_route"
    current = system_detail(db, probe.current_system_id)
    target = _main_route_target(context)
    if current and current.details.get("object_role") == MAIN_BEACON_ROLE and target and probe.propulsion >= 25:
        return ProposedAction(action="move", target_id=target["id"], reason=f"Continue outward from the outer terminus toward frontier target {target['name']}."), "main_route"
    if context.visible_signals and probe.energy >= 8 and probe.sensors >= 10 and probe.storage_used + 6 <= probe.storage_capacity:
        signal = context.visible_signals[0]
        return ProposedAction(action="investigate_signal", target_id=signal["id"], reason="Investigate the unprocessed local signal before continuing."), "detour_signal"
    if FUEL_LIMITS_ENABLED and probe.fuel < 18 and _can_collect_here(db, probe):
        return ProposedAction(action="collect_resource", reason="Collect available resources before continuing cruise."), "resource"
    if target and probe.propulsion >= 25:
        return ProposedAction(action="move", target_id=target["id"], reason=f"Plot main route toward {target['name']}."), "main_route"
    return ProposedAction(action="wait", reason="Hold attitude and communications; no executable cruise action is available."), "recovery"


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
    if any(obs.type == "navigation" and "到着" in obs.value for obs in observations):
        return True, "arrival"
    if action.target_id == "sys-outer-terminus" and not _phase_logged(db, "outer_lighthouse_detected"):
        return True, "outer_lighthouse_detected"
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
    snapshot = probe_snapshot(probe)
    db.add(ProbeStateHistory(probe_id=probe.id, mission_time=probe.mission_time, snapshot=snapshot))
    log = None
    if log_worthy:
        log = await _persist_log(db, llm, context, action, event, observations, interpretations)
    route = _route_state(db, probe)
    db.commit()
    db.refresh(probe)
    db.refresh(event)
    db.refresh(action)
    if log:
        db.refresh(log)
    return action, event, log, probe, route


def _deterministic_cruise_action(db: Session, probe: Probe, context: ActionContext) -> tuple[ProposedAction, str]:
    scripted = scripted_initial_action(probe)
    if scripted:
        return scripted, "main_route"
    current = system_detail(db, probe.current_system_id)
    target = _main_route_target(context)
    if current and current.details.get("object_role") == MAIN_BEACON_ROLE and target and probe.propulsion >= 25:
        return ProposedAction(action="move", target_id=target["id"], reason=f"Continue outward from the outer terminus toward frontier target {target['name']}."), "main_route"
    if context.visible_signals and probe.energy >= 8 and probe.sensors >= 10 and probe.storage_used + 6 <= probe.storage_capacity:
        signal = context.visible_signals[0]
        return ProposedAction(action="investigate_signal", target_id=signal["id"], reason="Investigate the unprocessed local signal before continuing."), "detour_signal"
    if FUEL_LIMITS_ENABLED and probe.fuel < 18 and _can_collect_here(db, probe):
        return ProposedAction(action="collect_resource", reason="Collect available resources before continuing cruise."), "resource"
    if target and probe.propulsion >= 25:
        return ProposedAction(action="move", target_id=target["id"], reason=f"Plot main route toward {target['name']}."), "main_route"
    return ProposedAction(action="wait", reason="Hold attitude and communications; no executable cruise action is available."), "recovery"


def _deterministic_cruise_action(db: Session, probe: Probe, context: ActionContext) -> tuple[ProposedAction, str]:
    scripted = scripted_initial_action(probe)
    if scripted:
        return scripted, "main_route"
    current = system_detail(db, probe.current_system_id)
    target = _main_route_target(context)
    if current and current.details.get("object_role") == MAIN_BEACON_ROLE and target and probe.propulsion >= 25:
        return ProposedAction(action="move", target_id=target["id"], reason=f"Continue outward from the outer terminus toward frontier target {target['name']}."), "main_route"
    if context.visible_signals and probe.energy >= 8 and probe.sensors >= 10 and probe.storage_used + 6 <= probe.storage_capacity:
        signal = context.visible_signals[0]
        return ProposedAction(action="investigate_signal", target_id=signal["id"], reason="Investigate the unprocessed local signal before continuing."), "detour_signal"
    if FUEL_LIMITS_ENABLED and probe.fuel < 18 and _can_collect_here(db, probe):
        return ProposedAction(action="collect_resource", reason="Collect available resources before continuing cruise."), "resource"
    if target and probe.propulsion >= 25:
        return ProposedAction(action="move", target_id=target["id"], reason=f"Plot main route toward {target['name']}."), "main_route"
    return ProposedAction(action="wait", reason="Hold attitude and communications; no executable cruise action is available."), "recovery"


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


async def run_tick(db: Session, llm: LLMClient) -> tuple[SimulationAction, SimulationEvent, ExplorationLog | None, Probe, dict | None]:
    probe = ensure_probe(db)
    context = action_context(db, probe)
    proposed, navigation_intent = _deterministic_cruise_action(db, probe, context)
    return await _execute_action(db, llm, proposed, navigation_intent, context, force_log=False)


# Final cruise model overrides. These names are resolved at runtime by run_step/run_tick.
MISSION_START_AT = datetime(2080, 5, 2, 12, 0, 0, tzinfo=UTC)
SIM_SECONDS_PER_REAL_SECOND = 600
REAL_SECONDS_PER_TICK = 1.8
SIM_SECONDS_PER_TICK = int(SIM_SECONDS_PER_REAL_SECOND * REAL_SECONDS_PER_TICK)
STANDARD_SPEED_SETTING = "標準巡航"
MAX_CRUISE_SPEED = 4.0
ACCELERATION_TICKS = 3
DECELERATION_DISTANCE = 12.0


def sim_elapsed_seconds_for_tick(mission_time: int) -> int:
    return max(0, mission_time) * SIM_SECONDS_PER_TICK


def sim_datetime_for_tick(mission_time: int) -> datetime:
    return MISSION_START_AT + timedelta(seconds=sim_elapsed_seconds_for_tick(mission_time))


def mission_clock_for_tick(mission_time: int) -> str:
    return sim_datetime_for_tick(mission_time).strftime("%Y/%m/%d %H:%M:%S UTC")


def mission_time_payload(mission_time: int) -> dict:
    sim_dt = sim_datetime_for_tick(mission_time)
    return {
        "mission_clock": sim_dt.strftime("%Y/%m/%d %H:%M:%S UTC"),
        "sim_timestamp": sim_dt.isoformat().replace("+00:00", "Z"),
        "sim_elapsed_seconds": sim_elapsed_seconds_for_tick(mission_time),
    }


def _latest_route_state(db: Session, probe: Probe) -> dict | None:
    events = db.scalars(
        select(SimulationEvent)
        .where(SimulationEvent.probe_id == probe.id)
        .order_by(SimulationEvent.id.desc())
        .limit(30)
    ).all()
    for event in events:
        route_state = event.data.get("route_state")
        if route_state and route_state.get("target_id") == probe.target_id:
            return route_state
    return None


def _route_vectors(probe: Probe, target: StarSystem) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    return (probe.display_x, probe.display_y, probe.display_z), display_probe_offset(target)


def _build_route_state(probe: Probe, target: StarSystem) -> dict:
    start, destination = _route_vectors(probe, target)
    return {
        "target_id": target.id,
        "target_name": target.name,
        "route_phase": "course_plotted",
        "route_started_at_tick": probe.mission_time + 1,
        "route_from": {"x": start[0], "y": start[1], "z": start[2]},
        "route_to": {"x": destination[0], "y": destination[1], "z": destination[2]},
        "route_distance": _distance(start, destination),
        "speed_setting": STANDARD_SPEED_SETTING,
        "velocity": 0.0,
        "progress": 0.0,
        "remaining_distance": _distance(start, destination),
    }


def _route_progress(route_state: dict, point: tuple[float, float, float]) -> tuple[float, float]:
    destination = route_state["route_to"]
    remaining = _distance(point, (destination["x"], destination["y"], destination["z"]))
    total = max(float(route_state.get("route_distance", remaining)), 1.0)
    progress = max(0.0, min(1.0, 1.0 - remaining / total))
    return progress, remaining


def _speed_for_route(probe: Probe, route_state: dict, remaining: float) -> tuple[str, float]:
    ticks_since_start = max(0, probe.mission_time - int(route_state.get("route_started_at_tick", probe.mission_time)))
    accel_factor = min(1.0, (ticks_since_start + 1) / ACCELERATION_TICKS)
    decel_factor = max(0.18, min(1.0, remaining / DECELERATION_DISTANCE))
    velocity = MAX_CRUISE_SPEED * min(accel_factor, decel_factor)
    if remaining <= ARRIVAL_DISTANCE:
        return "arrived", remaining
    if decel_factor < 1.0:
        return "decelerating", min(velocity, remaining)
    if accel_factor < 1.0:
        return "accelerating", min(velocity, remaining)
    return "cruising", min(velocity, remaining)


def _advance_toward_target(db: Session, probe: Probe, target: StarSystem) -> tuple[bool, float, dict]:
    route_state = _latest_route_state(db, probe)
    if not route_state:
        route_state = _build_route_state(probe, target)
        probe.target_id = target.id
        probe.velocity = 0.0
        db.flush()
        return False, route_state["remaining_distance"], route_state

    route_from = route_state["route_from"]
    origin_tuple = (route_from["x"], route_from["y"], route_from["z"])
    destination = route_state["route_to"]
    destination_tuple = (destination["x"], destination["y"], destination["z"])
    previous_progress = max(0.0, min(1.0, float(route_state.get("progress", 0.0))))
    total_distance = max(float(route_state.get("route_distance", 0.0)), 1e-9)
    remaining_before = total_distance * (1.0 - previous_progress)
    phase, step_distance = _speed_for_route(probe, route_state, remaining_before)

    if phase == "arrived" or step_distance >= remaining_before:
        progress = 1.0
    else:
        progress = max(0.0, min(1.0, previous_progress + step_distance / total_distance))

    probe.display_x = _lerp(origin_tuple[0], destination_tuple[0], progress)
    probe.display_y = _lerp(origin_tuple[1], destination_tuple[1], progress)
    probe.display_z = _lerp(origin_tuple[2], destination_tuple[2], progress)
    probe.x = _lerp(probe.x, target.x, max(0.0, min(1.0, progress - previous_progress)))
    probe.y = _lerp(probe.y, target.y, max(0.0, min(1.0, progress - previous_progress)))
    probe.z = _lerp(probe.z, target.z, max(0.0, min(1.0, progress - previous_progress)))

    new_point = (probe.display_x, probe.display_y, probe.display_z)
    progress, remaining_after = _route_progress(route_state, new_point)
    arrived = remaining_after <= ARRIVAL_DISTANCE or progress >= 1.0
    if arrived:
        probe.x, probe.y, probe.z = target.x, target.y, target.z
        probe.display_x, probe.display_y, probe.display_z = destination_tuple
        probe.current_system_id = target.id
        probe.target_id = None
        probe.velocity = 0.0
        ensure_frontier_targets(db, probe, min_unvisited=6)
        phase = "arrived"
        progress = 1.0
        remaining_after = 0.0
    else:
        probe.target_id = target.id
        probe.velocity = step_distance

    route_state = {
        **route_state,
        "route_phase": phase,
        "velocity": probe.velocity,
        "progress": progress,
        "remaining_distance": remaining_after,
    }
    db.flush()
    return arrived, remaining_before, route_state


def scripted_initial_action(probe: Probe) -> ProposedAction | None:
    if probe.target_id:
        return ProposedAction(action="move", target_id=probe.target_id, reason="設定済みの航路を継続する。")
    if probe.mission_time == 0 and probe.current_system_id == "sol":
        return ProposedAction(action="move", target_id=LAUNCH_TARGET_ID, reason="発射シークエンスを完了し、太陽系外縁への航路を設定する。")
    return None


def log_header(snapshot: dict, event: SimulationEvent) -> str:
    log_number = int(snapshot.get("log_number", snapshot["mission_time"]))
    timestamp = snapshot.get("mission_clock") or mission_clock_for_tick(log_number)
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
) -> tuple[list[ObservationFact], list[Interpretation]]:
    target_kind = "航路標の微光" if target.kind == "waypoint" else "恒星光"
    observations = [
        ObservationFact(
            type="passive_sighting",
            value=f"航路前方に{target.name}の{target_kind}を捉えた",
            reliability=reliability,
            sighting_level="detected" if target.kind == "waypoint" else "resolved",
            source=target.id,
            distance_hint=f"残距離推定 {remaining_before_step:.1f}",
        )
    ]
    interpretations = [
        Interpretation(
            hypothesis="受動観測は航路維持に利用できるが、単独では発見確定には不足している",
            confidence=min(0.82, reliability * 0.72),
        )
    ]
    probe_radius = _display_radius(_vector_from_probe(probe))
    if probe.current_system_id != "sol" and probe_radius > 18:
        observations.append(
            ObservationFact(
                type="passive_sighting",
                value="後方視野で太陽系を淡い白点として分離した",
                reliability=max(0.2, reliability * 0.88),
                sighting_level="resolved",
                source="sol",
                distance_hint="後方視野",
            )
        )
    elif probe_radius > 9:
        observations.append(
            ObservationFact(
                type="passive_sighting",
                value="後方視野で太陽系内の光度がゆっくり低下している",
                reliability=max(0.2, reliability * 0.82),
                sighting_level="detected",
                source="sol",
                distance_hint="後方視野",
            )
        )
    side_system = _nearest_side_system(db, probe, target)
    if side_system and len(observations) < 3:
        observations.append(
            ObservationFact(
                type="passive_sighting",
                value=f"側方星野で{side_system.name}の恒星光に視差変化を記録した",
                reliability=max(0.2, reliability * 0.8),
                sighting_level="resolved",
                source=side_system.id,
                distance_hint="側方視野",
            )
        )
    signal = _passive_signal_hint(db, probe, target)
    if signal and len(observations) < 3:
        observations.append(
            ObservationFact(
                type="passive_signal",
                value=f"{signal.kind}の微弱な反射を受動検出した",
                reliability=max(0.2, min(0.95, reliability * signal.strength)),
                sighting_level="detected",
                source=signal.id,
                distance_hint="航路周辺",
            )
        )
        interpretations.append(
            Interpretation(
                hypothesis="受動検出された信号は、到着後に寄り道調査の候補になり得る",
                confidence=max(0.2, min(0.75, reliability * signal.strength * 0.72)),
            )
        )
    return observations[:3], interpretations


def apply_action(db: Session, probe: Probe, action: ProposedAction) -> tuple[SimulationEvent, list[ObservationFact], list[Interpretation]]:
    observations: list[ObservationFact] = []
    interpretations: list[Interpretation] = []
    related_body_id: str | None = None
    related_signal_id: str | None = None
    summary = "探査機は待機し、姿勢制御と通信同期を維持した。"
    event_type = action.action
    route_state: dict | None = None
    nav_state = None
    clock, _ = advance_simulation_clock(db) if probe.mission_time > 0 else (ensure_simulation_clock(db), 0.0)
    simulation_datetime = clock.simulation_datetime
    if simulation_datetime.tzinfo is None:
        simulation_datetime = simulation_datetime.replace(tzinfo=UTC)
    reliability = _sensor_reliability(probe)

    if action.action == "move" and action.target_id:
        target = system_detail(db, action.target_id)
        assert target is not None
        previous_target = probe.target_id
        existing_route = _latest_route_state(db, probe) if previous_target == target.id else None
        nav_state = active_navigation_state(db, probe)
        if nav_state is None or nav_state.destination_system_id != target.id:
            nav_state = begin_navigation(db, probe, target, simulation_datetime)
        else:
            synchronize_navigation(db, probe, nav_state, target, simulation_datetime)
        if not existing_route:
            route_state = _build_route_state(probe, target)
            probe.target_id = target.id
            probe.velocity = 0.0
            if probe.mission_time == 0 and target.id == LAUNCH_TARGET_ID:
                summary = f"発射シークエンスを完了し、{target.name}への航路を設定した。推進は次のtickから開始する。"
            else:
                summary = f"{target.name}への航路を設定した。推進は次のtickから開始する。"
            observations.append(ObservationFact(type="navigation", value=f"{target.name}への航路を設定", reliability=reliability))
            passive_observations, passive_interpretations = passive_observations_during_move(
                db,
                probe,
                target,
                route_state["remaining_distance"],
                reliability,
            )
            observations.extend(passive_observations)
            interpretations.extend(passive_interpretations)
        else:
            arrived, remaining_before_step, route_state = _advance_toward_target(db, probe, target)
            if nav_state:
                nav_state.progress = float(route_state["progress"])
                nav_state.remaining_distance_km = nav_state.total_distance_km * (1.0 - nav_state.progress)
                nav_state.remaining_distance_pc = nav_state.total_distance_pc * (1.0 - nav_state.progress)
                nav_state.current_speed_m_s = 0.0 if arrived else min(nav_state.cruise_speed_m_s, nav_state.max_speed_m_s)
                nav_state.phase = "arrived" if arrived else {
                    "accelerating": "accelerating",
                    "cruising": "interstellar_cruise",
                    "decelerating": "decelerating",
                    "course_plotted": "system_departure",
                }.get(route_state["route_phase"], nav_state.phase)
                nav_state.drive_mode = "conventional" if arrived or nav_state.phase == "system_departure" else "piano_drive"
                if arrived:
                    nav_state.arrived_at = simulation_datetime
                    nav_state.remaining_distance_km = 0.0
                    nav_state.remaining_distance_pc = 0.0
                    nav_state.progress = 1.0
            drain_factor = max(0.2, probe.velocity / MAX_CRUISE_SPEED)
            probe.energy = max(0, probe.energy - 0.35 * drain_factor)
            if arrived:
                summary = f"{target.name}へ到着し、航行目標を解除した。"
                observations.append(ObservationFact(type="navigation", value=f"{target.name}へ到着", reliability=reliability))
            else:
                phase_label = {"accelerating": "加速", "cruising": "巡航", "decelerating": "減速"}.get(route_state["route_phase"], "巡航")
                summary = f"{target.name}へ向けて{phase_label}中。残距離推定 {route_state['remaining_distance']:.1f}。"
                observations.append(ObservationFact(type="navigation", value=f"{target.name}へ向けた外向き航行を継続", reliability=reliability))
            passive_observations, passive_interpretations = passive_observations_during_move(
                db,
                probe,
                target,
                remaining_before_step,
                reliability,
            )
            observations.extend(passive_observations)
            interpretations.extend(passive_interpretations)
            interpretations.append(Interpretation(hypothesis="外側へ向かう航路は継続可能である", confidence=min(0.86, reliability * 0.78)))

    elif action.action == "observe":
        current = system_detail(db, probe.current_system_id)
        if current and current.bodies:
            for body in current.bodies[:3]:
                related_body_id = related_body_id or body.id
                observations.append(ObservationFact(type="celestial_body", value=f"{body.name} ({body.body_type})を確認", reliability=reliability))
            interpretations.append(Interpretation(hypothesis=f"{current.name}は継続調査に値する安定した観測対象である", confidence=reliability * 0.7))
        probe.energy = max(0, probe.energy - 4)
        probe.storage_used = min(probe.storage_capacity, probe.storage_used + 4)
        summary = "周辺天体の分類・測距観測を実行した。"

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
        summary = f"{signal.id}の周期性と強度変化を記録した。"

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
        interpretations.append(Interpretation(hypothesis="推進剤または修復・冷却材として利用できる可能性", confidence=0.65))
        summary = f"{resource_name}を{quantity:.1f}単位採取し、航行継続用の燃料へ回した。"

    else:
        probe.energy = min(100, probe.energy + 2)
        probe.velocity = 0 if not probe.target_id else probe.velocity

    probe.mission_time += 1
    probe.last_updated_at = utcnow()
    event_payload = {
        "observations": [item.model_dump() for item in observations],
        "interpretations": [item.model_dump() for item in interpretations],
        **mission_time_payload(probe.mission_time - 1),
        "simulation_datetime": simulation_datetime.isoformat().replace("+00:00", "Z"),
        "mission_clock": simulation_datetime.strftime("%Y/%m/%d %H:%M:%S UTC"),
    }
    if nav_state:
        nav_payload = navigation_payload(probe, nav_state)
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
                "route_phase": route_state["route_phase"],
                "route_started_at_tick": route_state["route_started_at_tick"],
                "route_from": route_state["route_from"],
                "route_to": route_state["route_to"],
                "route_distance": route_state["route_distance"],
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
        db.add(
            Discovery(
                probe_id=probe.id,
                event_id=event.id,
                target_id=related_signal_id or related_body_id or probe.target_id,
                observation_type=obs.type,
                value=obs.value,
                reliability=obs.reliability,
                interpretations=[item.model_dump() for item in interpretations],
            )
        )
    return event, observations, interpretations


def _route_state(db: Session, probe: Probe) -> dict | None:
    route_state = _latest_route_state(db, probe)
    if not route_state:
        return None
    return {
        "target_id": route_state["target_id"],
        "target_name": route_state["target_name"],
        "phase": route_state["route_phase"],
        "velocity": float(route_state.get("velocity", probe.velocity)),
        "speed_setting": route_state.get("speed_setting", STANDARD_SPEED_SETTING),
        "progress": float(route_state.get("progress", 0.0)),
        "remaining_distance": float(route_state.get("remaining_distance", 0.0)),
    }


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
    route_phase = event.data.get("route_phase")
    if route_phase == "course_plotted":
        return True, "course_plotted"
    if event.event_type in {"investigate_signal", "collect_resource", "observe"}:
        return True, event.event_type
    if action.validated_action != "move":
        return False, None
    if route_phase == "arrived":
        return True, "arrival"
    if action.target_id == "sys-outer-terminus" and not _phase_logged(db, "outer_lighthouse_detected"):
        return True, "outer_lighthouse_detected"
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


async def _persist_log(
    db: Session,
    llm: LLMClient,
    context: ActionContext,
    action: SimulationAction,
    event: SimulationEvent,
    observations: list[ObservationFact],
    interpretations: list[Interpretation],
) -> ExplorationLog:
    probe = current_probe(db)
    snapshot = _snapshot_with_event_data(probe, event)
    snapshot["log_number"] = db.query(ExplorationLog).count() + 1
    generated = await safe_generate_log(
        llm,
        LogContext(
            action={
                "id": action.id,
                "action": action.validated_action,
                "reason": action.reason,
                "navigation_intent": action.raw_payload.get("navigation_intent"),
                "route_phase": event.data.get("route_phase"),
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
                **mission_time_payload(event.mission_time),
                "simulation_datetime": event.data.get("simulation_datetime"),
                "route_phase": event.data.get("route_phase"),
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
            **mission_time_payload(snapshot["mission_time"]),
        },
        related_event_ids=[event.id],
        related_body_ids=[event.related_body_id] if event.related_body_id else [],
        probe_state_snapshot=snapshot,
        communication_status="nominal" if snapshot["communication"] > 40 else "degraded",
        reliability=generated.reliability,
    )
    db.add(log)
    db.flush()
    return log


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
    log = None
    if log_worthy:
        log = await _persist_log(db, llm, context, action, event, observations, interpretations)
    route = _route_state(db, probe)
    db.commit()
    db.refresh(probe)
    db.refresh(event)
    db.refresh(action)
    if log:
        db.refresh(log)
    return action, event, log, probe, route
