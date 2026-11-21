"""再設計版の航行の読み取り専用API（11章、12章）。DBは VOYAGE_DATABASE_URL。"""

from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.voyage.route import Leg
from app.voyage.service import latest_voyage, load_legs
from app.voyage.store import VoyageRecord, cached_session_factory
from app.voyage.sync import (
    TimetablePoint,
    body_payload,
    build_timetable,
    leg_formula,
    legs_in_range,
    probe_position,
    sim_time_at,
    start_of,
)
from app.voyage.world import World, load_world

router = APIRouter(prefix="/api/voyage", tags=["voyage"])


def get_voyage_db() -> Generator[Session, None, None]:
    db = cached_session_factory(get_settings().voyage_database_url)()
    try:
        yield db
    finally:
        db.close()


def _state(db: Session) -> tuple[VoyageRecord, World, list[Leg], list[TimetablePoint]]:
    voyage = latest_voyage(db)
    if voyage is None:
        raise HTTPException(status_code=404, detail="航海がまだない（`python -m app.voyage.cli new`）")
    world = load_world()
    legs = load_legs(db, voyage.id)
    timetable = build_timetable(db, voyage, world, legs, get_settings().voyage_publish_interval_seconds)
    return voyage, world, legs, timetable


@router.get("/sync")
def voyage_sync(db: Session = Depends(get_voyage_db)) -> dict[str, Any]:
    """フロントが毎フレーム位置を計算するための材料：区間の式、時刻表、サーバーの時刻、天体の軌道要素。"""
    voyage, world, legs, timetable = _state(db)
    sims = [p.sim_at for p in timetable]
    return {
        "server_time": utcnow().isoformat(),
        "voyage_id": voyage.id,
        "start_position_au": start_of(world, voyage),
        "timetable": [p.model_dump(mode="json") for p in timetable],
        "legs": [leg_formula(leg) for leg in legs_in_range(legs, min(sims), max(sims))],
        "bodies": body_payload(world),
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
