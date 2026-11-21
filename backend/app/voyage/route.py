"""航路計画（5章）。候補を集めて点数順に並べ、上位を選び手（LLMかモック）に渡し、区間の式と場面を作る。"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.voyage.motion import LOCAL_SPEED_KM_S, LegProfile, cruise_speed_km_s, make_profile
from app.voyage.orbits import AU_KM, DAY_S, Vec3, add, norm, scale, sub, unit
from app.voyage.scenes import Scene, leg_scenes
from app.voyage.world import Destination, World, position_au

START_ID = "earth"
MAIN_MIN_FACTOR = 1.5
MAIN_MAX_FACTOR = 3.0
MIN_STEP_AU = 0.5
INWARD_LIMIT = 0.8
DETOUR_TIME_FACTOR = 0.5
OFFER_COUNT = 3
STAGNATION_BOOST = 0.5
WEIGHTS: dict[str, float] = {"outward": 1.0, "novelty": 0.5, "highlight": 1.0, "travel_time": -0.3}
STANDOFF_RADII: dict[str, float] = {"planet": 20.0}
DEFAULT_STANDOFF_RADII = 8.0
ETA_MAX_ITERATIONS = 5

LegKind = Literal["main", "detour", "tour"]
LEG_KIND_LABELS: dict[str, str] = {"main": "本線", "detour": "寄り道", "tour": "衛星の巡回"}


class Candidate(BaseModel):
    id: str
    name: str
    leg_kind: LegKind
    r_au: float
    travel_days: float
    scores: dict[str, float]
    total: float


class Planning(BaseModel):
    """航路計画の各段の出力。なぜここへ向かったかを後から追うために保存する。"""

    current_id: str
    current_r_au: float
    stagnation: int
    candidates: list[Candidate]
    offered_ids: list[str]
    llm_raw: dict[str, Any] | None
    chosen_id: str
    reason: str
    fell_back: bool


class Leg(BaseModel):
    index: int
    origin_id: str
    target: Destination
    leg_kind: LegKind
    profile: LegProfile
    scenes: list[Scene]
    planning: Planning


class Choice(BaseModel):
    """選び手の答え。target_id が候補の外か None なら、1位を使う。"""

    target_id: str | None
    reason: str
    raw: dict[str, Any] | None = None


Chooser = Callable[[list[Candidate], dict[str, Any]], Awaitable[Choice]]


def standoff_au(dest: Destination) -> float:
    return dest.radius_km * STANDOFF_RADII.get(dest.subtype, DEFAULT_STANDOFF_RADII) / AU_KM


def start_position(world: World, t: datetime) -> Vec3:
    """出発点は地球の夜側（太陽と反対側）の最接近距離の位置。"""
    earth = world.get(START_ID)
    pos = position_au(world, earth, t)
    return add(pos, scale(unit(pos), standoff_au(earth)))


def cursor(world: World, legs: list[Leg], start_at: datetime) -> tuple[str, Vec3, datetime]:
    """今いる行き先の ID、位置、時刻。到着したらその時刻にそのまま次へ出発する。"""
    if legs:
        last = legs[-1]
        return last.target.id, last.profile.destination_au, last.profile.arrive_at
    return START_ID, start_position(world, start_at), start_at


def aim(world: World, origin: Vec3, target: Destination, depart_at: datetime, speed_km_s: float) -> LegProfile:
    """動く目標は到着時刻の位置を狙う。到着時刻が1秒以内に収まるまで計算し直す（通常2〜3回）。"""
    arrive_at = depart_at
    profile: LegProfile | None = None
    for _ in range(ETA_MAX_ITERATIONS):
        target_pos = position_au(world, target, arrive_at)
        end = sub(target_pos, scale(unit(sub(target_pos, origin)), standoff_au(target)))
        profile = make_profile(origin, end, depart_at, speed_km_s)
        if abs((profile.arrive_at - arrive_at).total_seconds()) < 1:
            break
        arrive_at = profile.arrive_at
    assert profile is not None
    return profile


def stagnation(legs: list[Leg]) -> int:
    """外へ進まなかった区間（衛星の巡回は数えない）が、直近でいくつ続いているか。"""
    count = 0
    for leg in reversed(legs):
        if leg.leg_kind == "tour":
            continue
        if norm(leg.profile.destination_au) > norm(leg.profile.origin_au):
            break
        count += 1
    return count


def _candidate(
    dest: Destination, kind: LegKind, r: float, rd: float, days: float, recent_subtypes: list[str], stuck: int
) -> Candidate:
    # 本線（1.5倍以上）は一律1。遠くへ跳ぶほど得をしないので、距離は少しずつ伸びる。寄り道は外向きの割合だけ。
    outward_ratio = max(0.0, min(1.0, math.log(rd / r) / math.log(MAIN_MIN_FACTOR)))
    outward = 0.0 if kind == "tour" else outward_ratio * (1 + STAGNATION_BOOST * stuck)
    scores = {
        "outward": round(outward, 3),
        "novelty": 0.0 if dest.subtype in recent_subtypes[-3:] else 1.0,
        "highlight": dest.highlight,
        "travel_time": round(math.log10(1 + days), 3),
    }
    total = sum(WEIGHTS[k] * v for k, v in scores.items())
    return Candidate(
        id=dest.id, name=dest.name, leg_kind=kind, r_au=round(rd, 3), travel_days=round(days, 3), scores=scores, total=round(total, 3)
    )


def rank_candidates(world: World, legs: list[Leg], start_at: datetime) -> list[Candidate]:
    current_id, here, now = cursor(world, legs, start_at)
    visited = {START_ID, *(leg.target.id for leg in legs)}
    recent_subtypes = [leg.target.subtype for leg in legs]
    r = norm(here)
    current = world.get(current_id)
    stuck = stagnation(legs)

    def where(dest: Destination) -> tuple[float, float]:
        """（太陽からの距離 AU、今の位置からの距離 km）"""
        pos = position_au(world, dest, now)
        return norm(pos), norm(sub(pos, here)) * AU_KM

    # 惑星系の巡回：惑星（または準惑星）に着いたら、データにある衛星を巡ってから次へ。距離の規則の外で扱う。
    system_id = current.parent_id if current.subtype == "moon" and current.parent_id else current.id
    tour = [d for d in world.children(system_id) if d.id not in visited]
    if tour:
        ranked = []
        for dest in tour:
            rd, km = where(dest)
            ranked.append(_candidate(dest, "tour", r, rd, km / LOCAL_SPEED_KM_S / DAY_S, recent_subtypes, stuck))
        return sorted(ranked, key=lambda c: -c.total)

    mains: list[Candidate] = []
    others: list[Candidate] = []
    for dest in world.destinations.values():
        if dest.id in visited or dest.kind != "body" or dest.subtype in ("star", "moon"):
            continue
        rd, km = where(dest)
        if rd < INWARD_LIMIT * r:
            continue
        is_main = max(MAIN_MIN_FACTOR * r, r + MIN_STEP_AU) <= rd <= MAIN_MAX_FACTOR * r
        days = km / cruise_speed_km_s(max(r, rd)) / DAY_S
        (mains if is_main else others).append(_candidate(dest, "main" if is_main else "detour", r, rd, days, recent_subtypes, stuck))
    if not mains:
        return []
    detour_limit = DETOUR_TIME_FACTOR * min(c.travel_days for c in mains)
    detours = [c for c in others if c.travel_days <= detour_limit]
    return sorted(mains + detours, key=lambda c: -c.total)


def _passed_milestones(legs: list[Leg]) -> set[str]:
    return {s.subject_id for leg in legs for s in leg.scenes if s.kind == "milestone"}


async def plan_leg(world: World, legs: list[Leg], start_at: datetime, choose: Chooser) -> Leg | None:
    """次の区間を決める。候補がなければ None（今回は空白を埋める生成をしないので、ここで航路が終わる）。"""
    candidates = rank_candidates(world, legs, start_at)
    if not candidates:
        return None
    current_id, here, now = cursor(world, legs, start_at)
    offered = candidates[:OFFER_COUNT]
    context = {
        "current": world.get(current_id).name,
        "sun_distance_au": round(norm(here), 3),
        "recent_destinations": [leg.target.name for leg in legs[-3:]],
    }
    choice = await choose(offered, context)
    picked = next((c for c in offered if c.id == choice.target_id), None)
    # 上書きはこの1か所だけ：選び手の答えが候補の外なら1位を使う。
    fell_back = picked is None
    chosen = picked or offered[0]
    reason = choice.reason if picked else f"点数が最も高い候補（{chosen.name}）を選んだ"
    target = world.get(chosen.id)
    speed = LOCAL_SPEED_KM_S if chosen.leg_kind == "tour" else cruise_speed_km_s(max(norm(here), chosen.r_au))
    profile = aim(world, here, target, now, speed)
    return Leg(
        index=len(legs),
        origin_id=current_id,
        target=target,
        leg_kind=chosen.leg_kind,
        profile=profile,
        scenes=leg_scenes(world, profile, target, world.get(current_id), _passed_milestones(legs)),
        planning=Planning(
            current_id=current_id,
            current_r_au=round(norm(here), 4),
            stagnation=stagnation(legs),
            candidates=candidates,
            offered_ids=[c.id for c in offered],
            llm_raw=choice.raw,
            chosen_id=chosen.id,
            reason=reason,
            fell_back=fell_back,
        ),
    )
