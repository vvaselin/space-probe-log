"""航行を1場面ずつ進め、ログを1本ずつ書く（9章、12章）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.llm.client import JsonLLM
from app.models.entities import MISSION_START_AT
from app.voyage.llm import INTERNAL_KEY, LogDraft, llm_chooser, recent_phrases, write_log
from app.voyage.motion import SPEED_STATE_LABELS
from app.voyage.orbits import AU_KM, C_KM_S, norm, sub
from app.voyage.route import LEG_KIND_LABELS, Leg, plan_leg
from app.voyage.scenes import SCENE_LABELS, SCENE_MEANINGS
from app.voyage.store import LegRecord, LogRecord, VoyageRecord
from app.voyage.visibility import Sighting, observe
from app.voyage.world import World, position_au

class StepConflictError(RuntimeError):
    """同じ場面を2つの処理が同時に公開しようとした。"""


RECENT_LOGS = 3
PHRASE_WINDOW = 5
LOG_OTHER_LIMIT = 3  # 小さいモデルが全部を並べないよう、太陽・地球・行き先以外は3件まで
INTERNAL_SIGHTING_FIELDS = {"id", "size_ratio", "magnitude", "distance_au"}


def _time(t: datetime) -> str:
    return t.strftime("%Y/%m/%d %H:%M:%S UTC")


def _duration_text(seconds: float) -> str:
    if seconds < 60:
        return "1分未満"
    if seconds < 3600:
        return f"約{round(seconds / 60)}分"
    if seconds < 48 * 3600:
        return f"約{seconds / 3600:.1f}時間"
    return f"約{seconds / 86_400:.1f}日"


def create_voyage(db: Session, seed: str, start_at: datetime = MISSION_START_AT) -> VoyageRecord:
    voyage = VoyageRecord(seed=seed, start_at=start_at)
    db.add(voyage)
    db.commit()
    return voyage


def latest_voyage(db: Session) -> VoyageRecord | None:
    return db.scalars(select(VoyageRecord).order_by(VoyageRecord.id.desc())).first()


def load_legs(db: Session, voyage_id: int) -> list[Leg]:
    rows = db.scalars(select(LegRecord).where(LegRecord.voyage_id == voyage_id).order_by(LegRecord.index)).all()
    return [Leg.model_validate(row.data) for row in rows]


def current_logs(db: Session, voyage_id: int) -> list[LogRecord]:
    """ログ番号ごとに最新の版だけ。"""
    rows = db.scalars(
        select(LogRecord).where(LogRecord.voyage_id == voyage_id).order_by(LogRecord.log_number, LogRecord.revision)
    ).all()
    latest = {row.log_number: row for row in rows}
    return [latest[n] for n in sorted(latest)]


def build_log_payload(
    world: World,
    start_at: datetime,
    legs: list[Leg],
    leg_index: int,
    scene_index: int,
    log_number: int,
    previous: dict[str, Sighting],
    recent: list[LogRecord],
) -> dict[str, Any]:
    """LLMに渡す入力。そのまま保存し、書き直しにも使う。"""
    leg = legs[leg_index]
    scene = leg.scenes[scene_index]
    profile, t = leg.profile, scene.at
    ship = profile.position_at(t)
    next_leg = legs[leg_index + 1] if scene.kind == "closest" and leg_index + 1 < len(legs) else None
    subject = world.destinations[scene.subject_id].name if scene.subject_id in world.destinations else str(scene.detail.get("name"))
    must = ["sun", "earth", leg.target.id]
    if next_leg is not None:
        must.append(next_leg.target.id)
    if scene.kind in ("flyby", "leave"):
        must.append(scene.subject_id)
    sightings = observe(world, t, ship, sub(profile.destination_au, profile.origin_au), must, previous, LOG_OTHER_LIMIT)
    full_sightings = [s.model_dump() for s in sightings]
    speed = profile.speed_at(t)
    remaining_s = (profile.arrive_at - t).total_seconds()
    heading_leg = leg if scene.kind != "closest" else next_leg
    next_destination = (
        {
            "name": heading_leg.target.name,
            "reason": heading_leg.planning.reason,
            "eta_utc": _time(heading_leg.profile.arrive_at),
            "remaining_time": _duration_text((heading_leg.profile.arrive_at - t).total_seconds()),
        }
        if heading_leg is not None
        else None
    )
    earth = position_au(world, world.get("earth"), t)
    return {
        "log_number": log_number,
        "scene": {
            "kind": SCENE_LABELS[scene.kind],
            "meaning": SCENE_MEANINGS[scene.kind],
            "subject": subject,
            "detail": scene.detail,
        },
        "time_utc": _time(t),
        "mission_elapsed": _duration_text((t - start_at).total_seconds()),
        "position": {
            "sun_distance_au": round(norm(ship), 4),
            "earth_distance_km": round(norm(sub(ship, earth)) * AU_KM),
            "ecliptic_au": [round(c, 6) for c in ship],
        },
        "speed": {
            "km_s": round(speed, 1),
            "fraction_of_light": round(speed / C_KM_S, 5),
            "state": SPEED_STATE_LABELS[profile.state_at(t)],
        },
        "current_leg": {
            "kind": LEG_KIND_LABELS[leg.leg_kind],
            "from": world.get(leg.origin_id).name,
            "to": leg.target.name,
            "remaining_km": round(profile.distance_km - profile.travelled_km(t)),
            "eta_utc": _time(profile.arrive_at),
            "remaining_time": _duration_text(remaining_s) if remaining_s > 0 else "到着",
        },
        "visible": [{k: v for k, v in s.items() if k not in INTERNAL_SIGHTING_FIELDS} for s in full_sightings],
        "next_destination": next_destination,
        "recent_logs": [
            {"log_number": r.log_number, "scene": r.llm_input["scene"]["kind"], "summary": r.summary}
            for r in recent[-RECENT_LOGS:]
        ],
        "recent_phrases": recent_phrases([r.body_markdown for r in recent[-PHRASE_WINDOW:]]),
        # LLMには送らない。次のログの「前回との差」を計算するために残す。
        INTERNAL_KEY: {"sightings": full_sightings},
    }


def previous_sightings(log: LogRecord) -> dict[str, Sighting]:
    # 古いログは visible に全項目を持っていた。
    items = log.llm_input.get(INTERNAL_KEY, {}).get("sightings") or log.llm_input["visible"]
    return {s["id"]: Sighting.model_validate(s) for s in items}


def compose_markdown(payload: dict[str, Any], draft: LogDraft) -> str:
    """ヘッダーと末尾の数値はコードが書く。LLMが書くのは題と本文だけ。"""
    n = payload["log_number"]
    nxt = payload["next_destination"]
    return (
        "# INSOMNIA 航行ログ\n"
        "**探査機: INSOMNIA-07 ／ 搭載AI: NOCTUA-7**\n\n"
        f"## LOG #{n:03d} {draft.title}\n"
        f"**{payload['time_utc']} ／ {payload['scene']['kind']}**  \n"
        f"**位置: 太陽から {payload['position']['sun_distance_au']} AU ／ 速度: 毎秒 {payload['speed']['km_s']:,.1f} km**\n\n"
        f"{draft.body.strip()}\n\n---\n\n"
        f"**次の観測予定地点: {nxt['name'] if nxt else '未定（航路の候補がない）'}**\n\n"
        f"`[ LOG #{n:03d} - 記録終了 ]`\n"
    )


async def step(db: Session, voyage: VoyageRecord, world: World, route_llm: JsonLLM, log_llm: JsonLLM) -> LogRecord | None:
    """次の場面へ進め、ログを1本書いて保存する。航路の端に着いていたら None。"""
    legs = load_legs(db, voyage.id)
    logs = current_logs(db, voyage.id)
    start_at = voyage.start_at_utc
    choose = llm_chooser(route_llm, world)

    def save_leg(leg: Leg) -> None:
        legs.append(leg)
        db.add(LegRecord(voyage_id=voyage.id, index=leg.index, data=leg.model_dump(mode="json")))

    if not legs:
        first = await plan_leg(world, [], start_at, choose)
        if first is None:
            voyage.ended = True
            db.commit()
            return None
        save_leg(first)
    leg_index, scene_index = (logs[-1].leg_index, logs[-1].scene_index + 1) if logs else (0, 0)
    if scene_index >= len(legs[leg_index].scenes):
        leg_index, scene_index = leg_index + 1, 0
    if leg_index >= len(legs):
        return None
    # 到着の場面では、先に次の行き先を決めておく（ログの「次の観測予定地点」に使う）。
    if legs[leg_index].scenes[scene_index].kind == "closest" and leg_index + 1 == len(legs) and not voyage.ended:
        nxt = await plan_leg(world, legs, start_at, choose)
        if nxt is None:
            voyage.ended = True
        else:
            save_leg(nxt)

    previous = previous_sightings(logs[-1]) if logs else {}
    log_number = logs[-1].log_number + 1 if logs else 1
    payload = build_log_payload(world, start_at, legs, leg_index, scene_index, log_number, previous, logs)
    draft, output, fallback = await write_log(log_llm, payload)
    record = LogRecord(
        voyage_id=voyage.id,
        log_number=log_number,
        revision=1,
        leg_index=leg_index,
        scene_index=scene_index,
        title=draft.title,
        summary=draft.summary,
        body_markdown=compose_markdown(payload, draft),
        llm_input=payload,
        llm_output=output,
        fallback=fallback,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError as exc:
        # 別のプロセス（スケジューラ、管理画面、CLI）が先に同じ場面を公開した。区間もログも残さない。
        db.rollback()
        raise StepConflictError(f"LOG #{log_number:03d} は別の処理で先に公開された") from exc
    return record


async def rewrite(db: Session, log_id: int, log_llm: JsonLLM) -> LogRecord:
    """保存した入力から、ログだけを書き直す（今のプロンプトを使う）。新しい版として保存する。"""
    source = db.get(LogRecord, log_id)
    if source is None:
        raise LookupError(f"log id {log_id} not found")
    payload = source.llm_input
    draft, output, fallback = await write_log(log_llm, payload)
    latest_revision = db.scalar(
        select(func.max(LogRecord.revision)).where(
            LogRecord.voyage_id == source.voyage_id, LogRecord.log_number == source.log_number
        )
    )
    record = LogRecord(
        voyage_id=source.voyage_id,
        log_number=source.log_number,
        revision=(latest_revision or 0) + 1,
        leg_index=source.leg_index,
        scene_index=source.scene_index,
        title=draft.title,
        summary=draft.summary,
        body_markdown=compose_markdown(payload, draft),
        llm_input=payload,
        llm_output=output,
        fallback=fallback,
    )
    db.add(record)
    db.commit()
    return record
