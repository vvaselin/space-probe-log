from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models import (
    CelestialBody,
    Discovery,
    ExplorationLog,
    Probe,
    ProbeStateHistory,
    PromptSettings,
    ResourceInventory,
    Signal,
    SimulationAction,
    SimulationEvent,
    StarSystem,
    Universe,
)
from app.repositories.settings import load_prompt_defaults
from app.services.snapshots import probe_snapshot
from app.world.generator import generate_world


def reset_world(db: Session, world_seed: str | None = None) -> Probe:
    requested_seed = (world_seed or "").strip()
    seed = requested_seed or f"reset-{utcnow().isoformat()}"
    for model in [
        Discovery,
        ExplorationLog,
        SimulationEvent,
        SimulationAction,
        ProbeStateHistory,
        ResourceInventory,
        Probe,
        Signal,
        CelestialBody,
        StarSystem,
        Universe,
        PromptSettings,
    ]:
        db.execute(delete(model))
    universe = Universe(world_seed=seed, active=True, reset_at=utcnow())
    db.add(universe)
    db.flush()
    for spec in generate_world(seed):
        system = StarSystem(
            id=spec.id,
            universe_id=universe.id,
            name=spec.name,
            kind=spec.kind,
            x=spec.position[0],
            y=spec.position[1],
            z=spec.position[2],
            display_x=spec.display[0],
            display_y=spec.display[1],
            display_z=spec.display[2],
            discovered=True,
            generated_seed=spec.generated_seed,
            has_life=spec.has_life,
            resources=spec.resources,
            details=spec.details,
        )
        db.add(system)
        for body in spec.bodies:
            db.add(
                CelestialBody(
                    id=body.id,
                    system_id=spec.id,
                    name=body.name,
                    body_type=body.body_type,
                    orbit_radius_km=body.orbit_radius_km,
                    radius_km=body.radius_km,
                    sim_x=body.sim[0],
                    sim_y=body.sim[1],
                    sim_z=body.sim[2],
                    display_x=body.display[0],
                    display_y=body.display[1],
                    display_z=body.display[2],
                    display_radius=body.display_radius,
                    discovered=True,
                    details=body.details,
                )
            )
        for signal in spec.signals:
            db.add(
                Signal(
                    id=signal.id,
                    system_id=spec.id,
                    body_id=signal.body_id,
                    kind=signal.kind,
                    strength=signal.strength,
                    x=signal.position[0],
                    y=signal.position[1],
                    z=signal.position[2],
                    display_x=signal.display[0],
                    display_y=signal.display[1],
                    display_z=signal.display[2],
                    discovered=True,
                    investigated=False,
                    details=signal.details,
                )
            )
    db.flush()
    earth = db.get(CelestialBody, "earth")
    probe = Probe(
        id="probe-aurora",
        name="INSOMNIA-07",
        universe_id=universe.id,
        current_system_id="sol",
        target_id=None,
        x=earth.sim_x if earth else 1.0,
        y=earth.sim_y if earth else 0.03,
        z=earth.sim_z if earth else 0.17,
        display_x=earth.display_x if earth else 7.1,
        display_y=earth.display_y if earth else 0.2,
        display_z=earth.display_z if earth else 0.0,
        velocity=0.0,
        energy=100.0,
        fuel=100.0,
        hull=100.0,
        communication=100.0,
        sensors=100.0,
        propulsion=100.0,
        storage_used=4.0,
        storage_capacity=100.0,
        current_mission="太陽系外縁へ向かう段階航行",
        discovered_body_ids=["sun", "mercury", "venus", "earth", "moon", "mars", "jupiter", "saturn", "uranus", "neptune"],
        collected_resources={},
        mission_time=0,
    )
    probe.current_mission = "太陽系外縁へ向かう段階航行"
    db.add(probe)
    probe_profile, action_policy, log_writer_style = load_prompt_defaults()
    db.add(
        PromptSettings(
            id=1,
            probe_profile=probe_profile,
            action_policy=action_policy,
            log_writer_style=log_writer_style,
        )
    )
    db.flush()
    db.add(ProbeStateHistory(probe_id=probe.id, mission_time=probe.mission_time, snapshot=probe_snapshot(probe)))
    db.commit()
    db.refresh(probe)
    return probe
