"""位置の同期（11章）。時刻表（現実の時刻 ⇔ シミュレーション内の時刻）と「現実の時刻から位置」。

フロントの frontend/utils/voyage/ に同じ式がある。変えたら両方を直し、`python -m app.voyage.golden` で答えを書き出し直す。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.voyage.motion import LegProfile
from app.voyage.orbits import Vec3
from app.voyage.route import Leg, start_position
from app.voyage.scenes import SCENE_LABELS
from app.voyage.store import LogRecord, VoyageRecord
from app.voyage.world import World

TIMETABLE_PUBLISHED_POINTS = 3


class TimetablePoint(BaseModel):
    real_at: datetime
    sim_at: datetime
    label: str
    published: bool


def _seconds(t: datetime) -> float:
    return t.timestamp()


def _utc(t: datetime) -> datetime:
    # SQLite はタイムゾーンを落とすので付け直す。
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def monotone_cubic(points: list[tuple[float, float]], x: float) -> float:
    """単調3次補間（Fritsch–Carlson）。点を必ず通り、行き過ぎない。範囲の外は端の値で止まる。"""
    if not points:
        raise ValueError("timetable has no points")
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    n = len(points)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0.0
        else:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    i = max(k for k in range(n - 1) if xs[k] <= x)
    t = (x - xs[i]) / h[i]
    t2, t3 = t * t, t * t * t
    return (
        (2 * t3 - 3 * t2 + 1) * ys[i]
        + (t3 - 2 * t2 + t) * h[i] * m[i]
        + (-2 * t3 + 3 * t2) * ys[i + 1]
        + (t3 - t2) * h[i] * m[i + 1]
    )


def sim_time_at(timetable: list[TimetablePoint], real_at: datetime) -> datetime:
    points: list[tuple[float, float]] = []
    for p in timetable:
        x = _seconds(p.real_at)
        if points and x <= points[-1][0]:
            points[-1] = (x, _seconds(p.sim_at))  # 同じ時刻の点は後の物を使う
            continue
        points.append((x, _seconds(p.sim_at)))
    return datetime.fromtimestamp(monotone_cubic(points, _seconds(real_at)), tz=UTC)


def probe_position(legs: list[Leg], start: Vec3, sim_at: datetime) -> tuple[Vec3, int | None]:
    """（位置、区間の番号）。区間は前の終点から始まるので、どこでもつながっている。"""
    for leg in legs:
        if sim_at <= leg.profile.arrive_at:
            return leg.profile.position_at(sim_at), leg.index
    if legs:
        return legs[-1].profile.destination_au, legs[-1].index
    return start, None


def _first_published_at(db: Session, voyage_id: int) -> dict[int, datetime]:
    rows = db.execute(
        select(LogRecord.log_number, func.min(LogRecord.created_at))
        .where(LogRecord.voyage_id == voyage_id)
        .group_by(LogRecord.log_number)
    ).all()
    return {n: _utc(t) for n, t in rows}


def build_timetable(
    db: Session, voyage: VoyageRecord, world: World, legs: list[Leg], publish_interval_s: float
) -> list[TimetablePoint]:
    """公開したログの直近の点と、次の公開の予定（最後の公開＋間隔、次の場面）。"""
    published_at = _first_published_at(db, voyage.id)
    logs = db.scalars(
        select(LogRecord).where(LogRecord.voyage_id == voyage.id, LogRecord.revision == 1).order_by(LogRecord.log_number)
    ).all()
    scenes = [(leg.index, i, scene) for leg in legs for i, scene in enumerate(leg.scenes)]
    by_key = {(li, si): scene for li, si, scene in scenes}

    def label(scene_kind: str, subject_id: str) -> str:
        name = world.destinations[subject_id].name if subject_id in world.destinations else subject_id
        return f"{SCENE_LABELS[scene_kind]}（{name}）"

    points: list[TimetablePoint] = []
    for log in logs[-TIMETABLE_PUBLISHED_POINTS:]:
        scene = by_key[(log.leg_index, log.scene_index)]
        points.append(
            TimetablePoint(
                real_at=published_at[log.log_number], sim_at=scene.at, label=label(scene.kind, scene.subject_id), published=True
            )
        )
    last_key = (logs[-1].leg_index, logs[-1].scene_index) if logs else None
    upcoming = next((s for li, si, s in scenes if last_key is None or (li, si) > last_key), None)
    if upcoming is not None:
        base = points[-1].real_at if points else _utc(voyage.created_at)
        points.append(
            TimetablePoint(
                real_at=base + timedelta(seconds=publish_interval_s),
                sim_at=upcoming.at,
                label=label(upcoming.kind, upcoming.subject_id),
                published=False,
            )
        )
    if not points:
        points.append(TimetablePoint(real_at=_utc(voyage.created_at), sim_at=voyage.start_at_utc, label="出発前", published=False))
    return points


def legs_in_range(legs: list[Leg], start: datetime, end: datetime) -> list[Leg]:
    return [leg for leg in legs if leg.profile.arrive_at >= start and leg.profile.depart_at <= end]


def leg_formula(leg: Leg) -> dict[str, object]:
    profile: LegProfile = leg.profile
    return {"index": leg.index, "target_id": leg.target.id, "profile": profile.model_dump(mode="json")}


def body_payload(world: World) -> list[dict[str, object]]:
    """フロントが天体を動かすのに要る項目だけ（軌道要素と大きさ）。見た目はLLM向けの言葉なので送らない。"""
    fields = {"id", "name", "subtype", "parent_id", "radius_km", "orbit"}
    return [d.model_dump(mode="json", include=fields) for d in world.destinations.values()]


def start_of(world: World, voyage: VoyageRecord) -> Vec3:
    return start_position(world, voyage.start_at_utc)
