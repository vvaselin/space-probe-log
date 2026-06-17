import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BodySpec:
    id: str
    name: str
    body_type: str
    orbit_radius_km: float | None
    radius_km: float
    sim: tuple[float, float, float]
    display: tuple[float, float, float]
    display_radius: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SignalSpec:
    id: str
    kind: str
    strength: float
    position: tuple[float, float, float]
    display: tuple[float, float, float]
    body_id: str | None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SystemSpec:
    id: str
    name: str
    position: tuple[float, float, float]
    display: tuple[float, float, float]
    generated_seed: str
    has_life: bool
    resources: dict[str, float]
    details: dict[str, Any]
    bodies: list[BodySpec]
    signals: list[SignalSpec]
    kind: str = "stellar"


@dataclass(frozen=True)
class EnvironmentObjectSpec:
    id: str
    name: str
    object_type: str
    position: tuple[float, float, float]
    display: tuple[float, float, float]
    scale: tuple[float, float, float]
    rotation: tuple[float, float, float]
    details: dict[str, Any]


def stable_seed(*parts: object) -> int:
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


REAL_SPACE_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "real_space"
SOLAR_SYSTEM_CACHE = REAL_SPACE_DATA_DIR / "solar_system.json"
EXOPLANET_CACHE = REAL_SPACE_DATA_DIR / "exoplanets_100ly.json"
SOLAR_DISPLAY_SCALE = 8.2
INTERSTELLAR_DISPLAY_SCALE = 9.0
SOLAR_DISTANCE_EXPONENT = 0.72
SOLAR_RADIUS_EXPONENT = 0.38
SOLAR_MIN_DISPLAY_RADIUS = 0.18
SOLAR_RADIUS_SCALE = 0.018


def load_real_space_objects(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in data.get("objects", []) if isinstance(item, dict)]


def real_data_epoch() -> str | None:
    epochs = []
    for path in (SOLAR_SYSTEM_CACHE, EXOPLANET_CACHE):
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("source_epoch"):
                epochs.append(str(data["source_epoch"]))
    return " / ".join(epochs) if epochs else None


def _real_details(obj: dict[str, Any], fallback_source: str) -> dict[str, Any]:
    return {
        "source": obj.get("source", fallback_source),
        "source_id": obj.get("source_id"),
        "source_epoch": obj.get("source_epoch"),
        "physical_data": obj.get("physical_data", {}),
        "position_data": obj.get("position_data", {}),
        "visual_data": obj.get("visual_data", {}),
        "fictional_data": obj.get("fictional_data", {}),
    }


def _solar_display(obj: dict[str, Any]) -> tuple[float, float, float]:
    state = obj.get("position_data", {}).get("solar_system_au", {})
    return _solar_display_from_state(float(state.get("x", 0.0)), float(state.get("y", 0.0)), float(state.get("z", 0.0)))


def _solar_sim(obj: dict[str, Any]) -> tuple[float, float, float]:
    state = obj.get("position_data", {}).get("solar_system_au", {})
    return float(state.get("x", 0.0)), float(state.get("y", 0.0)), float(state.get("z", 0.0))


def _exoplanet_display(obj: dict[str, Any]) -> tuple[float, float, float]:
    state = obj.get("position_data", {}).get("interstellar_pc", {})
    return (
        float(state.get("x", 0.0)) * INTERSTELLAR_DISPLAY_SCALE,
        float(state.get("y", 0.0)) * INTERSTELLAR_DISPLAY_SCALE,
        float(state.get("z", 0.0)) * INTERSTELLAR_DISPLAY_SCALE,
    )


def _display_radius_from_tuple(point: tuple[float, float, float]) -> float:
    return math.sqrt(point[0] ** 2 + point[1] ** 2 + point[2] ** 2)


