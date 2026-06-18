import math
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta

import pytest

import app.services.clock as clock_service
from app.llm.mock import MockLLMClient
from app.models import Discovery, ExplorationLog, ProbeStateHistory, Signal, SimulationAction, SimulationEvent, StarSystem
from app.repositories.read import logs as read_logs, system_detail
from app.schemas.domain import ProposedAction
from app.services.action_validation import validate_action
from app.services.navigation import begin_navigation, synchronize_navigation
from app.services.reset import reset_world
from app.services.simulation import _display_radius, _main_route_target, apply_action, run_step, run_tick


class InvalidTargetLLMClient(MockLLMClient):
    async def propose_action(self, context):
        return ProposedAction(action="move", target_id="missing-system", reason="invalid test target")


class WaitLLMClient(MockLLMClient):
    async def propose_action(self, context):
        return ProposedAction(action="wait", reason="test wait")


def add_legacy_outer_lighthouse(db, probe) -> StarSystem:
    objective = StarSystem(
        id="sys-outer-terminus",
        universe_id=probe.universe_id,
        name="外縁灯台",
        x=14.0,
        y=-4.0,
        z=7.0,
        display_x=252.0,
        display_y=-72.0,
        display_z=126.0,
        generated_seed="legacy-save",
        resources={},
        details={"object_role": "far_objective", "navigation_order": 99},
    )
    db.add(objective)
    db.flush()
    return objective


def test_move_allowed_when_fuel_is_low(db) -> None:
    probe = reset_world(db)
    probe.fuel = 1
    result = validate_action(db, probe, ProposedAction(action="move", target_id="sys-1", reason="test"))
    assert not result.fallback_used
    assert result.action.action == "move"


def test_move_plots_course_without_instant_motion(db) -> None:
    probe = reset_world(db)
    start_display = (probe.display_x, probe.display_y, probe.display_z)
    target = system_detail(db, "outer-solar-marker")
    assert target is not None
    event, observations, _ = apply_action(db, probe, ProposedAction(action="move", target_id="outer-solar-marker", reason="test"))
    assert probe.current_system_id == "sol"
    assert probe.target_id == "outer-solar-marker"
    assert (probe.display_x, probe.display_y, probe.display_z) == start_display
    assert event.data["route_phase"] == "course_plotted"
    assert probe.velocity == 0
    assert any(obs.type == "passive_sighting" for obs in observations)
    assert any(obs.sighting_level in {"detected", "resolved"} for obs in observations)
    assert any(item["type"] == "passive_sighting" for item in event.data["observations"])


def test_passive_move_observations_do_not_create_discoveries(db) -> None:
    probe = reset_world(db)
    _, observations, _ = apply_action(db, probe, ProposedAction(action="move", target_id="outer-solar-marker", reason="test"))
    passive_count = sum(1 for obs in observations if obs.type.startswith("passive"))
    passive_discoveries = db.query(Discovery).filter(Discovery.observation_type.like("passive%")).count()
    assert passive_count >= 1
    assert passive_discoveries == 0


def test_move_arrives_after_multiple_navigation_steps(db) -> None:
    probe = reset_world(db)
    for _ in range(30):
        apply_action(db, probe, ProposedAction(action="move", target_id="outer-solar-marker", reason="test"))
        if probe.target_id is None:
            break
    assert probe.current_system_id == "sol"
    assert probe.target_id == "outer-solar-marker"


def test_navigation_rejects_target_switch_while_underway(db) -> None:
    probe = reset_world(db)
    apply_action(db, probe, ProposedAction(action="move", target_id="outer-solar-marker", reason="test"))
    result = validate_action(db, probe, ProposedAction(action="move", target_id="sys-1", reason="test"))
    assert result.fallback_used
    assert result.action.action == "wait"


