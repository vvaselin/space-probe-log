import asyncio
from datetime import UTC, timedelta
import logging
import uuid

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.time import utcnow
from app.db.session import SessionLocal
from app.llm.factory import get_llm_client
from app.models import SchedulerLease
from app.schemas.domain import ClockState
from app.services.clock import ensure_simulation_clock
from app.services.simulation import run_tick


LOGGER = logging.getLogger(__name__)
TICK_LEASE_NAME = "simulation-tick"


def acquire_scheduler_lease(owner_id: str) -> bool:
    settings = get_settings()
    now = utcnow()
    expires_at = now + timedelta(seconds=settings.scheduler_lease_seconds)
    with SessionLocal() as db:
        if db.get(SchedulerLease, TICK_LEASE_NAME) is None:
            db.add(SchedulerLease(name=TICK_LEASE_NAME, owner_id=None, lease_expires_at=now))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
        result = db.execute(
            update(SchedulerLease)
            .where(
                SchedulerLease.name == TICK_LEASE_NAME,
                or_(
                    SchedulerLease.owner_id == owner_id,
                    SchedulerLease.owner_id.is_(None),
                    SchedulerLease.lease_expires_at < now,
                ),
            )
            .values(owner_id=owner_id, lease_expires_at=expires_at, updated_at=now)
        )
        db.commit()
        return result.rowcount == 1


def set_tick_in_progress(owner_id: str, in_progress: bool) -> bool:
    now = utcnow()
    with SessionLocal() as db:
        result = db.execute(
            update(SchedulerLease)
            .where(SchedulerLease.name == TICK_LEASE_NAME, SchedulerLease.owner_id == owner_id)
            .values(tick_in_progress=in_progress, updated_at=now)
        )
        db.commit()
        return result.rowcount == 1


def release_scheduler_lease(owner_id: str) -> None:
    now = utcnow()
    with SessionLocal() as db:
        db.execute(
            update(SchedulerLease)
            .where(SchedulerLease.name == TICK_LEASE_NAME, SchedulerLease.owner_id == owner_id)
            .values(owner_id=None, lease_expires_at=now, tick_in_progress=False, updated_at=now)
        )
        db.commit()


def tick_is_in_progress() -> bool:
    now = utcnow()
    with SessionLocal() as db:
        lease = db.get(SchedulerLease, TICK_LEASE_NAME)
        if lease is None or not lease.tick_in_progress:
            return False
        expires_at = lease.lease_expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at is not None and expires_at < now:
            return False
        return True


async def wait_for_tick_idle() -> None:
    settings = get_settings()
    deadline = asyncio.get_running_loop().time() + settings.scheduler_lease_seconds + 5
    while tick_is_in_progress():
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("Timed out waiting for the active simulation tick")
        await asyncio.sleep(0.05)


async def renew_lease_while_running(owner_id: str, stop_event: asyncio.Event) -> None:
    interval = max(1.0, get_settings().scheduler_lease_seconds / 3)
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            if not acquire_scheduler_lease(owner_id):
                return


async def run_simulation_scheduler(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    owner_id = str(uuid.uuid4())
    try:
        while not stop_event.is_set():
            if acquire_scheduler_lease(owner_id):
                should_tick = False
                with SessionLocal() as db:
                    clock = ensure_simulation_clock(db)
                    should_tick = clock.clock_state == ClockState.running.value and clock.time_scale > 0
                    db.commit()
                if should_tick and set_tick_in_progress(owner_id, True):
                    heartbeat_stop = asyncio.Event()
                    heartbeat_task = asyncio.create_task(renew_lease_while_running(owner_id, heartbeat_stop))
                    try:
                        with SessionLocal() as db:
                            clock = ensure_simulation_clock(db)
                            if clock.clock_state == ClockState.running.value and clock.time_scale > 0:
                                await run_tick(db, get_llm_client())
                    except Exception:
                        LOGGER.exception("Background simulation tick failed")
                    finally:
                        heartbeat_stop.set()
                        await heartbeat_task
                        set_tick_in_progress(owner_id, False)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.simulation_tick_interval_seconds)
            except TimeoutError:
                pass
    finally:
        release_scheduler_lease(owner_id)
