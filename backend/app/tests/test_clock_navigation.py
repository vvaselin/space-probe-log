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
from app.services.navigation import begin_navigation, navigation_payload, synchronize_navigation
from app.services.probe_spec import probe_specification
from app.services.reset import reset_world
from app.services.simulation import ensure_frontier_targets


def test_360x_advances_one_real_minute_to_six_sim_hours(db) -> None:
    reset_simulation_clock(db, real_now=datetime(2026, 1, 1, tzinfo=UTC))
    update_simulation_clock(db, SimulationClockUpdate(time_scale=360), real_now=datetime(2026, 1, 1, tzinfo=UTC))
    clock, _ = advance_simulation_clock(db, real_now=datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    assert clock.simulation_datetime == datetime(2080, 5, 2, 18, 0, tzinfo=UTC)


def test_1440x_advances_one_real_minute_to_one_sim_day(db) -> None:
    reset_simulation_clock(db, real_now=datetime(2026, 1, 1, tzinfo=UTC))
    update_simulation_clock(db, SimulationClockUpdate(time_scale=1440), real_now=datetime(2026, 1, 1, tzinfo=UTC))
    clock, _ = advance_simulation_clock(db, real_now=datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    assert clock.simulation_datetime == datetime(2080, 5, 3, 12, 0, tzinfo=UTC)


def test_pause_resume_does_not_count_paused_real_elapsed(db) -> None:
    reset_simulation_clock(db, real_now=datetime(2026, 1, 1, tzinfo=UTC))
    update_simulation_clock(db, SimulationClockUpdate(time_scale=360), real_now=datetime(2026, 1, 1, tzinfo=UTC))
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
    update_simulation_clock(db, SimulationClockUpdate(time_scale=360), real_now=datetime(2026, 1, 1, tzinfo=UTC))
    changed, _ = update_simulation_clock(db, SimulationClockUpdate(time_scale=1440), real_now=datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    assert changed.simulation_datetime == datetime(2080, 5, 2, 18, 0, tzinfo=UTC)
    advanced, _ = advance_simulation_clock(db, real_now=datetime(2026, 1, 1, 0, 2, tzinfo=UTC))
    assert advanced.simulation_datetime == datetime(2080, 5, 3, 18, 0, tzinfo=UTC)


def test_offline_cap_limits_real_elapsed(db) -> None:
    reset_simulation_clock(db, real_now=datetime(2026, 1, 1, tzinfo=UTC))
    update_simulation_clock(db, SimulationClockUpdate(time_scale=360), real_now=datetime(2026, 1, 1, tzinfo=UTC))
    update_simulation_settings(db, SimulationSettingsUpdate(max_offline_elapsed_seconds=60))
    clock, applied = advance_simulation_clock(db, real_now=datetime(2026, 1, 2, tzinfo=UTC))
    assert applied == 60
    assert clock.simulation_datetime == datetime(2080, 5, 2, 18, 0, tzinfo=UTC)


def test_large_time_scale_clamps_instead_of_overflowing(db) -> None:
    clock = reset_simulation_clock(db, real_now=datetime(2026, 1, 1, tzinfo=UTC))
    clock.simulation_datetime = datetime(9999, 12, 31, 23, 59, 58, tzinfo=UTC)
    clock.time_scale = 5_000_000
    clock.last_real_datetime = datetime(2026, 1, 1, tzinfo=UTC)

    advanced, applied = advance_simulation_clock(db, real_now=datetime(2026, 1, 1, 0, 1, tzinfo=UTC))

    assert advanced.simulation_datetime == datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert advanced.clock_state == ClockState.paused.value
    assert applied == pytest.approx(1 / 5_000_000)


def test_default_time_scale_presets_include_realtime(db) -> None:
    settings = ensure_simulation_settings(db)

    assert settings.default_time_scale == 500_000.0
    assert settings.time_scale_presets == [1.0, 10_000.0, 100_000.0, 500_000.0]


def test_navigation_eta_uses_physical_distance_and_cruise_speed(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    assert state.total_distance_pc > 0
    assert state.total_distance_km > 0
    assert state.eta_datetime > state.started_at
    assert state.cruise_speed_m_s == pytest.approx(239_833_966.4)


def test_existing_navigation_state_upgrades_to_current_piano_drive_output(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    state.cruise_speed_m_s = 23_983_396.64
    state.max_speed_m_s = 35_975_094.96
    state.schedule = {
        **state.schedule,
        **{
            key: value * 10
            for key, value in state.schedule.items()
            if key.endswith("_s") or key.endswith("_seconds")
        },
    }
    state.eta_datetime = state.started_at + timedelta(seconds=state.schedule["arrival_end_s"])
    old_eta = state.eta_datetime

    synchronize_navigation(db, probe, state, target, state.started_at + timedelta(days=1))

    assert state.cruise_speed_m_s == pytest.approx(239_833_966.4)
    assert state.max_speed_m_s == pytest.approx(239_833_966.4)
    assert state.schedule["drive_profile"] == "instant_high_output_v1"
    assert state.eta_datetime < old_eta


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


def test_navigation_position_depends_on_simulation_time_not_tick_count(db) -> None:
    probe = reset_world(db, "large-step-navigation")
    target = db.get(StarSystem, "outer-solar-marker")
    start = datetime(2080, 5, 2, 12, tzinfo=UTC)
    state = begin_navigation(db, probe, target, start)
    sample_time = start + timedelta(days=4)

    synchronize_navigation(db, probe, state, target, sample_time)
    first_position = (probe.display_x, probe.display_y, probe.display_z)
    for _ in range(5):
        synchronize_navigation(db, probe, state, target, sample_time)

    assert (probe.display_x, probe.display_y, probe.display_z) == pytest.approx(first_position)


def test_navigation_large_step_matches_many_small_steps(db) -> None:
    probe = reset_world(db, "large-step-navigation")
    target = db.get(StarSystem, "outer-solar-marker")
    start = datetime(2080, 5, 2, 12, tzinfo=UTC)
    state = begin_navigation(db, probe, target, start)
    sample_time = start + timedelta(days=9)
    synchronize_navigation(db, probe, state, target, sample_time)
    large_step_position = (probe.display_x, probe.display_y, probe.display_z)

    probe = reset_world(db, "large-step-navigation")
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, start)
    for day in range(1, 10):
        synchronize_navigation(db, probe, state, target, start + timedelta(days=day))

    assert (probe.display_x, probe.display_y, probe.display_z) == pytest.approx(large_step_position)


def test_navigation_speed_changes_by_phase(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    schedule = state.schedule

    assert schedule["system_departure_end_s"] == 5 * 60
    assert schedule["acceleration_seconds"] <= 30 * 60

    accel_start = state.started_at + timedelta(seconds=schedule["system_departure_end_s"] + schedule["acceleration_seconds"] * 0.25)
    accel_later = state.started_at + timedelta(seconds=schedule["system_departure_end_s"] + schedule["acceleration_seconds"] * 0.75)
    cruise_time = state.started_at + timedelta(seconds=schedule["acceleration_end_s"] + 60)
    decel_start = state.started_at + timedelta(seconds=schedule["cruise_end_s"] + schedule["deceleration_seconds"] * 0.25)
    decel_later = state.started_at + timedelta(seconds=schedule["cruise_end_s"] + schedule["deceleration_seconds"] * 0.75)

    synchronize_navigation(db, probe, state, target, accel_start)
    first_accel_speed = state.current_speed_m_s
    synchronize_navigation(db, probe, state, target, accel_later)
    assert state.current_speed_m_s > first_accel_speed

    synchronize_navigation(db, probe, state, target, cruise_time)
    assert state.current_speed_m_s == pytest.approx(state.cruise_speed_m_s)

    synchronize_navigation(db, probe, state, target, decel_start)
    first_decel_speed = state.current_speed_m_s
    synchronize_navigation(db, probe, state, target, decel_later)
    assert state.current_speed_m_s < first_decel_speed


def test_arrival_updates_probe_and_navigation_atomically(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))

    synchronize_navigation(db, probe, state, target, state.eta_datetime + timedelta(seconds=1))

    assert state.phase == "arrived"
    assert state.progress == 1.0
    assert state.current_speed_m_s == 0.0
    assert probe.current_system_id == target.id
    assert probe.target_id is None
    assert "到着" in probe.current_mission
    assert "進行率" not in probe.current_mission
    assert (probe.display_x, probe.display_y, probe.display_z) == pytest.approx((target.display_x, target.display_y, target.display_z))


def test_navigation_payloads_share_authoritative_display_position(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    synchronize_navigation(db, probe, state, target, state.started_at + timedelta(days=5))

    sampled_at = state.started_at + timedelta(days=5)
    navigation = navigation_payload(probe, state, sampled_at)
    map_probe = {
        "display_position": {"x": probe.display_x, "y": probe.display_y, "z": probe.display_z},
        "navigation": navigation,
    }

    assert map_probe["display_position"] == navigation["display_position"]
    assert navigation["display_velocity"].keys() == {"x", "y", "z"}
    assert navigation["sampled_at"] == sampled_at.isoformat().replace("+00:00", "Z")


def test_piano_drive_is_not_used_inside_system_boundary(db) -> None:
    probe = reset_world(db)
    target = db.get(StarSystem, "outer-solar-marker")
    state = begin_navigation(db, probe, target, datetime(2080, 5, 2, 12, tzinfo=UTC))
    synchronize_navigation(db, probe, state, target, state.started_at + timedelta(minutes=1))
    assert state.phase == "system_departure"
    assert state.drive_mode == "conventional"

    synchronize_navigation(db, probe, state, target, state.started_at + timedelta(minutes=7))
    assert state.phase in {"accelerating", "interstellar_cruise"}
    assert state.drive_mode == "piano_drive"


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
