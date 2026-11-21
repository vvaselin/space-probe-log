"""場面の時刻表（9章）。区間の式が決まった時点で、場面の時刻を先に計算する。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.voyage.motion import LegProfile
from app.voyage.orbits import AU_KM, norm, sub
from app.voyage.visibility import size_ratio
from app.voyage.world import Destination, World, position_au

SceneKind = Literal["departure", "approach", "closest", "leave", "flyby", "milestone"]
SCENE_LABELS: dict[str, str] = {
    "departure": "出発",
    "approach": "接近",
    "closest": "最接近・到着",
    "leave": "離脱",
    "flyby": "すれ違い",
    "milestone": "節目",
}
APPROACH_RATIO = 0.5  # 満月の半分
SAMPLES = 400
# shortcut: すれ違いは区間を SAMPLES 等分して探すので、刻みより短い一瞬の接近は見落とす。見落としが問題になったら刻みを細かくする。


class Scene(BaseModel):
    kind: SceneKind
    at: datetime
    subject_id: str
    detail: dict[str, float | str] = Field(default_factory=dict)


def _ratio(world: World, dest: Destination, profile: LegProfile, t: datetime) -> float:
    distance_km = norm(sub(position_au(world, dest, t), profile.position_at(t))) * AU_KM
    return size_ratio(dest.radius_km, max(distance_km, dest.radius_km))


def _bisect(f: Callable[[datetime], float], a: datetime, b: datetime) -> datetime:
    """f(a) と f(b) の符号が違う区間で、符号が変わる時刻を探す。"""
    negative_at_a = f(a) < 0
    for _ in range(40):
        mid = a + (b - a) / 2
        if (f(mid) < 0) == negative_at_a:
            a = mid
        else:
            b = mid
    return b


def leg_scenes(
    world: World, profile: LegProfile, target: Destination, previous: Destination, passed_milestones: set[str]
) -> list[Scene]:
    t0, t1 = profile.depart_at, profile.arrive_at
    times = [t0 + (t1 - t0) * (i / SAMPLES) for i in range(SAMPLES + 1)]

    def series(dest: Destination) -> list[float]:
        return [_ratio(world, dest, profile, t) for t in times]

    def crossing(dest: Destination, values: list[float], rising: bool) -> datetime | None:
        for i in range(1, len(values)):
            if (values[i] >= APPROACH_RATIO) == rising and (values[i - 1] >= APPROACH_RATIO) != rising:
                return _bisect(lambda t: _ratio(world, dest, profile, t) - APPROACH_RATIO, times[i - 1], times[i])
        return None

    middle: list[Scene] = []
    if (at := crossing(target, series(target), rising=True)) is not None:
        middle.append(Scene(kind="approach", at=at, subject_id=target.id))
    if (at := crossing(previous, series(previous), rising=False)) is not None:
        middle.append(Scene(kind="leave", at=at, subject_id=previous.id))

    skip = {target.id, previous.id, "sun", target.parent_id, previous.parent_id}
    for dest in world.destinations.values():
        if dest.id in skip:
            continue
        values = series(dest)
        i = max(range(len(values)), key=values.__getitem__)
        if values[i] >= APPROACH_RATIO and 0 < i < SAMPLES:
            distance_km = norm(sub(position_au(world, dest, times[i]), profile.position_at(times[i]))) * AU_KM
            middle.append(Scene(kind="flyby", at=times[i], subject_id=dest.id, detail={"closest_km": round(distance_km)}))

    r0, r1 = norm(profile.origin_au), norm(profile.destination_au)
    for line in world.milestones:
        if line.id not in passed_milestones and r0 < line.r_au <= r1:
            at = _bisect(lambda t: norm(profile.position_at(t)) - line.r_au, t0, t1)
            middle.append(Scene(kind="milestone", at=at, subject_id=line.id, detail={"name": line.name, "r_au": line.r_au}))

    closest_km = norm(sub(position_au(world, target, t1), profile.destination_au)) * AU_KM
    return [
        Scene(kind="departure", at=t0, subject_id=target.id),
        *sorted(middle, key=lambda s: s.at),
        Scene(kind="closest", at=t1, subject_id=target.id, detail={"closest_km": round(closest_km)}),
    ]
