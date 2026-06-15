import pytest

from app.llm.mock import MockLLMClient
from app.models import Discovery, ExplorationLog, ProbeStateHistory, Signal, SimulationAction, SimulationEvent
from app.repositories.read import system_detail
from app.schemas.domain import ProposedAction
from app.services.action_validation import validate_action
from app.services.reset import reset_world
from app.services.simulation import apply_action, run_step


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
    apply_action(db, probe, ProposedAction(action="move", target_id="outer-solar-marker", reason="test"))
    assert probe.current_system_id == "sol"
    assert probe.target_id == "outer-solar-marker"
    assert (probe.display_x, probe.display_y, probe.display_z) != (target.display_x, target.display_y, target.display_z)


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
    assert db.query(Discovery).count() >= 1


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


@pytest.mark.asyncio
async def test_probe_moves_outward_after_signal_and_local_observation(db) -> None:
    probe = reset_world(db)
    await run_step(db, MockLLMClient())
    await run_step(db, MockLLMClient())
    await run_step(db, MockLLMClient())
    db.refresh(probe)
    assert probe.target_id == "outer-solar-marker"
    assert probe.display_x > 7.1


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
