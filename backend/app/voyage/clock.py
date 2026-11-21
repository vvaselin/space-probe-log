"""時計（10章、12章）。シミュレーション内の時刻は場面ごとに進み、現実の時間は公開の間隔だけを決める。

- 次の公開 ＝ 最後の公開 ＋ 間隔 ＋ 最後の公開のあとに一時停止していた時間
- 一時停止の間は時間が進まない（時刻表では同じシミュレーション時刻の2点になる）
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.voyage.store import LogRecord, VoyageClockRecord, VoyageRecord

ClockMode = Literal["auto", "manual"]
PauseSpan = tuple[datetime, datetime | None]  # 終わっていない停止は終了が None


class ClockStatus(BaseModel):
    mode: ClockMode
    interval_seconds: float
    paused: bool
    paused_at: datetime | None
    last_published_at: datetime | None
    next_publish_at: datetime
    ended: bool


def _utc(t: datetime) -> datetime:
    # SQLite はタイムゾーンを落とすので付け直す。
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def ensure_clock(db: Session, voyage: VoyageRecord) -> VoyageClockRecord:
    """なければ手動モードで作る（開発中に意図せずLLMを呼び続けないため）。"""
    clock = db.get(VoyageClockRecord, voyage.id)
    if clock is None:
        clock = VoyageClockRecord(voyage_id=voyage.id, mode="manual", pauses=[])
        db.add(clock)
        db.commit()
    return clock


def interval_seconds(clock: VoyageClockRecord) -> float:
    return clock.interval_seconds or get_settings().voyage_publish_interval_seconds


def last_published_at(db: Session, voyage: VoyageRecord) -> datetime | None:
    """書き直しの版ではなく、初版を書いた時刻。"""
    value = db.scalar(
        select(func.max(LogRecord.created_at)).where(LogRecord.voyage_id == voyage.id, LogRecord.revision == 1)
    )
    return _utc(value) if value is not None else None


def pause_spans(clock: VoyageClockRecord, since: datetime) -> list[PauseSpan]:
    """since より後の停止区間（重なる分だけ）。"""
    spans: list[PauseSpan] = [(datetime.fromisoformat(s), datetime.fromisoformat(e)) for s, e in clock.pauses or []]
    if clock.paused_at is not None:
        spans.append((_utc(clock.paused_at), None))
    result: list[PauseSpan] = []
    for start, end in sorted(spans, key=lambda s: s[0]):
        if end is not None and end <= since:
            continue
        result.append((max(start, since), end))
    return result


def anchor_at(db: Session, voyage: VoyageRecord) -> datetime:
    """次の公開を数え始める時刻。まだ公開していなければ航海を作った時刻。"""
    return last_published_at(db, voyage) or _utc(voyage.created_at)


def next_publish_at(db: Session, voyage: VoyageRecord, clock: VoyageClockRecord, now: datetime) -> datetime:
    anchor = anchor_at(db, voyage)
    paused = sum((((end or now) - start).total_seconds() for start, end in pause_spans(clock, anchor)), 0.0)
    return anchor + timedelta(seconds=interval_seconds(clock) + paused)


def status(db: Session, voyage: VoyageRecord, now: datetime | None = None) -> ClockStatus:
    now = now or utcnow()
    clock = ensure_clock(db, voyage)
    return ClockStatus(
        mode="auto" if clock.mode == "auto" else "manual",
        interval_seconds=interval_seconds(clock),
        paused=clock.paused_at is not None,
        paused_at=_utc(clock.paused_at) if clock.paused_at else None,
        last_published_at=last_published_at(db, voyage),
        next_publish_at=next_publish_at(db, voyage, clock, now),
        ended=voyage.ended,
    )


def configure(db: Session, voyage: VoyageRecord, mode: ClockMode | None = None, interval: float | None = None) -> None:
    clock = ensure_clock(db, voyage)
    if mode is not None:
        clock.mode = mode
    if interval is not None:
        if interval <= 0:
            raise ValueError(f"interval must be positive, got {interval}")
        clock.interval_seconds = interval
    clock.updated_at = utcnow()
    db.commit()


def pause(db: Session, voyage: VoyageRecord, now: datetime | None = None) -> None:
    clock = ensure_clock(db, voyage)
    if clock.paused_at is None:
        clock.paused_at = now or utcnow()
        clock.updated_at = utcnow()
        db.commit()


def resume(db: Session, voyage: VoyageRecord, now: datetime | None = None) -> None:
    clock = ensure_clock(db, voyage)
    if clock.paused_at is None:
        return
    now = now or utcnow()
    anchor = anchor_at(db, voyage)
    # 最後の公開より前に終わった停止は、次の予定に関係しないので捨てる
    kept = [[s, e] for s, e in clock.pauses or [] if datetime.fromisoformat(e) > anchor]
    clock.pauses = [*kept, [_utc(clock.paused_at).isoformat(), now.isoformat()]]
    clock.paused_at = None
    clock.updated_at = utcnow()
    db.commit()
