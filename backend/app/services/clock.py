from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models import MISSION_START_AT, SimulationClock, SimulationSettings
from app.schemas.domain import ClockState, SimulationClockUpdate, SimulationSettingsUpdate

DEFAULT_TIME_SCALE = 360.0
DEFAULT_TIME_SCALE_PRESETS = [0.0, 360.0, 1440.0, 10080.0, 525600.0]
DEFAULT_OFFLINE_CAP_SECONDS = 86_400


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def mission_clock_text(value: datetime) -> str:
    return _aware(value).strftime("%Y/%m/%d %H:%M:%S UTC")


def ensure_simulation_settings(db: Session) -> SimulationSettings:
    settings = db.get(SimulationSettings, 1)
    if settings is None:
        settings = SimulationSettings(
            id=1,
            default_time_scale=DEFAULT_TIME_SCALE,
            advance_offline=True,
            max_offline_elapsed_seconds=DEFAULT_OFFLINE_CAP_SECONDS,
            time_scale_presets=DEFAULT_TIME_SCALE_PRESETS,
            updated_at=utcnow(),
        )
        db.add(settings)
        db.flush()
    return settings


def ensure_simulation_clock(db: Session, *, real_now: datetime | None = None) -> SimulationClock:
    now = _aware(real_now or utcnow())
    settings = ensure_simulation_settings(db)
    clock = db.get(SimulationClock, 1)
    if clock is None:
        clock = SimulationClock(
            id=1,
            simulation_datetime=MISSION_START_AT,
            time_scale=settings.default_time_scale,
            clock_state=ClockState.running.value,
            last_real_datetime=now,
            updated_at=now,
        )
        db.add(clock)
        db.flush()
    return clock


def advance_simulation_clock(db: Session, *, real_now: datetime | None = None) -> tuple[SimulationClock, float]:
    now = _aware(real_now or utcnow())
    settings = ensure_simulation_settings(db)
    clock = ensure_simulation_clock(db, real_now=now)
    last_real = _aware(clock.last_real_datetime)
    real_elapsed_seconds = max(0.0, (now - last_real).total_seconds())
    applied_real_seconds = real_elapsed_seconds
    if clock.clock_state == ClockState.running.value:
        if not settings.advance_offline and real_elapsed_seconds > 2:
            applied_real_seconds = 0.0
        else:
            applied_real_seconds = min(real_elapsed_seconds, float(settings.max_offline_elapsed_seconds))
        clock.simulation_datetime = _aware(clock.simulation_datetime) + timedelta(seconds=applied_real_seconds * clock.time_scale)
    else:
        applied_real_seconds = 0.0
    clock.last_real_datetime = now
    clock.updated_at = now
    db.flush()
    return clock, applied_real_seconds


def update_simulation_clock(
    db: Session,
    payload: SimulationClockUpdate,
    *,
    real_now: datetime | None = None,
) -> tuple[SimulationClock, float]:
    clock, applied_seconds = advance_simulation_clock(db, real_now=real_now)
    now = _aware(real_now or utcnow())
    if payload.time_scale is not None:
        clock.time_scale = payload.time_scale
    if payload.clock_state is not None:
        clock.clock_state = payload.clock_state.value
    clock.last_real_datetime = now
    clock.updated_at = now
    db.flush()
    return clock, applied_seconds


def reset_simulation_clock(db: Session, *, real_now: datetime | None = None) -> SimulationClock:
    now = _aware(real_now or utcnow())
    settings = ensure_simulation_settings(db)
    clock = db.get(SimulationClock, 1)
    if clock is None:
        clock = SimulationClock(id=1)
        db.add(clock)
    clock.simulation_datetime = MISSION_START_AT
    clock.time_scale = settings.default_time_scale
    clock.clock_state = ClockState.running.value
    clock.last_real_datetime = now
    clock.updated_at = now
    db.flush()
    return clock


def update_simulation_settings(db: Session, payload: SimulationSettingsUpdate) -> SimulationSettings:
    settings = ensure_simulation_settings(db)
    if payload.default_time_scale is not None:
        settings.default_time_scale = payload.default_time_scale
    if payload.advance_offline is not None:
        settings.advance_offline = payload.advance_offline
    if payload.max_offline_elapsed_seconds is not None:
        settings.max_offline_elapsed_seconds = payload.max_offline_elapsed_seconds
    if payload.time_scale_presets is not None:
        presets = sorted({float(item) for item in payload.time_scale_presets if item >= 0})
        settings.time_scale_presets = presets or DEFAULT_TIME_SCALE_PRESETS
    settings.updated_at = utcnow()
    db.flush()
    return settings


def clock_payload(clock: SimulationClock, applied_real_seconds: float = 0.0) -> dict:
    sim_dt = _aware(clock.simulation_datetime)
    return {
        "simulation_datetime": sim_dt,
        "mission_clock": mission_clock_text(sim_dt),
        "time_scale": clock.time_scale,
        "clock_state": clock.clock_state,
        "last_real_datetime": _aware(clock.last_real_datetime),
        "real_elapsed_seconds_applied": applied_real_seconds,
    }
