"""再設計版の航行のAPI（10章、11章、12章）。DBは VOYAGE_DATABASE_URL。書き換える操作は管理者だけ。"""

from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.services.auth import require_admin
from app.voyage import clock
from app.voyage.route import Leg
from app.voyage.scheduler import VOYAGE_STEP_LOCK, step_latest
from app.voyage.service import StepConflictError, current_logs, latest_voyage, load_legs
from app.voyage.store import LogRecord, VoyageRecord, cached_session_factory
from app.voyage.sync import (
    TimetablePoint,
    body_payload,
    build_timetable,
    first_published_at,
    leg_formula,
    legs_in_range,
    probe_position,
    sim_time_at,
    start_of,
)
from app.voyage.world import World, load_world

router = APIRouter(prefix="/api/voyage", tags=["voyage"])


class ClockUpdate(BaseModel):
    mode: clock.ClockMode | None = None
    interval_seconds: float | None = Field(default=None, ge=1)


def get_voyage_db() -> Generator[Session, None, None]:
    db = cached_session_factory(get_settings().voyage_database_url)()
    try:
        yield db
    finally:
        db.close()


def _voyage(db: Session) -> VoyageRecord:
    voyage = latest_voyage(db)
    if voyage is None:
        raise HTTPException(status_code=404, detail="航海がまだない（`python -m app.voyage.cli new`）")
    return voyage


def _state(db: Session) -> tuple[VoyageRecord, World, list[Leg], list[TimetablePoint]]:
    voyage = _voyage(db)
    world = load_world()
    legs = load_legs(db, voyage.id)
    voyage_clock = clock.ensure_clock(db, voyage)
    pauses = clock.pause_spans(voyage_clock, clock.anchor_at(db, voyage))
    timetable = build_timetable(db, voyage, world, legs, clock.interval_seconds(voyage_clock), pauses)
    return voyage, world, legs, timetable


@router.get("/sync")
def voyage_sync(db: Session = Depends(get_voyage_db)) -> dict[str, Any]:
    """フロントが毎フレーム位置を計算するための材料：区間の式、時刻表、サーバーの時刻、天体の軌道要素、時計。"""
    voyage, world, legs, timetable = _state(db)
    sims = [p.sim_at for p in timetable]
    return {
        "server_time": utcnow().isoformat(),
        "voyage_id": voyage.id,
        "start_position_au": start_of(world, voyage),
        "timetable": [p.model_dump(mode="json") for p in timetable],
        "legs": [leg_formula(leg) for leg in legs_in_range(legs, min(sims), max(sims))],
        "bodies": body_payload(world),
        "clock": clock.status(db, voyage).model_dump(mode="json"),
    }


@router.get("/position")
def voyage_position(real_at: datetime | None = None, db: Session = Depends(get_voyage_db)) -> dict[str, Any]:
    """デバッグ用（12章）：現実の時刻を指定すると、バックが計算した位置を返す。省略すると今。"""
    voyage, world, legs, timetable = _state(db)
    real = real_at or utcnow()
    real = real if real.tzinfo else real.replace(tzinfo=UTC)
    sim = sim_time_at(timetable, real)
    position, leg_index = probe_position(legs, start_of(world, voyage), sim)
    return {"real_at": real.isoformat(), "sim_at": sim.isoformat(), "position_au": position, "leg_index": leg_index}


def _log_item(log: LogRecord, published_at: dict[int, datetime]) -> dict[str, Any]:
    scene = log.llm_input["scene"]
    return {
        "log_number": log.log_number,
        "title": log.title,
        "summary": log.summary,
        "scene": scene["kind"],
        "subject": scene["subject"],
        "sim_time": log.llm_input["time_utc"],
        "published_at": published_at.get(log.log_number, log.created_at).isoformat(),
        "revision": log.revision,
        "fallback": log.fallback,
    }


@router.get("/logs")
def list_logs(db: Session = Depends(get_voyage_db)) -> list[dict[str, Any]]:
    """新しい順。書き直したログは最新の版だけ。"""
    # shortcut: 全件を返す（1日1本なので当面は少ない）。数百本を超えたらページ分けを足す。
    voyage = _voyage(db)
    published_at = first_published_at(db, voyage.id)
    return [_log_item(log, published_at) for log in reversed(current_logs(db, voyage.id))]


@router.get("/logs/{log_number}")
def get_log(log_number: int, db: Session = Depends(get_voyage_db)) -> dict[str, Any]:
    voyage = _voyage(db)
    log = next((log for log in current_logs(db, voyage.id) if log.log_number == log_number), None)
    if log is None:
        raise HTTPException(status_code=404, detail=f"LOG #{log_number:03d} はない")
    payload = log.llm_input
    return {
        **_log_item(log, first_published_at(db, voyage.id)),
        "body_markdown": log.body_markdown,
        "position": payload["position"],
        "speed": payload["speed"],
        "current_leg": payload["current_leg"],
        "visible": payload["visible"],
        "next_destination": payload["next_destination"],
        "model": log.llm_output.get("model"),
    }


@router.get("/clock")
def read_clock(db: Session = Depends(get_voyage_db)) -> dict[str, Any]:
    return clock.status(db, _voyage(db)).model_dump(mode="json")


@router.patch("/clock")
def update_clock(payload: ClockUpdate, db: Session = Depends(get_voyage_db), _admin: object = Depends(require_admin)) -> dict[str, Any]:
    voyage = _voyage(db)
    clock.configure(db, voyage, mode=payload.mode, interval=payload.interval_seconds)
    return clock.status(db, voyage).model_dump(mode="json")


@router.post("/clock/pause")
def pause_clock(db: Session = Depends(get_voyage_db), _admin: object = Depends(require_admin)) -> dict[str, Any]:
    voyage = _voyage(db)
    clock.pause(db, voyage)
    return clock.status(db, voyage).model_dump(mode="json")


@router.post("/clock/resume")
def resume_clock(db: Session = Depends(get_voyage_db), _admin: object = Depends(require_admin)) -> dict[str, Any]:
    voyage = _voyage(db)
    clock.resume(db, voyage)
    return clock.status(db, voyage).model_dump(mode="json")


@router.post("/step")
async def publish_step(db: Session = Depends(get_voyage_db), _admin: object = Depends(require_admin)) -> dict[str, Any]:
    """次の場面へ進め、ログを1本書く（12章の管理画面のボタン）。時計のモードや一時停止に関係なく進める。"""
    _voyage(db)
    async with VOYAGE_STEP_LOCK:
        try:
            record = await step_latest(db)
        except StepConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=409, detail="航路の端に着いた。これ以上進める場面がない")
    return {
        "log_id": record.id,
        "log_number": record.log_number,
        "title": record.title,
        "scene": record.llm_input["scene"]["kind"],
        "fallback": record.fallback,
    }
