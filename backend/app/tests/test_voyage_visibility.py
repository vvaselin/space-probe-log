from datetime import UTC, datetime

from app.voyage.orbits import AU_KM, add, scale, unit
from app.voyage.visibility import observe, sight
from app.voyage.world import load_world, position_au

T = datetime(2080, 5, 2, 12, tzinfo=UTC)


def test_saturn_from_two_million_km_is_about_six_full_moons() -> None:
    world = load_world()
    saturn_pos = position_au(world, world.get("saturn"), T)
    ship = add(saturn_pos, scale(unit((1.0, 1.0, 0.0)), 2_000_000 / AU_KM))
    seen = sight(world, world.get("saturn"), T, ship, heading=scale(unit((1.0, 1.0, 0.0)), -1))
    assert seen is not None
    assert 5.5 <= seen.size_ratio <= 7.0
    assert seen.size == "満月の約6倍"
    assert seen.stage == "大きく見える"
    assert seen.direction == "真正面"
    assert "環" in seen.look


def test_sun_from_30_au_is_a_dazzling_point() -> None:
    world = load_world()
    seen = sight(world, world.get("sun"), T, ship=(30.0, 0.0, 0.0), heading=(1.0, 0.0, 0.0))
    assert seen is not None
    assert seen.stage == "点"
    assert seen.brightness.startswith("まぶしい")
    assert "満月の約" in seen.brightness  # 海王星付近でも満月の数百倍
    assert seen.direction == "真後ろ"


def test_observe_always_includes_sun_earth_and_next_target_and_limits_others() -> None:
    world = load_world()
    earth = position_au(world, world.get("earth"), T)
    ship = add(earth, (0.0, 0.0, 0.05))
    result = observe(world, T, ship, heading=(1.0, 0.0, 0.0), must_ids=["sun", "earth", "neptune"])
    ids = [s.id for s in result]
    assert ids[:3] == ["sun", "earth", "neptune"]
    assert len(ids) <= 3 + 5
    neptune = result[2]
    assert neptune.visible is False and "見えない" in neptune.brightness


def test_direction_and_phase_words() -> None:
    world = load_world()
    earth = position_au(world, world.get("earth"), T)
    to_sun = unit(scale(earth, -1))
    # 太陽と地球を結ぶ線に直角な位置から見ると半月形になる
    side = unit((-to_sun[1], to_sun[0], 0.0))
    ship = add(earth, scale(side, 100_000 / AU_KM))
    seen = sight(world, world.get("earth"), T, ship, heading=to_sun)
    assert seen is not None
    assert seen.phase is not None and "半分が明るい" in seen.phase
    assert "舷側" in seen.direction


def test_change_from_previous_sighting() -> None:
    world = load_world()
    saturn = world.get("saturn")
    saturn_pos = position_au(world, saturn, T)
    far = sight(world, saturn, T, add(saturn_pos, (0.0, 6_000_000 / AU_KM, 0.0)), heading=(0.0, -1.0, 0.0))
    near = sight(world, saturn, T, add(saturn_pos, (0.0, 2_000_000 / AU_KM, 0.0)), heading=(0.0, -1.0, 0.0), previous=far)
    assert near is not None and near.change == "前回の約3倍の大きさ"