def _normalize_vector(point: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(point[0] ** 2 + point[1] ** 2 + point[2] ** 2)
    if length <= 1e-9:
        return (0.0, 0.0, 1.0)
    return (point[0] / length, point[1] / length, point[2] / length)


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _world_basis(world_seed: str) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    rng = random.Random(stable_seed(world_seed, "world-basis"))
    theta = rng.uniform(0.0, math.tau)
    phi = rng.uniform(-0.72, 0.72)
    forward = _normalize_vector(
        (
            math.cos(phi) * math.cos(theta),
            math.sin(phi),
            math.cos(phi) * math.sin(theta),
        )
    )
    guide = (0.0, 1.0, 0.0) if abs(forward[1]) < 0.92 else (1.0, 0.0, 0.0)
    right = _normalize_vector(_cross(guide, forward))
    up = _normalize_vector(_cross(forward, right))
    return forward, right, up


def _orient_local(world_seed: str, radial: float, lateral: float, vertical: float) -> tuple[float, float, float]:
    forward, right, up = _world_basis(world_seed)
    return (
        forward[0] * radial + right[0] * lateral + up[0] * vertical,
        forward[1] * radial + right[1] * lateral + up[1] * vertical,
        forward[2] * radial + right[2] * lateral + up[2] * vertical,
    )


def _solar_display_from_state(x: float, y: float, z: float) -> tuple[float, float, float]:
    distance = math.sqrt(x * x + y * y + z * z)
    if distance <= 1e-6:
        return (0.0, 0.0, 0.0)
    compressed = (distance**SOLAR_DISTANCE_EXPONENT) * SOLAR_DISPLAY_SCALE
    return (
        (x / distance) * compressed,
        (y / distance) * compressed * 0.28,
        (z / distance) * compressed,
    )


def _solar_display_radius(radius_km: float) -> float:
    radius = max(SOLAR_MIN_DISPLAY_RADIUS, (radius_km**SOLAR_RADIUS_EXPONENT) * SOLAR_RADIUS_SCALE)
    if radius_km >= 300_000:
        return min(2.45, radius * 0.76)
    return radius


def _solar_visual_data(body_id: str, body_type: str) -> dict[str, Any]:
    visual_data: dict[str, Any] = {
        "texture_key": _body_texture_key(body_type),
        "emissive": body_type == "star",
    }
    if body_id == "saturn":
        visual_data["ring"] = {
            "inner_radius": 1.5,
            "outer_radius": 2.35,
            "texture_key": "ring_01",
            "tilt": 0.48,
            "opacity": 0.72,
            "color": "#d9d1b0",
        }
    return visual_data


def real_solar_system() -> SystemSpec | None:
    objects = load_real_space_objects(SOLAR_SYSTEM_CACHE)
    if not objects:
        return None
    body_specs = []
    for obj in objects:
        physical = obj.get("physical_data", {})
        display = _solar_display(obj)
        body_specs.append(
            BodySpec(
                id=str(obj["id"]),
                name=str(obj["name"]),
                body_type=str(obj.get("object_type", "rocky_planet")),
                orbit_radius_km=None,
                radius_km=float(physical.get("radius_km") or 1_000),
                sim=_solar_sim(obj),
                display=display,
                display_radius=_solar_display_radius(float(physical.get("radius_km") or 1_000)),
                details=_real_details(obj, "jpl_horizons"),
            )
        )
    return SystemSpec(
        id="sol",
        name="太陽系",
        position=(0, 0, 0),
        display=(0, 0, 0),
        generated_seed="real-sol-cache",
        has_life=True,
        resources={"water_ice": 12.0, "silicates": 40.0},
        details={
            "source": "jpl_horizons",
            "object_role": "origin",
            "navigation_order": 0,
            "physical_data": {},
            "position_data": {"coordinate_system": "solar_system_au"},
            "visual_data": {"texture_key": "star_yellow_01"},
            "fictional_data": {"generated_features": {"resources": {"water_ice": 12.0, "silicates": 40.0}}},
        },
        bodies=body_specs,
        signals=[
            SignalSpec(
                "signal-sol-001",
                "radio_beacon",
                0.72,
                (1.01, 0.03, 0.17),
                (7.2, 0.8, 1.5),
                "earth",
                {"source": "generated", "fictional_data": {"frequency": "1420MHz", "pattern": "terrestrial calibration"}},
            ),
        ],
    )


def solar_system() -> SystemSpec:
    cached = real_solar_system()
    if cached is not None:
        return cached
    bodies = [
        BodySpec("sun", "太陽", "star", None, 696_340, (0, 0, 0), (0, 0, 0), 2.4, {"spectral_type": "G2V"}),
        BodySpec("earth", "地球", "terrestrial_planet", 149_600_000, 6_371, (1, 0.03, 0.17), (7.0, 0.4, 1.2), 0.55, {"atmosphere": "nitrogen_oxygen"}),
        BodySpec("mars", "火星", "terrestrial_planet", 227_900_000, 3_389.5, (1.52, -0.09, -0.34), (9.5, -0.6, -2.2), 0.42, {"atmosphere": "thin_co2"}),
        BodySpec("jupiter", "木星", "gas_giant", 778_500_000, 69_911, (5.2, 0.31, 0.88), (17.0, 1.1, 3.5), 1.2, {"atmosphere": "hydrogen_helium"}),
    ]
    return SystemSpec(
        id="sol",
        name="太陽系",
        position=(0, 0, 0),
        display=(0, 0, 0),
        generated_seed="fixed-sol",
        has_life=True,
        resources={"water_ice": 12.0, "silicates": 40.0},
        details={"star": {"name": "太陽", "mass_solar": 1.0}, "object_role": "origin", "navigation_order": 0},
        bodies=bodies,
        signals=[
            SignalSpec("signal-sol-001", "radio_beacon", 0.72, (1.01, 0.03, 0.17), (7.2, 0.8, 1.5), "earth", {"frequency": "1420MHz", "pattern": "terrestrial calibration"}),
        ],
    )


def navigation_waypoint(
    waypoint_id: str,
    name: str,
    position: tuple[float, float, float],
    display: tuple[float, float, float],
    order: int,
) -> SystemSpec:
    return SystemSpec(
        id=waypoint_id,
        name=name,
        position=position,
        display=display,
        generated_seed=f"fixed-{waypoint_id}",
        has_life=False,
        resources={},
        details={
            "object_role": "navigation_waypoint",
            "navigation_order": order,
            "description": "太陽系外縁へ向かうための確定済み航行基準点",
        },
        bodies=[],
        signals=[],
        kind="waypoint",
    )


def fictional_system(world_seed: str, index: int, coordinate: tuple[int, int, int]) -> SystemSpec:
    seed = stable_seed(world_seed, coordinate, index)
    rng = random.Random(seed)
    prefixes = ["Kepler", "Aster", "Mira", "Lacaille", "Noctua", "Vela"]
    name = f"{rng.choice(prefixes)}-{rng.randint(100, 999)}"
    x = coordinate[0] + rng.uniform(-0.45, 0.45)
    y = coordinate[1] + rng.uniform(-0.45, 0.45)
    z = coordinate[2] + rng.uniform(-0.45, 0.45)
    display = (x * 18, y * 18, z * 18)
    star_radius = rng.uniform(250_000, 900_000)
    planet_count = rng.randint(2, 5)
    bodies = [
        BodySpec(
            id=f"{name.lower()}-star",
            name=f"{name} 主星",
            body_type="star",
            orbit_radius_km=None,
            radius_km=star_radius,
            sim=(x, y, z),
            display=display,
            display_radius=rng.uniform(1.2, 2.1),
            details={"spectral_type": rng.choice(["K", "G", "M", "F"]), "fictional": True, "visual_data": {"texture_key": "star_yellow_01"}},
        )
    ]
    for planet_index in range(planet_count):
        orbit = 60_000_000 + planet_index * rng.uniform(45_000_000, 120_000_000)
        dx = (planet_index + 1) * 1.8
        body_id = f"{name.lower()}-{planet_index + 1}"
        body_type = rng.choice(["rocky_planet", "ice_world", "gas_giant", "ocean_world"])
        bodies.append(
            BodySpec(
                id=body_id,
                name=f"{name}-{planet_index + 1}",
                body_type=body_type,
                orbit_radius_km=orbit,
                radius_km=rng.uniform(2_100, 55_000),
                sim=(x + dx, y, z),
                display=(display[0] + dx * 2.3, display[1] + rng.uniform(-2, 2), display[2] + rng.uniform(-2, 2)),
                display_radius=rng.uniform(0.35, 1.0),
                details={
                    "surface_temperature_k": round(rng.uniform(80, 520), 1),
                    "visual_data": {"texture_key": _body_texture_key(body_type)},
                    "fictional_data": {},
                },
            )
        )
    signals: list[SignalSpec] = []
    for signal_index in range(rng.randint(1, 3)):
        host = rng.choice(bodies[1:])
        signals.append(
            SignalSpec(
                id=f"signal-{name.lower()}-{signal_index + 1}",
                kind=rng.choice(["radio_signal", "infrared_pulse", "magnetic_anomaly"]),
                strength=round(rng.uniform(0.2, 0.95), 2),
                position=host.sim,
                display=(host.display[0] + rng.uniform(-0.6, 0.6), host.display[1] + 0.8, host.display[2]),
                body_id=host.id,
                details={"frequency": f"{round(rng.uniform(0.3, 8.0), 2)}GHz", "periodic": rng.choice([True, False])},
            )
        )
    return SystemSpec(
        id=f"sys-{index}",
        name=name,
        position=(x, y, z),
        display=display,
        generated_seed=str(seed),
        has_life=rng.random() > 0.65,
        resources={"water_ice": round(rng.uniform(0, 30), 2), "rare_metals": round(rng.uniform(0, 12), 2)},
        details={"star": bodies[0].details, "coordinate": list(coordinate), "object_role": "nearby_system", "navigation_order": 10 + index},
        bodies=bodies,
        signals=signals,
    )


def frontier_system(world_seed: str, ring: int, slot: int, base_radius: float) -> SystemSpec:
    seed = stable_seed(world_seed, "frontier", ring, slot, round(base_radius, 2))
    rng = random.Random(seed)
    names = ["Noctua", "Lumen", "Vesper", "Astra", "Umbra", "Orison", "Caelum", "Morrow"]
    name = f"{rng.choice(names)}-{ring}{slot}{rng.randint(10, 99)}"
    radius = base_radius + ring * 2.8 + rng.uniform(0.5, 3.0)
    theta = (slot / 4) * math.tau + rng.uniform(-0.46, 0.46)
    phi = rng.uniform(-0.58, 0.58)
    x = math.cos(phi) * math.cos(theta) * radius
    y = math.sin(phi) * radius
    z = math.cos(phi) * math.sin(theta) * radius
    display = (x * 18, y * 18, z * 18)
    star_mass = round(rng.uniform(0.35, 1.8), 2)
    planet_count = rng.randint(2, 6)
    spectral_type = rng.choice(["M", "K", "G", "F", "A"])
    bodies = [
        BodySpec(
            id=f"{name.lower()}-star",
            name=f"{name} 主星",
            body_type="star",
            orbit_radius_km=None,
            radius_km=rng.uniform(240_000, 1_050_000),
            sim=(x, y, z),
            display=display,
            display_radius=rng.uniform(1.1, 2.0),
            details={"spectral_type": spectral_type, "mass_solar": star_mass, "fictional": True},
        )
    ]
    for planet_index in range(planet_count):
        orbit = 45_000_000 + planet_index * rng.uniform(38_000_000, 135_000_000)
        angle = rng.uniform(0, math.tau)
        spread = (planet_index + 1) * rng.uniform(1.4, 2.4)
        body_id = f"{name.lower()}-{planet_index + 1}"
        body_type = rng.choice(["rocky_planet", "ice_world", "gas_giant", "ocean_world", "dwarf_planet"])
        bodies.append(
            BodySpec(
                id=body_id,
                name=f"{name}-{planet_index + 1}",
                body_type=body_type,
                orbit_radius_km=orbit,
                radius_km=rng.uniform(2_000, 70_000),
                sim=(x + math.cos(angle) * spread, y + rng.uniform(-0.16, 0.16), z + math.sin(angle) * spread),
                display=(
                    display[0] + math.cos(angle) * spread * 2.3,
                    display[1] + rng.uniform(-2.4, 2.4),
                    display[2] + math.sin(angle) * spread * 2.3,
                ),
                display_radius=rng.uniform(0.32, 1.15),
                details={
                    "surface_temperature_k": round(rng.uniform(50, 610), 1),
                    "orbit_band": planet_index + 1,
                    "visual_data": {"texture_key": _body_texture_key(body_type)},
                    "fictional_data": {},
                },
            )
        )
    signals: list[SignalSpec] = []
    signal_count = 1 if rng.random() < 0.72 else 2
    for signal_index in range(signal_count):
        host = rng.choice(bodies[1:])
        signals.append(
            SignalSpec(
                id=f"signal-{name.lower()}-{signal_index + 1}",
                kind=rng.choice(["radio_signal", "infrared_pulse", "magnetic_anomaly", "gravitational_lensing_noise"]),
                strength=round(rng.uniform(0.24, 0.92), 2),
                position=host.sim,
                display=(host.display[0] + rng.uniform(-0.8, 0.8), host.display[1] + 0.9, host.display[2]),
                body_id=host.id,
                details={"frequency": f"{round(rng.uniform(0.2, 9.5), 2)}GHz", "periodic": rng.choice([True, False])},
            )
        )
    has_life = rng.random() > 0.82
    return SystemSpec(
        id=f"frontier-{ring}-{slot}",
        name=name,
        position=(x, y, z),
        display=display,
        generated_seed=str(seed),
        has_life=has_life,
        resources={
            "water_ice": round(rng.uniform(8, 34), 2),
            "rare_metals": round(rng.uniform(1, 14), 2),
            "hydrogen": round(rng.uniform(4, 18), 2),
        },
        details={
            "star": bodies[0].details,
            "object_role": "frontier_system",
            "navigation_order": 120 + ring * 10 + slot,
            "frontier_ring": ring,
            "distance_from_origin": radius,
            "narrative_tier": "frontier" if ring < 4 else "deep_frontier",
        },
        bodies=bodies,
        signals=signals,
    )


def frontier_shell_systems(world_seed: str, ring: int, base_radius: float, count: int = 4) -> list[SystemSpec]:
    return [frontier_system(world_seed, ring, slot + 1, base_radius) for slot in range(count)]


def real_exoplanet_systems(limit_hosts: int = 48) -> list[SystemSpec]:
    objects = load_real_space_objects(EXOPLANET_CACHE)
    if not objects:
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for obj in objects:
        host = str(obj.get("physical_data", {}).get("hostname") or obj.get("name") or "unknown")
        grouped.setdefault(host, []).append(obj)
    systems_out = []
    for index, (host, planets) in enumerate(sorted(grouped.items())[:limit_hosts], start=1):
        first = planets[0]
        display = _exoplanet_display(first)
        state = first.get("position_data", {}).get("interstellar_pc", {})
        spectral_hint = _stellar_spectral_hint(first)
        bodies = [
            BodySpec(
                id=f"nea-{_slug(host)}-star",
                name=host,
                body_type="star",
                orbit_radius_km=None,
                radius_km=696_340,
                sim=(float(state.get("x", 0.0)), float(state.get("y", 0.0)), float(state.get("z", 0.0))),
                display=display,
                display_radius=1.1,
                details={
                    "source": "nasa_exoplanet_archive",
                    "physical_data": {
                        "stellar_teff_k": first.get("physical_data", {}).get("stellar_teff_k"),
                        "stellar_radius_solar": first.get("physical_data", {}).get("stellar_radius_solar"),
                        "stellar_mass_solar": first.get("physical_data", {}).get("stellar_mass_solar"),
                    },
                    "position_data": first.get("position_data", {}),
                    "visual_data": {"texture_key": _star_texture_key(first)},
                    "fictional_data": {},
                    "spectral_type": spectral_hint,
                },
            )
        ]
        for planet_index, planet in enumerate(planets, start=1):
            p_display = (display[0] + planet_index * 2.4, display[1] + (planet_index % 2) * 0.7, display[2] - planet_index * 1.2)
            physical = planet.get("physical_data", {})
            bodies.append(
                BodySpec(
                    id=str(planet["id"]),
                    name=str(planet["name"]),
                    body_type=str(planet.get("object_type", "rocky_planet")),
                    orbit_radius_km=None,
                    radius_km=float(physical.get("planet_radius_earth") or 1.0) * 6_371,
                    sim=(float(state.get("x", 0.0)), float(state.get("y", 0.0)), float(state.get("z", 0.0))),
                    display=p_display,
                    display_radius=max(0.28, min(1.15, float(physical.get("planet_radius_earth") or 1.0) * 0.22)),
                    details=_real_details(planet, "nasa_exoplanet_archive"),
                )
            )
        systems_out.append(
            SystemSpec(
                id=f"real-{_slug(host)}",
                name=host,
                position=(float(state.get("x", 0.0)), float(state.get("y", 0.0)), float(state.get("z", 0.0))),
                display=display,
                generated_seed=f"nasa-exoplanet-{host}",
                has_life=False,
                resources={},
                details={
                    "source": "nasa_exoplanet_archive",
                    "source_id": host,
                    "source_epoch": first.get("source_epoch"),
                    "object_role": "real_exoplanet_system",
                    "navigation_order": 40 + index,
                    "distance_from_origin": _display_radius_from_tuple(display) / INTERSTELLAR_DISPLAY_SCALE,
                    "physical_data": bodies[0].details["physical_data"],
                    "position_data": first.get("position_data", {}),
                    "visual_data": {"texture_key": _star_texture_key(first)},
                    "fictional_data": {"generated_features": {}},
                },
                bodies=bodies,
                signals=[],
            )
        )
    return systems_out


def generated_environment_objects(world_seed: str, systems_in: list[SystemSpec], count: int = 10) -> list[EnvironmentObjectSpec]:
    hot_stars = sum(1 for system in systems_in if str(system.details.get("star", {}).get("spectral_type", "")).startswith(("A", "B", "O")))
    density_bonus = min(0.18, len(systems_in) / 200)
    objects = []
    types = ["nebula", "dust_cloud", "anomaly_region"]
    for slot in range(count):
        rng = random.Random(stable_seed(world_seed, "environment", slot))
        object_type = rng.choices(types, weights=[0.52 + hot_stars * 0.02 + density_bonus, 0.34, 0.14], k=1)[0]
        radius = rng.uniform(80, 340)
        theta = rng.uniform(0, math.tau)
        phi = rng.uniform(-0.65, 0.65)
        position = (math.cos(phi) * math.cos(theta) * radius / 18, math.sin(phi) * radius / 18, math.cos(phi) * math.sin(theta) * radius / 18)
        display = (position[0] * 18, position[1] * 18, position[2] * 18)
        nebula_type = _nebula_type(rng, object_type, hot_stars)
        opacity = round(rng.uniform(0.13, 0.36) if object_type != "anomaly_region" else rng.uniform(0.2, 0.46), 2)
        emission_strength = _environment_emission_strength(rng, object_type, nebula_type)
        color_profile = _color_profile(nebula_type, rng)
        details = {
            "source": "generated",
            "nebula_type": nebula_type,
            "color_profile": color_profile,
            "density": round(rng.uniform(0.18, 0.9), 2),
            "opacity": opacity,
            "emission_strength": emission_strength,
            "noise_scale": round(rng.uniform(0.8, 2.6), 2),
            "noise_octaves": rng.randint(3, 7),
            "texture_key": _environment_texture_key(object_type, nebula_type),
            "seed": str(stable_seed(world_seed, "environment", slot)),
            "physical_data": {},
            "position_data": {"interstellar_pc": {"x": position[0], "y": position[1], "z": position[2], "unit": "pc"}},
            "visual_data": {
                "texture_key": _environment_texture_key(object_type, nebula_type),
                "opacity": opacity,
                "emission_strength": emission_strength,
                "color_profile": color_profile,
            },
            "fictional_data": {},
        }
        objects.append(
            EnvironmentObjectSpec(
                id=f"env-{slot:03d}",
                name=_environment_name(rng, object_type, slot),
                object_type=object_type,
                position=position,
                display=display,
                scale=(rng.uniform(18, 52), rng.uniform(10, 34), rng.uniform(18, 56)),
                rotation=(rng.uniform(0, math.tau), rng.uniform(0, math.tau), rng.uniform(0, math.tau)),
                details=details,
            )
        )
    return objects


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-").replace("--", "-")


def _stellar_spectral_hint(obj: dict[str, Any]) -> str:
    teff = obj.get("physical_data", {}).get("stellar_teff_k")
    if not isinstance(teff, int | float):
        return "G"
    if teff >= 10_000:
        return "B"
    if teff >= 7_500:
        return "A"
    if teff >= 6_000:
        return "F"
    if teff >= 5_200:
        return "G"
    if teff >= 3_700:
        return "K"
    return "M"


def _star_texture_key(obj: dict[str, Any]) -> str:
    spectral = _stellar_spectral_hint(obj)
    if spectral in {"A", "B", "O"}:
        return "star_blue_01"
    if spectral in {"K", "M"}:
        return "star_red_01"
    return "star_yellow_01"


def _body_texture_key(body_type: str) -> str:
    return {
        "star": "star_yellow_01",
        "rocky_planet": "rocky_01",
        "terrestrial_planet": "rocky_01",
        "gas_giant": "gas_blue_01",
        "ice_planet": "ice_01",
        "ice_world": "ice_01",
        "ocean_world": "cloudy_01",
        "moon": "moon_01",
        "dwarf_planet": "rocky_01",
        "asteroid": "asteroid_01",
        "comet": "ice_01",
    }.get(body_type, "rocky_01")


def _nebula_type(rng: random.Random, object_type: str, hot_star_count: int) -> str:
    if object_type == "dust_cloud":
        return "dark" if rng.random() < 0.45 else "reflection"
    if object_type == "anomaly_region":
        return "generated_unknown"
    choices = ["emission", "reflection", "dark", "planetary", "supernova_remnant"]
    weights = [0.34 + hot_star_count * 0.03, 0.22, 0.18, 0.14, 0.12]
    return rng.choices(choices, weights=weights, k=1)[0]


def _environment_emission_strength(rng: random.Random, object_type: str, nebula_type: str) -> float:
    if object_type == "anomaly_region":
        return round(rng.uniform(1.1, 2.0), 2)
    if nebula_type == "emission":
        return round(rng.uniform(1.2, 2.1), 2)
    if nebula_type == "reflection":
        return round(rng.uniform(0.45, 1.0), 2)
    if nebula_type == "dark":
        return round(rng.uniform(0.02, 0.18), 2)
    if nebula_type == "supernova_remnant":
        return round(rng.uniform(1.0, 1.8), 2)
    if nebula_type == "planetary":
        return round(rng.uniform(0.8, 1.45), 2)
    return round(rng.uniform(0.3, 0.9), 2)


def _color_profile(nebula_type: str, rng: random.Random | None = None) -> list[str]:
    palettes = {
        "emission": [
            ["#ff5f8f", "#5ee7ff", "#fff1a8"],
            ["#ff8a5b", "#ff4fd8", "#8ae7ff"],
            ["#ff6bd6", "#7df9ff", "#ffe082"],
        ],
        "reflection": [
            ["#8ab4ff", "#dbeafe", "#f8fdff"],
            ["#7dd3fc", "#c4b5fd", "#f8fafc"],
            ["#93c5fd", "#a7f3d0", "#eef6ff"],
        ],
        "dark": [
            ["#090d16", "#172033", "#334155"],
            ["#07111d", "#1b2338", "#374151"],
        ],
        "planetary": [
            ["#7dd3fc", "#86efac", "#f0f9ff"],
            ["#67e8f9", "#c084fc", "#ecfeff"],
        ],
        "supernova_remnant": [
            ["#f97316", "#f43f5e", "#38bdf8"],
            ["#fb7185", "#fde047", "#60a5fa"],
        ],
        "generated_unknown": [
            ["#c084fc", "#22d3ee", "#f8fafc"],
            ["#fb7185", "#60a5fa", "#fde68a"],
            ["#a78bfa", "#34d399", "#f9a8d4"],
        ],
    }
    choices = palettes.get(nebula_type, [["#dbeafe", "#ffffff", "#f8fafc"]])
    if rng is None:
        return choices[0]
    return choices[rng.randrange(len(choices))]


def _environment_texture_key(object_type: str, nebula_type: str) -> str:
    if object_type == "anomaly_region":
        return "anomaly_plasma_01"
    if object_type == "dust_cloud" or nebula_type == "dark":
        return "dust_grunge_01"
    return "nebula_fbm_01"


def _environment_name(rng: random.Random, object_type: str, slot: int) -> str:
    prefix = {"nebula": "Veil", "dust_cloud": "Mote", "anomaly_region": "Null"}[object_type]
    return f"{prefix}-{slot + 1:02d}-{rng.randint(100, 999)}"


def outer_terminus(world_seed: str) -> SystemSpec:
    seed = stable_seed(world_seed, "outer-terminus")
    return SystemSpec(
        id="sys-outer-terminus",
        name="白端航路標",
        position=(14.0, 7.0, -4.0),
        display=(185.0, 92.0, -58.0),
        generated_seed=str(seed),
        has_life=False,
        resources={"unknown_reflective_ice": 4.0},
        details={
            "star": {"name": "白端航路標", "spectral_type": "A", "fictional": True},
            "object_role": "far_objective",
            "navigation_order": 99,
            "description": "地球圏から見て外縁方向に置かれた、白く強い航路目標",
        },
        bodies=[
            BodySpec(
                id="outer-terminus-star",
                name="白端航路標 主星",
                body_type="star",
                orbit_radius_km=None,
                radius_km=1_100_000,
                sim=(14.0, 7.0, -4.0),
                display=(185.0, 92.0, -58.0),
                display_radius=2.2,
                details={"spectral_type": "A", "fictional": True},
            )
        ],
        signals=[
            SignalSpec(
                id="signal-outer-terminus-1",
                kind="distant_navigation_pulse",
                strength=0.38,
                position=(14.0, 7.0, -4.0),
                display=(185.0, 94.0, -58.0),
                body_id="outer-terminus-star",
                details={"frequency": "0.72GHz", "periodic": True},
            )
        ],
    )


def solar_system() -> SystemSpec:
    cached = real_solar_system()
    if cached is not None:
        return cached
    bodies = [
        BodySpec("sun", "太陽", "star", None, 696_340, (0, 0, 0), (0, 0, 0), 2.4, {"spectral_type": "G2V", "visual_data": {"texture_key": "star_yellow_01"}}),
        BodySpec("earth", "地球", "terrestrial_planet", 149_600_000, 6_371, (1, 0.03, 0.17), (7.0, 0.4, 1.2), 0.55, {"atmosphere": "nitrogen_oxygen", "visual_data": {"texture_key": "cloudy_01"}}),
        BodySpec("mars", "火星", "terrestrial_planet", 227_900_000, 3_389.5, (1.52, -0.09, -0.34), (9.5, -0.6, -2.2), 0.42, {"atmosphere": "thin_co2", "visual_data": {"texture_key": "rocky_01"}}),
        BodySpec("jupiter", "木星", "gas_giant", 778_500_000, 69_911, (5.2, 0.31, 0.88), (17.0, 1.1, 3.5), 1.2, {"atmosphere": "hydrogen_helium", "visual_data": {"texture_key": "gas_blue_01"}}),
    ]
    return SystemSpec(
        id="sol",
        name="太陽系",
        position=(0, 0, 0),
        display=(0, 0, 0),
        generated_seed="fixed-sol",
        has_life=True,
        resources={"water_ice": 12.0, "silicates": 40.0},
        details={
            "star": {"name": "太陽", "mass_solar": 1.0},
            "object_role": "origin",
            "navigation_order": 0,
            "source": "manual",
            "visual_data": {"texture_key": "star_yellow_01"},
            "fictional_data": {"generated_features": {"resources": {"water_ice": 12.0, "silicates": 40.0}}},
        },
        bodies=bodies,
        signals=[
            SignalSpec(
                "signal-sol-001",
                "radio_beacon",
                0.72,
                (1.01, 0.03, 0.17),
                (7.2, 0.8, 1.5),
                "earth",
                {"source": "generated", "fictional_data": {"frequency": "1420MHz", "pattern": "terrestrial calibration"}},
            ),
        ],
    )


def _manual_solar_body(
    *,
    body_id: str,
    name: str,
    body_type: str,
    radius_km: float,
    orbit_au: float,
    angle: float,
    y_offset: float = 0.0,
    z_wave: float = 0.0,
    extra_details: dict[str, Any] | None = None,
) -> BodySpec:
    x = orbit_au * math.cos(angle)
    z = orbit_au * math.sin(angle) + z_wave
    sim = (x, y_offset, z)
    display = _solar_display_from_state(x, y_offset, z)
    details = {
        "source": "manual",
        "physical_data": {"radius_km": radius_km},
        "position_data": {
            "orbit_au": orbit_au,
            "solar_system_au": {"x": x, "y": y_offset, "z": z, "vx": 0.0, "vy": 0.0, "vz": 0.0, "unit": "AU"},
        },
        "visual_data": _solar_visual_data(body_id, body_type),
        "fictional_data": {},
    }
    if extra_details:
        details.update(extra_details)
    return BodySpec(
        id=body_id,
        name=name,
        body_type=body_type,
        orbit_radius_km=None if orbit_au == 0 else orbit_au * 149_597_870.7,
        radius_km=radius_km,
        sim=sim,
        display=display,
        display_radius=_solar_display_radius(radius_km),
        details=details,
    )


def _manual_solar_system() -> SystemSpec:
    bodies = [
        _manual_solar_body(body_id="sun", name="Sun", body_type="star", radius_km=696_340, orbit_au=0.0, angle=0.0, extra_details={"spectral_type": "G2V"}),
        _manual_solar_body(body_id="mercury", name="Mercury", body_type="rocky_planet", radius_km=2_439.7, orbit_au=0.387, angle=0.42, y_offset=0.01),
        _manual_solar_body(body_id="venus", name="Venus", body_type="rocky_planet", radius_km=6_051.8, orbit_au=0.723, angle=1.28, y_offset=0.02),
        _manual_solar_body(body_id="earth", name="Earth", body_type="terrestrial_planet", radius_km=6_371.0, orbit_au=1.0, angle=2.12, y_offset=0.03, extra_details={"atmosphere": "nitrogen_oxygen"}),
        _manual_solar_body(body_id="moon", name="Moon", body_type="moon", radius_km=1_737.4, orbit_au=1.026, angle=2.32, y_offset=0.036),
        _manual_solar_body(body_id="mars", name="Mars", body_type="terrestrial_planet", radius_km=3_389.5, orbit_au=1.524, angle=2.86, y_offset=-0.02, extra_details={"atmosphere": "thin_co2"}),
        _manual_solar_body(body_id="jupiter", name="Jupiter", body_type="gas_giant", radius_km=69_911.0, orbit_au=5.203, angle=0.88, y_offset=0.05),
        _manual_solar_body(body_id="saturn", name="Saturn", body_type="gas_giant", radius_km=58_232.0, orbit_au=9.537, angle=1.46, y_offset=0.07),
        _manual_solar_body(body_id="uranus", name="Uranus", body_type="ice_planet", radius_km=25_362.0, orbit_au=19.191, angle=2.38, y_offset=-0.08),
        _manual_solar_body(body_id="neptune", name="Neptune", body_type="ice_planet", radius_km=24_622.0, orbit_au=30.07, angle=3.14, y_offset=0.09),
    ]
    earth = next(body for body in bodies if body.id == "earth")
    return SystemSpec(
        id="sol",
        name="Solar System",
        position=(0, 0, 0),
        display=(0, 0, 0),
        generated_seed="fixed-sol",
        has_life=True,
        resources={"water_ice": 12.0, "silicates": 40.0},
        details={
            "star": {"name": "Sun", "mass_solar": 1.0, "spectral_type": "G2V"},
            "object_role": "origin",
            "navigation_order": 0,
            "source": "manual",
            "physical_data": {"radius_km": 696_340},
            "position_data": {"coordinate_system": "solar_system_au"},
            "visual_data": {"texture_key": "star_yellow_01", "emissive": "#ffd166", "emission_strength": 1.35},
            "fictional_data": {"generated_features": {"resources": {"water_ice": 12.0, "silicates": 40.0}}},
        },
        bodies=bodies,
        signals=[
            SignalSpec(
                "signal-sol-001",
                "radio_beacon",
                0.72,
                earth.sim,
                (earth.display[0] + 0.22, earth.display[1] + 0.12, earth.display[2] + 0.18),
                "earth",
                {"source": "generated", "fictional_data": {"frequency": "1420MHz", "pattern": "terrestrial calibration"}},
            ),
        ],
    )


def solar_system() -> SystemSpec:
    cached = real_solar_system()
    if cached is not None:
        return cached
    return _manual_solar_system()


def _seeded_waypoints(world_seed: str) -> list[SystemSpec]:
    waypoint_defs = [
        ("outer-solar-marker", "白端航路標", (1.9, -0.28, 0.22), 1),
        ("heliopause-gate", "ヘリオポーズ境界", (3.2, 0.42, -0.36), 2),
        ("interstellar-corridor", "星間回廊入口", (5.1, 0.9, 0.72), 3),
    ]
    waypoints: list[SystemSpec] = []
    for waypoint_id, name, local, order in waypoint_defs:
        position = _orient_local(world_seed, local[0], local[1], local[2])
        display = (position[0] * 18, position[1] * 18, position[2] * 18)
        waypoints.append(navigation_waypoint(waypoint_id, name, position, display, order))
    return waypoints


def _seeded_nearby_coordinates(world_seed: str) -> list[tuple[float, float, float]]:
    local_points = [
        (3.3, 2.4, -2.1),
        (4.8, -2.6, 2.9),
        (6.1, 1.4, 4.3),
    ]
    return [_orient_local(world_seed, radial, lateral, vertical) for radial, lateral, vertical in local_points]


def _seeded_outer_terminus(world_seed: str) -> SystemSpec:
    seed = stable_seed(world_seed, "outer-terminus")
    position = _orient_local(world_seed, 14.0, -4.0, 7.0)
    display = (position[0] * 18, position[1] * 18, position[2] * 18)
    return SystemSpec(
        id="sys-outer-terminus",
        name="白端航路終点",
        position=position,
        display=display,
        generated_seed=str(seed),
        has_life=False,
        resources={"unknown_reflective_ice": 4.0},
        details={
            "star": {"name": "白端航路終点", "spectral_type": "A", "fictional": True},
            "object_role": "far_objective",
            "navigation_order": 99,
            "description": "外向き主航路の長距離ビーコンとして使われる遠方目標。",
            "visual_data": {"texture_key": "star_blue_01", "emissive": "#dbeafe", "emission_strength": 1.2},
            "fictional_data": {},
        },
        bodies=[
            BodySpec(
                id="outer-terminus-star",
                name="白端航路終点 主星",
                body_type="star",
                orbit_radius_km=None,
                radius_km=1_100_000,
                sim=position,
                display=display,
                display_radius=2.2,
                details={"spectral_type": "A", "fictional": True, "visual_data": {"texture_key": "star_blue_01"}},
            )
        ],
        signals=[
            SignalSpec(
                id="signal-outer-terminus-1",
                kind="distant_navigation_pulse",
                strength=0.38,
                position=position,
                display=(display[0], display[1] + 2.0, display[2]),
                body_id="outer-terminus-star",
                details={"frequency": "0.72GHz", "periodic": True},
            )
        ],
    )


def _seeded_waypoints(world_seed: str) -> list[SystemSpec]:
    waypoint_defs = [
        ("outer-solar-marker", "外縁航路標", (1.9, -0.28, 0.22), 1),
        ("heliopause-gate", "ヘリオポーズ境界", (3.2, 0.42, -0.36), 2),
        ("interstellar-corridor", "星間回廊入口", (5.1, 0.9, 0.72), 3),
    ]
    waypoints: list[SystemSpec] = []
    for waypoint_id, name, local, order in waypoint_defs:
        position = _orient_local(world_seed, local[0], local[1], local[2])
        display = (position[0] * 18, position[1] * 18, position[2] * 18)
        waypoints.append(navigation_waypoint(waypoint_id, name, position, display, order))
    return waypoints


def _seeded_outer_terminus(world_seed: str) -> SystemSpec:
    seed = stable_seed(world_seed, "outer-terminus")
    position = _orient_local(world_seed, 14.0, -4.0, 7.0)
    display = (position[0] * 18, position[1] * 18, position[2] * 18)
    return SystemSpec(
        id="sys-outer-terminus",
        name="外縁灯台",
        position=position,
        display=display,
        generated_seed=str(seed),
        has_life=False,
        resources={"unknown_reflective_ice": 4.0},
        details={
            "star": {"name": "外縁灯台", "spectral_type": "A", "fictional": True},
            "object_role": "far_objective",
            "navigation_order": 99,
            "description": "太陽系外縁の主航路ビーコンとして使われる遠方目標。",
            "visual_data": {"texture_key": "star_blue_01", "emissive": "#dbeafe", "emission_strength": 1.2},
            "fictional_data": {},
        },
        bodies=[
            BodySpec(
                id="outer-terminus-star",
                name="外縁灯台 主星",
                body_type="star",
                orbit_radius_km=None,
                radius_km=1_100_000,
                sim=position,
                display=display,
                display_radius=2.2,
                details={"spectral_type": "A", "fictional": True, "visual_data": {"texture_key": "star_blue_01"}},
            )
        ],
        signals=[
            SignalSpec(
                id="signal-outer-terminus-1",
                kind="distant_navigation_pulse",
                strength=0.38,
                position=position,
                display=(display[0], display[1] + 2.0, display[2]),
                body_id="outer-terminus-star",
                details={"frequency": "0.72GHz", "periodic": True},
            )
        ],
    )


def generate_world(world_seed: str) -> list[SystemSpec]:
    coordinates = [(3, 1, -2), (4, -2, 3), (6, 2, 1)]
    nearby = [fictional_system(world_seed, i + 1, coord) for i, coord in enumerate(coordinates)]
    waypoints = [
        navigation_waypoint("outer-solar-marker", "外惑星航路標", (1.9, 0.22, -0.28), (26.0, 3.4, -5.2), 1),
        navigation_waypoint("heliopause-gate", "ヘリオポーズ境界", (3.2, -0.48, 0.38), (46.0, -7.5, 7.2), 2),
        navigation_waypoint("interstellar-corridor", "星間回廊入口", (5.1, 0.9, 0.72), (72.0, 15.5, 12.0), 3),
    ]
    return [solar_system(), *waypoints, *real_exoplanet_systems(), *nearby, outer_terminus(world_seed)]


def generate_world(world_seed: str) -> list[SystemSpec]:
    nearby = [fictional_system(world_seed, i + 1, coord) for i, coord in enumerate(_seeded_nearby_coordinates(world_seed))]
    waypoints = _seeded_waypoints(world_seed)
    return [solar_system(), *waypoints, *real_exoplanet_systems(), *nearby, _seeded_outer_terminus(world_seed)]
