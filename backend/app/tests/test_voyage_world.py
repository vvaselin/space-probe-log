from datetime import UTC, datetime, timedelta

import pytest

from app.voyage.orbits import AU_KM, J2000, norm, sub
from app.voyage.world import load_world, position_au

START = datetime(2080, 5, 2, 12, tzinfo=UTC)
CENTURY = [START + timedelta(days=37 * k) for k in range(1000)]  # 2080〜2180年


def _r(dest_id: str, t: datetime) -> float:
    world = load_world()
    return norm(position_au(world, world.get(dest_id), t))


def test_positions_change_with_time() -> None:
    world = load_world()
    for dest in world.destinations.values():
        if dest.id == "sun":
            continue
        before = position_au(world, dest, START)
        after = position_au(world, dest, START + timedelta(days=30))
        assert norm(sub(before, after)) > 0, dest.id


def test_earth_stays_near_1_au() -> None:
    assert all(0.98 <= _r("earth", t) <= 1.02 for t in CENTURY)


def test_jupiter_stays_between_4_9_and_5_5_au() -> None:
    assert all(4.9 <= _r("jupiter", t) <= 5.5 for t in CENTURY)


def test_earth_at_j2000_matches_known_position() -> None:
    world = load_world()
    x, y, z = position_au(world, world.get("earth"), J2000)
    assert x == pytest.approx(-0.177, abs=0.01)
    assert y == pytest.approx(0.967, abs=0.01)
    assert z == pytest.approx(0.0, abs=0.001)


def test_moons_keep_their_orbit_radius_around_parent() -> None:
    world = load_world()
    for dest in world.destinations.values():
        if dest.subtype != "moon":
            continue
        parent = world.get(dest.parent_id or "")
        for t in (START, START + timedelta(days=3.3)):
            distance_km = norm(sub(position_au(world, dest, t), position_au(world, parent, t))) * AU_KM
            assert distance_km == pytest.approx(dest.orbit.orbit_radius_km, rel=1e-6), dest.id


def test_small_bodies_are_at_plausible_distances_in_2080() -> None:
    expected = {"ceres": (2.5, 3.0), "pluto": (29, 50), "eris": (37, 98), "sedna": (75, 78)}
    for dest_id, (low, high) in expected.items():
        assert low <= _r(dest_id, START) <= high, dest_id


def test_every_destination_has_visual_data() -> None:
    world = load_world()
    assert len(world.destinations) >= 20
    for dest in world.destinations.values():
        assert dest.visual.colors and dest.visual.pattern, dest.id
