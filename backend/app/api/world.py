import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import CelestialBody, Signal
from app.repositories.read import active_universe, route_points, system_detail, systems
from app.schemas.domain import MapPayload, SystemDetail, SystemRead
from app.services.simulation import display_probe_offset, ensure_probe
from app.world.generator import stable_seed

router = APIRouter(prefix="/api/world", tags=["world"])


def distant_stars(world_seed: str, count: int = 760) -> list[dict]:
    rng = random.Random(stable_seed(world_seed, "map-distant-stars"))
    stars = []
    for index in range(count):
        radius = rng.uniform(260, 760)
        is_bright = rng.random() > 0.88
        stars.append(
            {
                "id": f"bg-star-{index:03d}",
                "x": radius * rng.choice([-1, 1]) * rng.uniform(0.15, 1.0),
                "y": rng.uniform(-210, 210),
                "z": radius * rng.uniform(-1.0, 1.0),
                "size": rng.uniform(0.45, 1.05) if not is_bright else rng.uniform(1.1, 1.85),
                "brightness": rng.uniform(0.78, 1.25) if not is_bright else rng.uniform(1.35, 1.9),
                "color": "#ffffff" if rng.random() > 0.28 else "#dbeaff",
            }
        )
    return stars


@router.get("/systems", response_model=list[SystemRead])
def list_systems(db: Session = Depends(get_db)):
    ensure_probe(db)
    return systems(db)


@router.get("/systems/{system_id}", response_model=SystemDetail)
def get_system(system_id: str, db: Session = Depends(get_db)):
    ensure_probe(db)
    system = system_detail(db, system_id)
    if system is None:
        raise HTTPException(status_code=404, detail="system not found")
    return system


@router.get("/map", response_model=MapPayload)
def get_map(db: Session = Depends(get_db)):
    probe = ensure_probe(db)
    universe = active_universe(db)
    world_seed = universe.world_seed if universe else "sol-neighborhood-001"
    all_systems = systems(db)
    bodies = db.query(CelestialBody).all()
    signals = db.query(Signal).all()
    earth = next((body for body in bodies if body.id == "earth"), None)
    target = system_detail(db, probe.target_id) if probe.target_id else None
    map_origin = {
        "id": "earth",
        "name": "地球",
        "x": earth.display_x if earth else 7.0,
        "y": earth.display_y if earth else 0.0,
        "z": earth.display_z if earth else 0.0,
    }
    prediction = None
    if target:
        target_display = display_probe_offset(target)
        prediction = {
            "target_id": target.id,
            "target_name": target.name,
            "from": {"x": probe.display_x, "y": probe.display_y, "z": probe.display_z},
            "to": {"x": target_display[0], "y": target_display[1], "z": target_display[2]},
        }
    return {
        "systems": [
            {
                "id": item.id,
                "name": item.name,
                "x": item.display_x,
                "y": item.display_y,
                "z": item.display_z,
                "has_life": item.has_life,
                "kind": item.kind,
                "object_role": item.details.get("object_role", "system"),
            }
            for item in all_systems
        ],
        "bodies": [
            {
                "id": item.id,
                "system_id": item.system_id,
                "name": item.name,
                "type": item.body_type,
                "x": item.display_x,
                "y": item.display_y,
                "z": item.display_z,
                "radius": item.display_radius,
                "object_role": "origin_body" if item.id == "earth" else "body",
            }
            for item in bodies
        ],
        "signals": [
            {
                "id": item.id,
                "system_id": item.system_id,
                "kind": item.kind,
                "x": item.display_x,
                "y": item.display_y,
                "z": item.display_z,
                "investigated": item.investigated,
                "object_role": "signal",
            }
            for item in signals
        ],
        "probe": {
            "id": probe.id,
            "name": probe.name,
            "x": probe.display_x,
            "y": probe.display_y,
            "z": probe.display_z,
            "system_id": probe.current_system_id,
            "target_id": probe.target_id,
        },
        "route": route_points(db),
        "route_prediction": prediction,
        "map_origin": map_origin,
        "focus": {"x": probe.display_x, "y": probe.display_y, "z": probe.display_z},
        "distant_stars": distant_stars(world_seed),
    }
