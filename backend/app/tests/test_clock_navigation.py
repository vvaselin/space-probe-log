from datetime import UTC, datetime, timedelta
from pathlib import Path

import math

import pytest

from app.models import ProbeNavigationState, ProbeStateHistory, SimulationEvent, StarSystem
from app.repositories.read import route_points
from app.schemas.domain import ClockState, SimulationClockUpdate, SimulationSettingsUpdate
from app.services.clock import (
    advance_simulation_clock,
    ensure_simulation_settings,
    reset_simulation_clock,
    update_simulation_clock,
    update_simulation_settings,
)
from app.services.navigation import begin_navigation, synchronize_navigation
from app.services.probe_spec import probe_specification
from app.services.reset import reset_world
from app.services.simulation import ensure_frontier_targets


def test_360x_advances_one_real_minute_to_six_sim_hours(db) -> None:
    reset_simulation_clock(db, real_now=datetime(2026, 1, 1, tzinfo=UTC))
    clock, _ = advance_simulation_clock(db, real_now=datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    assert clock.simulation_datetime == datetime(2080, 5, 2, 18, 0, tzinfo=UTC)


def test_1440x_advances_one_real_minute_to_one_sim_day(db) -> None:
    reset_simulation_clock(db, real_now=datetime(2026, 1, 1, tzinfo=UTC))
    update_simulation_clock(db, SimulationClockUpdate(time_scale=1440), real_now=datetime(2026, 1, 1, tzinfo=UTC))
    clock, _ = advance_simulation_clock(db, real_now=datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    assert clock.simulation_datetime == datetime(2080, 5, 3, 12, 0, tzinfo=UTC)


def test_pause_resume_does_not_count_paused_real_elapsed(db) -> None:
    reset_simulation_clock(db, real_now=datetime(2026, 1, 1, tzinfo=UTC))
    paused, _ = update_simulation_clock(
        db,
        SimulationClockUpdate(clock_state=ClockState.paused),
        real_now=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
    )
    paused_time = paused.simulation_datetime
    resumed, _ = update_simulation_clock(
        db,
        SimulationClockUpdate(clock_state=ClockState.running),
        real_now=datetime(2026, 1, 1, 1, 1, tzinfo=UTC),
    )
    assert resumed.simulation_datetime == paused_time
    advanced, _ = advance_simulation_clock(db, real_now=datetime(2026, 1, 1, 1, 2, tzinfo=UTC))
    assert advanced.simulation_datetime == paused_time + timedelta(hours=6)


def test_time_scale_change_first_commits_current_time(db) -> None:
    reset_simulation_clock(db, real_now=datetime(2026, 1, 1, tzinfo=UTC))
    changed, _ = update_simulation_clock(db, SimulationClockUpdate(time_scale=1440), real_now=datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    assert changed.simulation_datetime == datetime(2080, 5, 2, 18, 0, tzinfo=UTC)
    advanced, _ = advance_simulation_clock(db, real_now=datetime(2026, 1, 1, 0, 2, tzinfo=UTC))
    assert advanced.simulation_datetime == datetime(2080, 5, 3, 18, 0, tzinfo=UTC)


def test_offline_cap_limits_real_elapsed(db) -> None:
    reset_simulation_clock(db, real_now=datetime(2026, 1, 1, tzinfo=UTC))
    update_simulation_settings(db, SimulationSettingsUpdate(max_offline_elapsed_seconds=60))
    clock, applied = advance_simulation_clock(db, real_now=datetime(2026, 1, 2, tzinfo=UTC))
    assert applied == 60
    assert clock.simulation_datetime == datetime(2080, 5, 2, 18, 0, tzinfo=UTC)


def test_navigation_eta_uses_physical_distance_and_cruise_speed(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    assert state.total_distance_pc > 0
    assert state.total_distance_km > 0
    assert state.eta_datetime > state.started_at
    assert state.cruise_speed_m_s == 23_983_396.64


def test_probe_specification_length_is_eighteen_meters() -> None:
    assert probe_specification().length_m == 18


def test_reset_clears_navigation_and_route_history_to_initial_position(db) -> None:
    probe = reset_world(db, "reset-route")
    target = db.get(StarSystem, "outer-solar-marker")
    begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    db.add(ProbeStateHistory(probe_id=probe.id, mission_time=99, snapshot={"display_x": 99.0, "display_y": 0.0, "display_z": 0.0}))
    db.commit()

    restored = reset_world(db, "reset-route")

    assert db.query(ProbeNavigationState).count() == 0
    assert db.query(ProbeStateHistory).count() == 1
    assert route_points(db, restored) == [{"x": restored.display_x, "y": restored.display_y, "z": restored.display_z}]
    assert restored.current_system_id == "sol"
    assert restored.target_id is None


def test_arrival_event_is_idempotent_when_time_jumps_forward(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    future = state.eta_datetime + timedelta(days=1)
    synchronize_navigation(db, probe, state, target, future)
    synchronize_navigation(db, probe, state, target, future + timedelta(days=1))
    count = db.query(SimulationEvent).filter(SimulationEvent.event_type == "navigation_arrived").count()
    assert count == 1


def test_arrived_navigation_state_does_not_reactivate_on_sync(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    synchronize_navigation(db, probe, state, target, state.eta_datetime + timedelta(hours=1))
    assert state.phase == "arrived"
    assert probe.target_id is None

    synchronize_navigation(db, probe, state, target, state.started_at + timedelta(hours=1))

    assert state.phase == "arrived"
    assert state.progress == 1.0
    assert state.remaining_distance_km == 0.0
    assert probe.current_system_id == "outer-solar-marker"
    assert probe.target_id is None


def test_route_payload_includes_current_probe_point_while_underway(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    synchronize_navigation(db, probe, state, target, state.started_at + timedelta(days=3))

    points = route_points(db, probe)

    assert len(points) >= 2
    assert points[-1] == pytest.approx({"x": probe.display_x, "y": probe.display_y, "z": probe.display_z})


def test_navigation_progress_is_monotonic_and_uses_original_origin(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    schedule = state.schedule
    origin = schedule["origin_display_position"]
    destination = schedule["destination_display_position"]

    synchronize_navigation(db, probe, state, target, state.started_at + timedelta(days=1))
    first_progress = state.progress
    first_expected_x = origin["x"] + (destination["x"] - origin["x"]) * first_progress
    assert probe.display_x == pytest.approx(first_expected_x)

    synchronize_navigation(db, probe, state, target, state.started_at + timedelta(days=2))
    second_progress = state.progress
    second_expected_x = origin["x"] + (destination["x"] - origin["x"]) * second_progress
    assert second_progress > first_progress
    assert probe.display_x == pytest.approx(second_expected_x)


def test_piano_drive_is_not_used_inside_system_boundary(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    synchronize_navigation(db, probe, state, target, state.started_at + timedelta(hours=1))
    assert state.phase == "system_departure"
    assert state.drive_mode == "conventional"


def test_frontier_after_outer_lighthouse_is_physically_outward(db) -> None:
    probe = reset_world(db, "outer-frontier")
    objective = db.get(StarSystem, "sys-outer-terminus")
    assert objective is not None
    probe.current_system_id = objective.id
    probe.x, probe.y, probe.z = objective.x, objective.y, objective.z
    probe.display_x, probe.display_y, probe.display_z = objective.display_x, objective.display_y, objective.display_z
    probe.target_id = None
    for system in db.query(StarSystem).all():
        db.add(ProbeStateHistory(probe_id=probe.id, mission_time=probe.mission_time, snapshot={"current_system_id": system.id}))
    db.commit()

    ensure_frontier_targets(db, probe, min_unvisited=6)

    probe_radius = math.sqrt(probe.x**2 + probe.y**2 + probe.z**2)
    frontier = db.query(StarSystem).filter(StarSystem.id.like("frontier-%")).all()
    assert len(frontier) >= 6
    for system in frontier:
        system_radius = math.sqrt(system.x**2 + system.y**2 + system.z**2)
        dot = (probe.x * system.x + probe.y * system.y + probe.z * system.z) / (probe_radius * system_radius)
        assert system_radius > probe_radius
        assert dot > 0


def test_old_probe_names_are_absent_from_primary_content() -> None:
    root = Path(__file__).resolve().parents[3]
    paths = [
        root / "README.md",
        root / "backend" / "app" / "prompts" / "probe_profile.md",
        root / "backend" / "app" / "prompts" / "action_policy.md",
        root / "backend" / "app" / "prompts" / "log_writer_style.md",
        root / "frontend" / "app.vue",
    ]
    content = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "AURORA-7" not in content
    assert "probe-aurora" not in content
