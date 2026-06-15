import math
import random

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.llm.client import LLMClient
from app.llm.mock import MockLLMClient
from app.models import (
    Discovery,
    ExplorationLog,
    Probe,
    ProbeStateHistory,
    ResourceInventory,
    SimulationAction,
    SimulationEvent,
    StarSystem,
)
from app.repositories.read import current_probe, signal_by_id, system_detail, systems
from app.repositories.settings import get_prompt_settings
from app.schemas.domain import (
    ActionContext,
    GeneratedLog,
    Interpretation,
    LogContext,
    ObservationFact,
    ProposedAction,
)
from app.services.action_validation import validate_action
from app.services.reset import reset_world
from app.services.snapshots import probe_snapshot
from app.world.generator import stable_seed

DISPLAY_STEP_DISTANCE = 13.0
ARRIVAL_DISTANCE = 2.4


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(a, b, strict=True)))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _display_radius(point: tuple[float, float, float]) -> float:
    return math.sqrt(point[0] ** 2 + point[1] ** 2 + point[2] ** 2)


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
    if probe.name != "INSOMNIA-07":
        probe.name = "INSOMNIA-07"
        db.commit()
        db.refresh(probe)
    return probe


def _visited_system_ids(db: Session, probe: Probe) -> set[str]:
    return {
        item.snapshot.get("current_system_id")
        for item in db.scalars(select(ProbeStateHistory).where(ProbeStateHistory.probe_id == probe.id)).all()
        if item.snapshot.get("current_system_id")
    }


def _navigation_score(probe: Probe, item: StarSystem, visited: set[str]) -> tuple[int, float, int, str]:
    probe_radius = _display_radius((probe.display_x, probe.display_y, probe.display_z))
    item_radius = _display_radius((item.display_x, item.display_y, item.display_z))
    outward_penalty = 0 if item_radius >= probe_radius + 0.5 else 1
    visited_penalty = 1 if item.id in visited else 0
    order = int(item.details.get("navigation_order", 50))
    return (visited_penalty, outward_penalty, order, item.id)


def action_context(db: Session, probe: Probe) -> ActionContext:
    current = system_detail(db, probe.current_system_id)
    prompt_settings = get_prompt_settings(db)
    visible_signals = []
    if not probe.target_id and current:
        visible_signals = [
            {"id": signal.id, "kind": signal.kind, "strength": signal.strength, "details": signal.details}
            for signal in current.signals
            if not signal.investigated
        ]
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
        probe=probe_snapshot(probe),
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
    if probe["mission_time"] < 2 or probe["fuel"] < 12 or probe["propulsion"] < 25:
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
        arrived, remaining_before_step = _advance_toward_target(db, probe, target)
        probe.fuel = max(0, probe.fuel - 4)
        probe.energy = max(0, probe.energy - 3)
        if arrived:
            summary = f"{target.name} へ到着し、航行目標を解除した。"
        elif previous_target == target.id:
            summary = f"{target.name} へ向けて外縁航路を維持した。残距離指標 {remaining_before_step:.1f}。"
        else:
            summary = f"{target.name} への外向き航行を開始した。太陽系離脱軌道へ段階的に移行する。"
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
        probe.energy = max(0, probe.energy - 6)
        probe.storage_used = min(probe.storage_capacity, probe.storage_used + 3)
        observations.append(ObservationFact(type="resource", value=f"{resource_name} を {quantity:.1f} 単位採取", reliability=0.9))
        interpretations.append(Interpretation(hypothesis="修復・冷却材として利用できる可能性", confidence=0.65))
        summary = f"{resource_name} を {quantity:.1f} 単位採取した。"
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


async def run_step(db: Session, llm: LLMClient) -> tuple[SimulationAction, SimulationEvent, ExplorationLog, Probe]:
    probe = ensure_probe(db)
    context = action_context(db, probe)
    proposed = ProposedAction(action="move", target_id=probe.target_id, reason="航行中のため既定目標へ向けて進む") if probe.target_id else await safe_propose(llm, context)
    proposed = avoid_stagnation(context, proposed)
    validation = validate_action(db, probe, proposed)
    action = SimulationAction(
        probe_id=probe.id,
        proposed_action=proposed.action,
        validated_action=validation.action.action,
        target_id=validation.action.target_id,
        reason=validation.action.reason,
        status=validation.status,
        validation_message=validation.message,
        raw_payload=proposed.model_dump(),
    )
    db.add(action)
    db.flush()
    event, observations, interpretations = apply_action(db, probe, validation.action)
    event.action_id = action.id
    snapshot = probe_snapshot(probe)
    db.add(ProbeStateHistory(probe_id=probe.id, mission_time=probe.mission_time, snapshot=snapshot))
    generated = await safe_generate_log(
        llm,
        LogContext(
            action={"id": action.id, "action": action.validated_action, "reason": action.reason},
            event={"id": event.id, "event_type": event.event_type, "summary": event.summary},
            probe_snapshot=snapshot,
            observations=observations,
            interpretations=interpretations,
            prompt_settings=context.prompt_settings,
        ),
    )
    body_markdown = generated.body_markdown
    if not body_markdown.lstrip().startswith("---------------------"):
        body_markdown = f"{log_header(snapshot, event)}\n\n{body_markdown}"
    log = ExplorationLog(
        title=generated.title,
        summary=generated.summary,
        body_markdown=body_markdown,
        mission_time=probe.mission_time,
        probe_position={"x": probe.x, "y": probe.y, "z": probe.z, "system_id": probe.current_system_id, "target_id": probe.target_id},
        related_event_ids=[event.id],
        related_body_ids=[event.related_body_id] if event.related_body_id else [],
        probe_state_snapshot=snapshot,
        communication_status="nominal" if probe.communication > 40 else "degraded",
        reliability=generated.reliability,
    )
    db.add(log)
    db.commit()
    db.refresh(probe)
    db.refresh(log)
    db.refresh(event)
    db.refresh(action)
    return action, event, log, probe
