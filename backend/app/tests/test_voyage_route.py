from datetime import timedelta
from typing import Any

import pytest

from app.voyage.cli import mock_chooser, simulate_route
from app.voyage.motion import cruise_speed_km_s, make_profile
from app.voyage.orbits import AU_KM, norm, sub
from app.voyage.route import INWARD_LIMIT, START_AT, Candidate, Choice, Leg, plan_leg, standoff_au
from app.voyage.world import load_world, position_au


@pytest.fixture(scope="module")
def legs() -> list[Leg]:
    import asyncio

    return asyncio.run(simulate_route(100, START_AT, mock_chooser("test-seed")))


def test_cruise_speed_follows_the_table() -> None:
    assert cruise_speed_km_s(1.0) == 200
    assert cruise_speed_km_s(5.0) == pytest.approx(1_000)
    assert cruise_speed_km_s(30.0) == pytest.approx(3_000)
    assert 1_000 < cruise_speed_km_s(10.0) < 3_000


def test_profile_is_continuous_and_reaches_the_end() -> None:
    profile = make_profile((1.0, 0.0, 0.0), (2.0, 0.0, 0.0), START_AT, 200.0)
    assert profile.position_at(profile.depart_at) == (1.0, 0.0, 0.0)
    assert profile.position_at(profile.arrive_at) == pytest.approx((2.0, 0.0, 0.0))
    steps = [profile.depart_at + timedelta(seconds=profile.duration_s * i / 50) for i in range(51)]
    travelled = [profile.travelled_km(t) for t in steps]
    assert travelled == sorted(travelled)
    assert max(profile.speed_at(t) for t in steps) == pytest.approx(200.0)
    assert [profile.state_at(t) for t in (steps[0], steps[1], steps[25], steps[49], steps[50])] == [
        "stopped",
        "accelerating",
        "cruising",
        "decelerating",
        "stopped",
    ]
    assert profile.duration_s / 86_400 == pytest.approx(AU_KM / 200 / 86_400 + profile.accel_s / 86_400, rel=1e-6)


def test_moving_target_is_met_at_arrival(legs: list[Leg]) -> None:
    world = load_world()
    for leg in legs:
        at_arrival = position_au(world, leg.target, leg.profile.arrive_at)
        miss_km = norm(sub(at_arrival, leg.profile.destination_au)) * AU_KM
        assert miss_km == pytest.approx(standoff_au(leg.target) * AU_KM, rel=0.05), leg.target.id


def test_route_never_goes_back_inside(legs: list[Leg]) -> None:
    assert len(legs) >= 15
    for leg in legs:
        if leg.leg_kind != "tour":
            assert norm(leg.profile.destination_au) >= INWARD_LIMIT * norm(leg.profile.origin_au), leg.index


def test_candidates_stay_between_08_and_3_times_the_current_distance(legs: list[Leg]) -> None:
    for leg in legs:
        p = leg.planning
        for c in p.candidates:
            if c.leg_kind != "tour":
                assert INWARD_LIMIT * p.current_r_au <= c.r_au <= 3 * p.current_r_au, (leg.index, c.id)


def test_legs_chain_without_gaps(legs: list[Leg]) -> None:
    for before, after in zip(legs, legs[1:]):
        assert after.profile.origin_au == before.profile.destination_au
        assert after.profile.depart_at == before.profile.arrive_at
        assert after.origin_id == before.target.id


def test_planets_are_visited_in_order_and_moons_are_toured_first(legs: list[Leg]) -> None:
    world = load_world()
    planets = [leg for leg in legs if leg.target.subtype == "planet"]
    order = ["mars", "jupiter", "saturn", "uranus", "neptune"]
    visited = [p.target.id for p in planets]
    assert visited == [pid for pid in order if pid in visited]
    assert {"jupiter", "saturn", "uranus"} <= set(visited)
    radii = [norm(p.profile.destination_au) for p in planets]
    assert radii == sorted(radii)
    for i, leg in enumerate(legs):
        moons = {m.id for m in world.children(leg.target.id)}
        if moons:
            following = legs[i + 1 : i + 1 + len(moons)]
            assert {f.target.id for f in following} == moons
            assert all(f.leg_kind == "tour" for f in following)


def test_scenes_are_ordered_inside_each_leg(legs: list[Leg]) -> None:
    for leg in legs:
        assert leg.scenes[0].kind == "departure" and leg.scenes[-1].kind == "closest"
        times = [s.at for s in leg.scenes]
        assert times == sorted(times)
        assert leg.profile.depart_at <= times[0] and times[-1] == leg.profile.arrive_at
    milestones = [s.subject_id for leg in legs for s in leg.scenes if s.kind == "milestone"]
    assert milestones.count("sun_disk") == 1


def test_planning_record_is_saved(legs: list[Leg]) -> None:
    for leg in legs:
        p = leg.planning
        assert p.chosen_id == leg.target.id and p.chosen_id in p.offered_ids
        assert p.offered_ids == [c.id for c in p.candidates[: len(p.offered_ids)]]
        assert p.reason


async def test_answer_outside_the_offer_falls_back_to_the_top_candidate() -> None:
    async def wrong(offered: list[Candidate], context: dict[str, Any]) -> Choice:
        return Choice(target_id="pluto", reason="候補にない")

    leg = await plan_leg(load_world(), [], START_AT, wrong)
    assert leg is not None
    assert leg.planning.fell_back is True
    assert leg.target.id == leg.planning.candidates[0].id
