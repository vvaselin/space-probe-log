import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import CelestialBody, Signal, SimulationAction
from app.repositories.read import active_universe, route_points, system_detail, systems
from app.schemas.domain import MapPayload, SystemDetail, SystemRead
from app.services.clock import ensure_simulation_clock
from app.services.navigation import latest_navigation_state, navigation_display_anchor, navigation_payload
from app.services.probe_spec import probe_specification
from app.services.simulation import ensure_probe, main_route_target
from app.world.generator import generated_environment_objects, generated_small_body_layers, real_data_epoch, stable_seed, stellar_visual_data

router = APIRouter(prefix="/api/world", tags=["world"])


def _body_visual_data(body: CelestialBody) -> dict:
    visual_data = body.details.get("visual_data", {})
    if body.body_type != "star":
        return visual_data
    return stellar_visual_data(body.details.get("spectral_type"), visual_data)


def _system_stellar_data(system, star_body: CelestialBody | None) -> tuple[str | None, dict]:
    star_details = system.details.get("star", {})
    spectral_type = star_body.details.get("spectral_type") if star_body else star_details.get("spectral_type")
    visual_data = system.details.get("visual_data", {})
    if star_body is not None:
        visual_data = {**_body_visual_data(star_body), **visual_data}
    if spectral_type or star_body is not None:
        visual_data = stellar_visual_data(spectral_type, visual_data)
    return spectral_type, visual_data


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
    clock = ensure_simulation_clock(db)
    nav_state = latest_navigation_state(db, probe)
    universe = active_universe(db)
    world_seed = universe.world_seed if universe else "sol-neighborhood-001"
    all_systems = systems(db)
    environment_objects = generated_environment_objects(world_seed, all_systems)
    small_body_layers = generated_small_body_layers(world_seed)
    bodies = db.query(CelestialBody).all()
    star_bodies_by_system = {body.system_id: body for body in bodies if body.body_type == "star"}
    stellar_data_by_system = {
        system.id: _system_stellar_data(system, star_bodies_by_system.get(system.id)) for system in all_systems
    }
    signals = db.query(Signal).all()
    earth = next((body for body in bodies if body.id == "earth"), None)
    target = system_detail(db, probe.target_id) if probe.target_id else None
    primary_target = main_route_target(db, probe)
    latest_action = db.query(SimulationAction).order_by(SimulationAction.id.desc()).first()
    nav_payload = navigation_payload(probe, nav_state, clock.simulation_datetime)
    map_origin = {
        "id": "earth",
        "name": "地球",
        "x": earth.display_x if earth else 7.0,
        "y": earth.display_y if earth else 0.0,
        "z": earth.display_z if earth else 0.0,
    }
    prediction = None
    if target:
        target_display = navigation_display_anchor(db, target)
        prediction = {
            "target_id": target.id,
            "target_name": target.name,
            "from": {"x": probe.display_x, "y": probe.display_y, "z": probe.display_z},
            "to": {"x": target_display[0], "y": target_display[1], "z": target_display[2]},
        }
    primary_prediction = None
    if primary_target and primary_target.id != probe.current_system_id:
        primary_display = navigation_display_anchor(db, primary_target)
        primary_prediction = {
            "target_id": primary_target.id,
            "target_name": primary_target.name,
            "from": {"x": probe.display_x, "y": probe.display_y, "z": probe.display_z},
            "to": {"x": primary_display[0], "y": primary_display[1], "z": primary_display[2]},
        }
    return {
        "systems": [
            {
                "id": item.id,
                "name": item.name,
                "x": item.display_x,
                "y": item.display_y,
                "z": item.display_z,
                "display_position": {"x": item.display_x, "y": item.display_y, "z": item.display_z},
                "galactic_position_pc": {"x": item.x, "y": item.y, "z": item.z},
                "has_life": item.has_life,
                "kind": item.kind,
                "object_role": item.details.get("object_role", "system"),
                "source": item.details.get("source", "generated"),
                "spectral_type": stellar_data_by_system[item.id][0],
                "visual_data": stellar_data_by_system[item.id][1],
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
                "display_position": {"x": item.display_x, "y": item.display_y, "z": item.display_z},
                "physical_position_km": {"x": item.sim_x, "y": item.sim_y, "z": item.sim_z},
                "physical_radius_km": item.radius_km,
                "display_radius": item.display_radius,
                "object_role": "origin_body" if item.id == "earth" else "body",
                "source": item.details.get("source", "generated"),
                "spectral_type": item.details.get("spectral_type") if item.body_type == "star" else None,
                "visual_data": _body_visual_data(item),
            }
            for item in bodies
        ],
        "signals": [
            {
                "id": item.id,
                "system_id": item.system_id,
                "body_id": item.body_id,
                "kind": item.kind,
                "x": item.display_x,
                "y": item.display_y,
                "z": item.display_z,
                "investigated": item.investigated,
                "object_role": "signal",
            }
            for item in signals
        ],
        "environment_objects": [
            {
                "id": item.id,
                "name": item.name,
                "object_type": item.object_type,
                "x": item.display[0],
                "y": item.display[1],
                "z": item.display[2],
                "scale": {"x": item.scale[0], "y": item.scale[1], "z": item.scale[2]},
                "rotation": {"x": item.rotation[0], "y": item.rotation[1], "z": item.rotation[2]},
                "source": item.details.get("source", "generated"),
                "nebula_type": item.details.get("nebula_type"),
                "visual_data": item.details.get("visual_data", {}),
                "details": item.details,
            }
            for item in environment_objects
        ],
        "small_body_layers": [
            {
                "id": item.id,
                "name": item.name,
                "layer_type": item.layer_type,
                "center": {"x": item.center[0], "y": item.center[1], "z": item.center[2]},
                "inner_radius": item.inner_radius,
                "outer_radius": item.outer_radius,
                "thickness": item.thickness,
                "particle_count": item.particle_count,
                "seed": item.seed,
                "visual_data": item.visual_data,
                "details": item.details,
            }
            for item in small_body_layers
        ],
        "probe": {
            "id": probe.id,
            "name": probe.name,
            "x": probe.display_x,
            "y": probe.display_y,
            "z": probe.display_z,
            "display_position": {"x": probe.display_x, "y": probe.display_y, "z": probe.display_z},
            "galactic_position_pc": {"x": probe.x, "y": probe.y, "z": probe.z},
            "system_id": probe.current_system_id,
            "target_id": probe.target_id,
            "navigation": nav_payload,
            "specification": probe_specification().model_dump(mode="json"),
        },
        "route": route_points(db, probe),
        "route_prediction": prediction,
        "primary_route_prediction": primary_prediction,
        "navigation_intent": latest_action.raw_payload.get("navigation_intent", "main_route") if latest_action else "main_route",
        "map_origin": map_origin,
        "focus": {"x": probe.display_x, "y": probe.display_y, "z": probe.display_z},
        "distant_stars": distant_stars(world_seed),
        "real_data_epoch": real_data_epoch(),
        "clock": {
            "simulation_datetime": clock.simulation_datetime.isoformat().replace("+00:00", "Z"),
            "time_scale": clock.time_scale,
            "clock_state": clock.clock_state,
        },
    }
