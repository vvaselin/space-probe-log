"""見え方の計算（6章）。入出力だけの純関数で、DBには触らない。"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.voyage.orbits import AU_KM, AU_PER_PC, Vec3, cross, dot, equatorial_to_ecliptic_unit, norm, scale, sub, unit
from app.voyage.world import Destination, Visual, World, position_au

FULL_MOON_DEG = 0.52
FULL_MOON_MAG = -12.74
TELESCOPE_ZOOM = 50.0
DISK_RATIO = 0.05
LARGE_RATIO = 1.0
DAZZLING_MAG = -4.0
NAKED_EYE_LIMIT_MAG = 6.0
OTHER_LIMIT = 5

Stage = Literal["大きく見える", "小さな円盤", "点"]
STAGE_RANK: dict[str, int] = {"大きく見える": 2, "小さな円盤": 1, "点": 0}


class Sighting(BaseModel):
    id: str
    name: str
    realism: str
    distance_km: float
    distance_au: float
    size_ratio: float
    stage: Stage
    telescope_stage: Stage
    size: str
    direction: str
    phase: str | None
    magnitude: float
    brightness: str
    look: str
    change: str | None
    visible: bool


def ship_frame(heading: Vec3) -> tuple[Vec3, Vec3, Vec3]:
    """進行方向、上（黄道の北に近い向き）、右舷の単位ベクトル。"""
    forward = unit(heading)
    ref = (0.0, 0.0, 1.0) if abs(forward[2]) < 0.99 else (1.0, 0.0, 0.0)
    up = unit(sub(ref, scale(forward, dot(ref, forward))))
    return forward, up, cross(forward, up)


def stage_for(ratio: float) -> Stage:
    if ratio >= LARGE_RATIO:
        return "大きく見える"
    if ratio >= DISK_RATIO:
        return "小さな円盤"
    return "点"


def size_ratio(radius_km: float, distance_km: float) -> float:
    return math.degrees(2 * math.atan(radius_km / distance_km)) / FULL_MOON_DEG


def approx(x: float) -> str:
    if x >= 100:
        return f"{float(f'{x:.2g}'):.0f}"
    if x >= 2:
        return f"{round(x)}"
    return f"{x:.2g}"


def _size_text(ratio: float) -> str:
    return "点にしか見えない" if ratio < DISK_RATIO else f"満月の約{approx(ratio)}倍"


def _direction_text(v: Vec3, frame: tuple[Vec3, Vec3, Vec3]) -> str:
    forward, up, right = frame
    fx = max(-1.0, min(1.0, dot(v, forward)))
    off_axis = math.degrees(math.acos(fx))
    if off_axis < 5:
        return "真正面"
    if off_axis > 175:
        return "真後ろ"
    azimuth = math.degrees(math.atan2(dot(v, right), fx))
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, dot(v, up)))))
    side, a = ("右" if azimuth > 0 else "左"), abs(azimuth)
    if a < 15:
        horizontal = "前方"
    elif a < 60:
        horizontal = f"前方やや{side}"
    elif a < 120:
        horizontal = f"{side}舷側"
    elif a < 165:
        horizontal = f"後方やや{side}"
    else:
        horizontal = "後方"
    if abs(elevation) < 5:
        return horizontal
    return f"{horizontal}、{'上' if elevation > 0 else '下'}に{round(abs(elevation))}度"


def _lit_fraction(body: Vec3, ship: Vec3) -> float:
    if norm(body) == 0:
        return 1.0
    return (1 + dot(unit(scale(body, -1)), unit(sub(ship, body)))) / 2


def _phase_text(body: Vec3, ship: Vec3, up: Vec3, lit: float) -> str:
    if lit > 0.97:
        return "ほぼ全面が明るい"
    if lit < 0.03:
        return "ほぼ全面が影に沈んでいる（太陽は向こう側）"
    view = unit(sub(body, ship))
    view_up = sub(up, scale(view, dot(up, view)))
    view_up = unit(view_up) if norm(view_up) > 1e-9 else ship_frame(view)[1]
    to_sun = unit(scale(body, -1))
    sx, sy = dot(to_sun, cross(view, view_up)), dot(to_sun, view_up)
    if abs(sx) >= abs(sy):
        side, opposite = ("右", "左") if sx > 0 else ("左", "右")
    else:
        side, opposite = ("上", "下") if sy > 0 else ("下", "上")
    if lit > 0.6:
        return f"{side}側が明るく、{opposite}の縁が影に入る"
    if lit >= 0.4:
        return f"{side}半分が明るい"
    if lit >= 0.15:
        return f"{side}側が三日月形に明るい"
    return f"{side}側に細い三日月形"


def _magnitude(dest: Destination, body: Vec3, distance_au: float, lit: float) -> float:
    if dest.abs_magnitude is not None:
        return dest.abs_magnitude + 5 * math.log10(distance_au / AU_PER_PC / 10)
    absolute = 5 * math.log10(1329 / (2 * dest.radius_km * math.sqrt(dest.visual.albedo)))
    return absolute + 5 * math.log10(norm(body) * distance_au) - 2.5 * math.log10(max(lit, 1e-3))


def _brightness_text(m: float) -> str:
    if m <= DAZZLING_MAG:
        label = "まぶしい"
    elif m <= -1:
        label = "どの恒星よりも明るい"
    elif m <= 1.5:
        label = "一等星ほどの明るさ"
    elif m <= 4:
        label = "目立たない星ほどの明るさ"
    elif m <= NAKED_EYE_LIMIT_MAG:
        label = "かろうじて見える"
    else:
        label = "広角では見えない（センサーでは捉える）"
    if m < -6:
        label += f"（満月の約{approx(10 ** (0.4 * (FULL_MOON_MAG - m)))}倍の明るさ）"
    return label


def _ring_text(visual: Visual, view: Vec3) -> str | None:
    if visual.rings is None:
        return None
    if visual.pole_ra_dec is None:
        return visual.rings.description
    opening = math.degrees(math.asin(min(1.0, abs(dot(equatorial_to_ecliptic_unit(*visual.pole_ra_dec), view)))))
    if opening < 3:
        tilt = "ほぼ真横から見え、細い線になっている"
    elif opening < 15:
        tilt = "浅い角度で斜めに横切る"
    else:
        tilt = "大きく傾いて開いて見える"
    return f"{visual.rings.description}が{tilt}"


def _look_text(visual: Visual, stage: Stage, view: Vec3) -> str:
    if stage == "点":
        return f"{visual.colors[0]}の光点"
    rings = _ring_text(visual, view)
    if stage == "小さな円盤":
        parts = ["・".join(visual.colors) + "の小さな円盤"]
        if rings and visual.rings and visual.rings.prominent:
            parts.append(rings)
        return "、".join(parts)
    parts = [visual.pattern]
    if rings:
        parts.append(rings)
    if visual.atmosphere:
        parts.append("縁が大気でぼんやり光る")
    return "、".join(parts)


def _change_text(stage: Stage, ratio: float, magnitude: float, previous: Sighting | None) -> str | None:
    if previous is None:
        return None
    if stage == "点":
        dm = magnitude - previous.magnitude
        if dm < -0.5:
            return f"前回より明るい（約{approx(10 ** (-0.4 * dm))}倍）"
        if dm > 0.5:
            return f"前回より暗い（約{approx(10 ** (0.4 * dm))}分の1）"
        return "前回とほぼ同じ明るさ"
    q = ratio / previous.size_ratio
    if q >= 1.3:
        return f"前回の約{approx(q)}倍の大きさ"
    if q <= 1 / 1.3:
        return f"前回の約{approx(1 / q)}分の1の大きさ"
    return "前回とほぼ同じ大きさ"


def sight(
    world: World, dest: Destination, t: datetime, ship: Vec3, heading: Vec3, previous: Sighting | None = None
) -> Sighting | None:
    body = position_au(world, dest, t)
    distance_au = norm(sub(body, ship))
    distance_km = distance_au * AU_KM
    if distance_km <= dest.radius_km:
        return None
    frame = ship_frame(heading)
    view = scale(sub(body, ship), 1 / distance_au)
    ratio = size_ratio(dest.radius_km, distance_km)
    stage, telescope_stage = stage_for(ratio), stage_for(ratio * TELESCOPE_ZOOM)
    is_star = dest.abs_magnitude is not None
    lit = 1.0 if is_star else _lit_fraction(body, ship)
    magnitude = _magnitude(dest, body, distance_au, lit)
    return Sighting(
        id=dest.id,
        name=dest.name,
        realism=dest.realism,
        distance_km=round(distance_km),
        distance_au=round(distance_au, 4),
        size_ratio=ratio,
        stage=stage,
        telescope_stage=telescope_stage,
        size=_size_text(ratio),
        direction=_direction_text(view, frame),
        phase=None if is_star or telescope_stage == "点" else _phase_text(body, ship, frame[1], lit),
        magnitude=round(magnitude, 2),
        brightness=_brightness_text(magnitude),
        look=_look_text(dest.visual, telescope_stage, view),
        change=_change_text(telescope_stage, ratio, magnitude, previous),
        visible=stage != "点" or magnitude <= NAKED_EYE_LIMIT_MAG,
    )


def observe(
    world: World,
    t: datetime,
    ship: Vec3,
    heading: Vec3,
    must_ids: list[str],
    previous: dict[str, Sighting] | None = None,
    limit: int = OTHER_LIMIT,
) -> list[Sighting]:
    """必ず入れる天体（太陽、地球、次の行き先など）と、見かけの大きさか明るさが大きい順に他を limit 件まで。"""
    previous = previous or {}
    must = list(dict.fromkeys(must_ids))
    seen = {d.id: sight(world, d, t, ship, heading, previous.get(d.id)) for d in world.destinations.values()}
    chosen = [s for i in must if (s := seen.get(i)) is not None]
    others = [
        s for i, s in seen.items() if s is not None and i not in must and (s.visible or s.telescope_stage != "点")
    ]
    others.sort(key=lambda s: (-STAGE_RANK[s.stage], -STAGE_RANK[s.telescope_stage], s.magnitude))
    return chosen + others[:limit]