def test_sensor_damage_reduces_observation_reliability(db) -> None:
    probe = reset_world(db)
    probe.sensors = 20
    _, observations, _ = apply_action(db, probe, ProposedAction(action="observe", target_id="sol", reason="test"))
    assert observations
    assert observations[0].reliability == 0.25


def test_storage_full_rejects_observation(db) -> None:
    probe = reset_world(db)
    probe.storage_used = probe.storage_capacity
    result = validate_action(db, probe, ProposedAction(action="observe", target_id="sol", reason="test"))
    assert result.fallback_used


def test_nonexistent_llm_target_falls_back(db) -> None:
    probe = reset_world(db)
    result = validate_action(db, probe, ProposedAction(action="investigate_signal", target_id="missing", reason="test"))
    assert result.fallback_used
    assert result.action.action == "wait"


@pytest.mark.asyncio
async def test_simulation_cycle_persists_state_event_and_log(db) -> None:
    reset_world(db)
    await run_step(db, MockLLMClient())
    assert db.query(SimulationAction).count() == 1
    assert db.query(SimulationEvent).count() == 1
    assert db.query(ExplorationLog).count() == 1
    assert db.query(ProbeStateHistory).count() == 2
    event = db.query(SimulationEvent).first()
    assert any(item["type"].startswith("passive") for item in event.data["observations"])


@pytest.mark.asyncio
async def test_launch_sequence_starts_with_outer_solar_marker(db) -> None:
    probe = reset_world(db)
    action, event, _, probe = await run_step(db, WaitLLMClient())
    assert action.validated_action == "move"
    assert action.target_id == "outer-solar-marker"
    assert probe.target_id == "outer-solar-marker"
    assert "発射シークエンス" in event.summary


@pytest.mark.asyncio
async def test_launch_sequence_is_seed_independent(db) -> None:
    sequence_by_seed = []
    for seed in ["seed-a", "seed-b"]:
        reset_world(db, seed)
        sequence = []
        for _ in range(3):
            action, _, _, _ = await run_step(db, WaitLLMClient())
            sequence.append((action.validated_action, action.target_id))
        sequence_by_seed.append(sequence)
    assert sequence_by_seed[0] == sequence_by_seed[1]


def test_reset_restores_initial_state(db) -> None:
    probe = reset_world(db, "seed-a")
    probe.fuel = 3
    db.commit()
    restored = reset_world(db, "seed-a")
    assert restored.name == "INSOMNIA-07"
    assert restored.fuel == 100
    assert restored.current_system_id == "sol"
    assert restored.current_mission == "太陽系外縁へ向かう段階航行"
    assert restored.mission_clock == "2080/05/02 12:00:00 UTC"
    assert restored.sim_elapsed_seconds == 0
    assert db.query(Signal).count() >= 4


@pytest.mark.asyncio
async def test_mock_log_uses_narrative_navigation_format(db) -> None:
    reset_world(db)
    await run_step(db, MockLLMClient())
    log = db.query(ExplorationLog).first()
    assert "INSOMNIA-07" in log.title
    assert "T+" not in log.title
    assert "# INSOMNIA 航行ログ" in log.body_markdown
    assert "LOG #001" in log.body_markdown
    assert "## 確認済みの事実" not in log.body_markdown
    assert "## OVISの解釈" not in log.body_markdown
    assert "## 記録" not in log.body_markdown
    assert "航路前方" in log.body_markdown


@pytest.mark.asyncio
async def test_immediate_ticks_do_not_advance_user_visible_sim_time_or_position(db, monkeypatch) -> None:
    fixed_now = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(clock_service, "utcnow", lambda: fixed_now)
    probe = reset_world(db)

    _, first_event, _, probe, _ = await run_tick(db, MockLLMClient())
    first_position = (probe.display_x, probe.display_y, probe.display_z)
    _, second_event, _, probe, _ = await run_tick(db, MockLLMClient())

    assert second_event.data["sim_timestamp"] == first_event.data["sim_timestamp"]
    assert second_event.data["mission_clock"] == first_event.data["mission_clock"]
    assert (probe.display_x, probe.display_y, probe.display_z) == first_position
    assert probe.mission_time == 2

    monkeypatch.setattr(clock_service, "utcnow", lambda: fixed_now + timedelta(minutes=3))
    _, third_event, _, probe, _ = await run_tick(db, MockLLMClient())

    assert third_event.data["sim_timestamp"] != first_event.data["sim_timestamp"]
    assert (probe.display_x, probe.display_y, probe.display_z) != first_position


