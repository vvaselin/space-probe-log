"""公開のスケジューラ（10章）。自動モードの航海を、予定の時刻に1場面ずつ進める。

- 予定を過ぎていたら1本だけ書く。止まっていた間の分をまとめて書くことはしない（次の予定は書いた時刻から数え直す）
- 同じプロセスの中では VOYAGE_STEP_LOCK で、管理画面の「次の場面へ進める」と重ならないようにする
- プロセスをまたぐ二重の公開は、ログ番号と区間番号の一意制約で防ぐ（service.StepConflictError）
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.llm.client import JsonLLM
from app.llm.factory import get_voyage_llm
from app.voyage.clock import ensure_clock, next_publish_at
from app.voyage.service import StepConflictError, latest_voyage, step
from app.voyage.store import LogRecord, cached_session_factory
from app.voyage.world import load_world

LOGGER = logging.getLogger(__name__)
VOYAGE_STEP_LOCK = asyncio.Lock()

LLMFactory = Callable[[str, str], JsonLLM]


def _llm(purpose: str, seed: str) -> JsonLLM:
    return get_voyage_llm("route" if purpose == "route" else "log", seed)


async def step_latest(db: Session, make_llm: LLMFactory | None = None) -> LogRecord | None:
    """一番新しい航海を1場面進める（管理画面とスケジューラが使う）。航路の端なら None。"""
    voyage = latest_voyage(db)
    if voyage is None:
        raise LookupError("航海がまだない")
    make = make_llm or _llm  # 既定値に固定せず、呼ぶたびに探す（テストで差し替えられるように）
    return await step(db, voyage, load_world(), make("route", voyage.seed), make("log", voyage.seed))


async def publish_if_due(db: Session, now: datetime, make_llm: LLMFactory | None = None) -> LogRecord | None:
    voyage = latest_voyage(db)
    if voyage is None or voyage.ended:
        return None
    clock = ensure_clock(db, voyage)
    if clock.mode != "auto" or clock.paused_at is not None:
        return None
    if now < next_publish_at(db, voyage, clock, now):
        return None
    return await step_latest(db, make_llm)


async def run_voyage_scheduler(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    factory = cached_session_factory(settings.voyage_database_url)
    while not stop_event.is_set():
        try:
            async with VOYAGE_STEP_LOCK:
                with factory() as db:
                    record = await publish_if_due(db, utcnow())
                    if record is not None:
                        LOGGER.info("voyage scheduler published LOG #%03d (log id %s)", record.log_number, record.id)
        except StepConflictError as exc:
            LOGGER.warning("voyage scheduler skipped: %s", exc)
        except Exception:
            LOGGER.exception("voyage scheduler step failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.voyage_scheduler_poll_seconds)
        except TimeoutError:
            pass
