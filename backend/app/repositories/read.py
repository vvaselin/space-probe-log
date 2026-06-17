from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    CelestialBody,
    Discovery,
    ExplorationLog,
    Probe,
    ProbeStateHistory,
    Signal,
    SimulationEvent,
    StarSystem,
    Universe,
)


def active_universe(db: Session) -> Universe | None:
    return db.scalar(select(Universe).where(Universe.active.is_(True)).order_by(Universe.id.desc()))


def current_probe(db: Session) -> Probe | None:
    return db.scalar(select(Probe).where(Probe.id == "probe-insomnia-07").limit(1)) or db.scalar(select(Probe).order_by(Probe.id).limit(1))


def systems(db: Session) -> list[StarSystem]:
    return list(db.scalars(select(StarSystem).order_by(StarSystem.id)).all())


def system_detail(db: Session, system_id: str) -> StarSystem | None:
    return db.scalar(
        select(StarSystem)
        .where(StarSystem.id == system_id)
        .options(selectinload(StarSystem.bodies), selectinload(StarSystem.signals))
    )


def body_by_id(db: Session, body_id: str) -> CelestialBody | None:
    return db.get(CelestialBody, body_id)


def signal_by_id(db: Session, signal_id: str) -> Signal | None:
    return db.get(Signal, signal_id)


def logs(db: Session) -> list[ExplorationLog]:
    return list(db.scalars(select(ExplorationLog).order_by(ExplorationLog.mission_time.desc())).all())


def log_by_id(db: Session, log_id: int) -> ExplorationLog | None:
    return db.get(ExplorationLog, log_id)


def discoveries_for_events(db: Session, event_ids: list[int]) -> list[Discovery]:
    if not event_ids:
        return []
    return list(db.scalars(select(Discovery).where(Discovery.event_id.in_(event_ids))).all())


def route_points(db: Session, probe: Probe | None = None) -> list[dict[str, float]]:
    histories = db.scalars(select(ProbeStateHistory).order_by(ProbeStateHistory.mission_time)).all()
    points = [
        {
            "x": item.snapshot["display_x"],
            "y": item.snapshot["display_y"],
            "z": item.snapshot["display_z"],
        }
        for item in histories
    ]
    if probe is not None:
        current = {"x": probe.display_x, "y": probe.display_y, "z": probe.display_z}
        if not points or any(abs(points[-1][axis] - current[axis]) > 1e-6 for axis in ["x", "y", "z"]):
            points.append(current)
    return points


def events_for_log(db: Session, log: ExplorationLog) -> list[SimulationEvent]:
    if not log.related_event_ids:
        return []
    return list(db.scalars(select(SimulationEvent).where(SimulationEvent.id.in_(log.related_event_ids))).all())