@pytest.mark.asyncio
async def test_tick_does_not_log_course_plotting_or_ordinary_cruise(db) -> None:
    reset_world(db)
    _, first_event, first_log, probe, first_route = await run_tick(db, MockLLMClient())
    assert first_event.data["log_worthy"] is False
    assert first_log is None
    assert first_route is not None
    assert first_route["phase"] == "course_plotted"
    assert first_route["velocity"] == 0
    _, second_event, second_log, probe, second_route = await run_tick(db, MockLLMClient())
    assert second_event.data["log_worthy"] is False
    assert second_log is None
    assert second_route is not None
    assert second_route["phase"] in {"accelerating", "interstellar_cruise", "decelerating", "system_arrival"}
    assert second_route["velocity"] > 0
    assert db.query(ExplorationLog).count() == 0


@pytest.mark.asyncio
async def test_tick_moves_after_high_output_departure(db) -> None:
    probe = reset_world(db)
    initial_display = (probe.display_x, probe.display_y, probe.display_z)
    await run_tick(db, MockLLMClient())
    assert (probe.display_x, probe.display_y, probe.display_z) == initial_display
    _, _, _, probe, route_one = await run_tick(db, MockLLMClient())
    display_after_first_move = (probe.display_x, probe.display_y, probe.display_z)
    _, _, _, probe, route_two = await run_tick(db, MockLLMClient())
    assert display_after_first_move != initial_display
    assert route_one["velocity"] > 0
    assert route_two["velocity"] >= 0


@pytest.mark.asyncio
async def test_tick_arrival_generates_log(db) -> None:
    probe = reset_world(db)
    log_count = 0
    for _ in range(30):
        _, event, log, probe, _ = await run_tick(db, MockLLMClient())
        log_count += 1 if log else 0
    assert probe.current_system_id == "sol"
    assert probe.target_id == "outer-solar-marker"
    assert log_count == db.query(ExplorationLog).count()


