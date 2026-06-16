import pytest

from app.llm.mock import MockLLMClient
from app.models import Discovery, ExplorationLog, ProbeStateHistory, Signal, SimulationAction, SimulationEvent, StarSystem
from app.repositories.read import system_detail
from app.schemas.domain import ProposedAction
from app.services.action_validation import validate_action
from app.services.reset import reset_world
from app.services.simulation import _display_radius, apply_action, run_step


class InvalidTargetLLMClient(MockLLMClient):
    async def propose_action(self, context):
        return ProposedAction(action="move", target_id="missing-system", reason="invalid test target")


class WaitLLMClient(MockLLMClient):
    async def propose_action(self, context):
        return ProposedAction(action="wait", reason="test wait")


def test_move_rejected_when_fuel_is_low(db) -> None:
    probe = reset_world(db)
    probe.fuel = 1
    result = validate_action(db, probe, ProposedAction(action="move", target_id="sys-1", reason="test"))
    assert result.fallback_used
    assert result.action.action == "wait"


def test_move_starts_navigation_without_instant_arrival(db) -> None:
    probe = reset_world(db)
    target = system_detail(db, "outer-solar-marker")
    assert target is not None
    event, observations, _ = apply_action(db, probe, ProposedAction(action="move", target_id="outer-solar-marker", reason="test"))
    assert probe.current_system_id == "sol"
    assert probe.target_id == "outer-solar-marker"
    assert (probe.display_x, probe.display_y, probe.display_z) != (target.display_x, target.display_y, target.display_z)
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
    for _ in range(8):
        apply_action(db, probe, ProposedAction(action="move", target_id="outer-solar-marker", reason="test"))
        if probe.target_id is None:
            break
    assert probe.current_system_id == "outer-solar-marker"
    assert probe.target_id is None


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
    assert db.query(Signal).count() >= 4


@pytest.mark.asyncio
async def test_mock_log_separates_facts_and_ovis_interpretation(db) -> None:
    reset_world(db)
    await run_step(db, MockLLMClient())
    log = db.query(ExplorationLog).first()
    assert "INSOMNIA-07" in log.title
    assert "INSOMNIA-07 航行ログ" in log.body_markdown
    assert "LOG #001" in log.body_markdown
    assert "## 確認済みの事実" in log.body_markdown
    assert "## OVISの解釈" in log.body_markdown
    assert "## 記録" in log.body_markdown
    assert "航路前方" in log.body_markdown


@pytest.mark.asyncio
async def test_probe_moves_outward_after_signal_and_local_observation(db) -> None:
    probe = reset_world(db)
    initial_radius = math.sqrt(probe.display_x ** 2 + probe.display_y ** 2 + probe.display_z ** 2)
    await run_step(db, MockLLMClient())
    await run_step(db, MockLLMClient())
    await run_step(db, MockLLMClient())
    db.refresh(probe)
    assert probe.current_system_id in {"sol", "outer-solar-marker"}
    assert probe.target_id in {None, "outer-solar-marker", "sys-outer-terminus"}
    assert math.sqrt(probe.display_x ** 2 + probe.display_y ** 2 + probe.display_z ** 2) > initial_radius


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
    assert action.target_id == "sys-outer-terminus"
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
async def test_long_run_keeps_moving_outward_without_stagnating(db) -> None:
    probe = reset_world(db)
    start_radius = _display_radius((probe.display_x, probe.display_y, probe.display_z))
    wait_streak = 0
    max_wait_streak = 0
    for _ in range(40):
        action, _, _, probe = await run_step(db, MockLLMClient())
        wait_streak = wait_streak + 1 if action.validated_action == "wait" else 0
        max_wait_streak = max(max_wait_streak, wait_streak)
    end_radius = _display_radius((probe.display_x, probe.display_y, probe.display_z))
    assert max_wait_streak <= 2
    assert end_radius > start_radius


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