@pytest.mark.asyncio
async def test_tick_logs_arrival_that_was_finalized_by_navigation_sync(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    synchronize_navigation(db, probe, state, target, state.eta_datetime + timedelta(seconds=1))

    assert state.phase == "arrived"
    assert db.query(ExplorationLog).count() == 0

    arrival_event = db.query(SimulationEvent).filter(SimulationEvent.event_type == "navigation_arrived").one()
    _, event, log, probe, route = await run_tick(db, MockLLMClient())

    assert event.event_type == "move"
    assert event.data["log_worthy"] is False
    assert log is not None
    assert log.probe_state_snapshot["progress_percent"] == 99
    assert route is not None
    assert route["phase"] == "course_plotted"
    assert probe.current_system_id == "outer-solar-marker"
    logs = db.query(ExplorationLog).order_by(ExplorationLog.id).all()
    assert [item.probe_state_snapshot["progress_percent"] for item in logs] == [1, 50, 99]
    assert [item.title for item in logs] == [
        "INSOMNIA-07 出発後の加速記録",
        "INSOMNIA-07 航路中間域の定期観測",
        "INSOMNIA-07 到着前の減速記録",
    ]
    narrative_fields = [text for item in logs for text in (item.title, item.summary, item.body_markdown)]
    assert all("%" not in text and "進捗" not in text for text in narrative_fields)
    assert all(arrival_event.id not in item.related_event_ids for item in logs)
    assert [item.probe_state_snapshot["progress_percent"] for item in read_logs(db)[:3]] == [99, 50, 1]
    milestone_events = db.query(SimulationEvent).filter(SimulationEvent.event_type == "navigation_progress").all()
    assert all(item.data["observations"] and item.data["interpretations"] for item in milestone_events)
    milestone_text = [
        text
        for item in milestone_events
        for text in (item.summary, item.data["observations"][0]["value"])
    ]
    milestone_actions = db.query(SimulationAction).filter(SimulationAction.id.in_([item.action_id for item in milestone_events])).all()
    assert all("%" not in text and "進捗" not in text for text in [*milestone_text, *[item.reason for item in milestone_actions]])

    await run_tick(db, MockLLMClient())
    assert db.query(ExplorationLog).count() == 3


def test_reset_world_does_not_create_outer_lighthouse(db) -> None:
    reset_world(db, "seed-a")
    assert db.get(StarSystem, "sys-outer-terminus") is None


def test_main_route_prefers_forward_outward_target_over_side_target(db) -> None:
    context = SimpleNamespace(
        probe={"x": 2.0, "y": 0.0, "z": 0.0},
        navigation_targets=[
            {
                "id": "side-outward",
                "visited": False,
                "object_role": "frontier_system",
                "distance_from_origin": 9.0,
                "outward_projection_pc": 0.0,
                "outward_alignment": 0.0,
            },
            {
                "id": "forward-outward",
                "visited": False,
                "object_role": "frontier_system",
                "distance_from_origin": 4.0,
                "outward_projection_pc": 4.0,
                "outward_alignment": 0.99,
            },
        ],
    )

    target = _main_route_target(context)

    assert target is not None
    assert target["id"] == "forward-outward"


@pytest.mark.asyncio
async def test_probe_moves_outward_after_signal_and_local_observation(db) -> None:
    probe = reset_world(db)
    initial_display = (probe.display_x, probe.display_y, probe.display_z)
    await run_step(db, MockLLMClient())
    await run_step(db, MockLLMClient())
    await run_step(db, MockLLMClient())
    db.refresh(probe)
    assert probe.current_system_id in {"sol", "outer-solar-marker"}
    assert probe.target_id in {None, "outer-solar-marker"}
    assert (probe.display_x, probe.display_y, probe.display_z) != initial_display


@pytest.mark.asyncio
async def test_uninvestigated_signal_overrides_llm_wait_at_detour_system(db) -> None:
    probe = reset_world(db)
    probe.current_system_id = "sys-1"
    probe.target_id = None
    probe.mission_time = 8
    db.commit()
    action, _, _, _ = await run_step(db, WaitLLMClient())
    assert action.validated_action == "investigate_signal"
    assert action.target_id is not None
    assert action.raw_payload["navigation_intent"] == "detour_signal"


@pytest.mark.asyncio
async def test_observed_system_returns_to_main_route_instead_of_waiting(db) -> None:
    probe = reset_world(db)
    probe.current_system_id = "sys-2"
    probe.target_id = None
    probe.mission_time = 10
    for signal in system_detail(db, "sys-2").signals:
        signal.investigated = True
    db.add(ProbeStateHistory(probe_id=probe.id, mission_time=10, snapshot={"current_system_id": "sys-2"}))
    db.add(SimulationEvent(probe_id=probe.id, event_type="observe", mission_time=10, summary="test observe", data={}))
    db.commit()
    action, _, _, probe = await run_step(db, WaitLLMClient())
    assert action.validated_action == "move"
    assert action.target_id != "sys-outer-terminus"
    target = db.get(StarSystem, action.target_id)
    assert target is not None
    assert target.details.get("object_role") != "far_objective"
    assert action.raw_payload["navigation_intent"] == "main_route"
    assert probe.target_id == action.target_id


@pytest.mark.asyncio
async def test_frontier_targets_are_added_after_initial_targets_are_consumed(db) -> None:
    probe = reset_world(db)
    for system in db.query(StarSystem).all():
        if system.id != probe.current_system_id:
            db.add(
                ProbeStateHistory(
                    probe_id=probe.id,
                    mission_time=probe.mission_time,
                    snapshot={"current_system_id": system.id},
                )
            )
    db.commit()
    await run_step(db, MockLLMClient())
    frontier_count = db.query(StarSystem).filter(StarSystem.id.like("frontier-%")).count()
    assert frontier_count >= 4


@pytest.mark.asyncio
async def test_outer_terminus_continues_to_outward_frontier(db) -> None:
    probe = reset_world(db)
    objective = add_legacy_outer_lighthouse(db, probe)
    probe.current_system_id = objective.id
    probe.target_id = None
    probe.x, probe.y, probe.z = objective.x, objective.y, objective.z
    probe.display_x, probe.display_y, probe.display_z = objective.display_x, objective.display_y, objective.display_z
    for system in db.query(StarSystem).all():
        db.add(ProbeStateHistory(probe_id=probe.id, mission_time=probe.mission_time, snapshot={"current_system_id": system.id}))
    db.commit()

    action, event, log, probe, route = await run_tick(db, MockLLMClient())

    assert action.validated_action == "move"
    assert probe.target_id is not None
    assert probe.target_id.startswith("frontier-")
    target = db.get(StarSystem, probe.target_id)
    assert target is not None
    probe_radius = math.sqrt(objective.x**2 + objective.y**2 + objective.z**2)
    target_radius = math.sqrt(target.x**2 + target.y**2 + target.z**2)
    dot = (objective.x * target.x + objective.y * target.y + objective.z * target.z) / (probe_radius * target_radius)
    assert target_radius > probe_radius
    assert dot > 0
    assert route is not None
    assert route["phase"] == "course_plotted"


@pytest.mark.asyncio
async def test_long_run_keeps_moving_outward_without_stagnating(db) -> None:
    probe = reset_world(db)
    start_display = (probe.display_x, probe.display_y, probe.display_z)
    wait_streak = 0
    max_wait_streak = 0
    for _ in range(40):
        action, _, _, probe = await run_step(db, MockLLMClient())
        wait_streak = wait_streak + 1 if action.validated_action == "wait" else 0
        max_wait_streak = max(max_wait_streak, wait_streak)
    assert max_wait_streak <= 2
    assert (probe.display_x, probe.display_y, probe.display_z) != start_display


@pytest.mark.asyncio
async def test_long_cruise_logs_include_passive_scenery(db) -> None:
    reset_world(db)
    for _ in range(5):
        _, event, log, _ = await run_step(db, MockLLMClient())
    assert any(item["type"].startswith("passive") for item in event.data["observations"])
    assert "航路前方" in log.body_markdown or "後方視野" in log.body_markdown or "側方星野" in log.body_markdown


@pytest.mark.asyncio
async def test_invalid_llm_move_is_recovered_to_valid_navigation(db) -> None:
    action, _, _, probe = await run_step(db, InvalidTargetLLMClient())
    assert action.status == "accepted"
    assert action.validated_action == "move"
    assert action.target_id == "outer-solar-marker"
    assert probe.mission_time == 1


@pytest.mark.asyncio
async def test_underway_step_keeps_existing_target(db) -> None:
    probe = reset_world(db)
    apply_action(db, probe, ProposedAction(action="move", target_id="outer-solar-marker", reason="test"))
    await run_step(db, MockLLMClient())
    db.refresh(probe)
    assert probe.current_system_id in {"sol", "outer-solar-marker"}
    assert probe.target_id in {"outer-solar-marker", None}
    actions = db.query(SimulationAction).all()
    assert actions[-1].target_id == "outer-solar-marker"


def test_invalid_llm_shape_rejected_by_pydantic() -> None:
    with pytest.raises(Exception):
        ProposedAction.model_validate({"action": "invent_life", "target_id": "x", "reason": "bad"})
