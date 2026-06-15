import hashlib
import random
from dataclasses import dataclass, field
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


def stable_seed(*parts: object) -> int:
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def solar_system() -> SystemSpec:
    bodies = [
        BodySpec("sun", "太陽", "star", None, 696_340, (0, 0, 0), (0, 0, 0), 2.4, {"spectral_type": "G2V"}),
        BodySpec("earth", "地球", "terrestrial_planet", 149_600_000, 6_371, (1, 0, 0), (7, 0, 0), 0.55, {"atmosphere": "nitrogen_oxygen"}),
        BodySpec("mars", "火星", "terrestrial_planet", 227_900_000, 3_389.5, (1.52, 0, 0), (10, 0, 0), 0.42, {"atmosphere": "thin_co2"}),
        BodySpec("jupiter", "木星", "gas_giant", 778_500_000, 69_911, (5.2, 0, 0), (18, 0, 0), 1.2, {"atmosphere": "hydrogen_helium"}),
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
            SignalSpec("signal-sol-001", "radio_beacon", 0.72, (1.01, 0.02, 0), (7.2, 0.3, 0), "earth", {"frequency": "1420MHz", "pattern": "terrestrial calibration"}),
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
            details={"spectral_type": rng.choice(["K", "G", "M", "F"]), "fictional": True},
        )
    ]
    for planet_index in range(planet_count):
        orbit = 60_000_000 + planet_index * rng.uniform(45_000_000, 120_000_000)
        dx = (planet_index + 1) * 1.8
        body_id = f"{name.lower()}-{planet_index + 1}"
        bodies.append(
            BodySpec(
                id=body_id,
                name=f"{name}-{planet_index + 1}",
                body_type=rng.choice(["rocky_planet", "ice_world", "gas_giant", "ocean_world"]),
                orbit_radius_km=orbit,
                radius_km=rng.uniform(2_100, 55_000),
                sim=(x + dx, y, z),
                display=(display[0] + dx * 2.3, display[1] + rng.uniform(-2, 2), display[2] + rng.uniform(-2, 2)),
                display_radius=rng.uniform(0.35, 1.0),
                details={"surface_temperature_k": round(rng.uniform(80, 520), 1)},
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


def generate_world(world_seed: str) -> list[SystemSpec]:
    coordinates = [(3, 1, -1), (5, 3, -2), (7, 4, -3)]
    nearby = [fictional_system(world_seed, i + 1, coord) for i, coord in enumerate(coordinates)]
    waypoints = [
        navigation_waypoint("outer-solar-marker", "外惑星航路標", (1.9, 0.15, -0.05), (26.0, 2.2, -1.0), 1),
        navigation_waypoint("heliopause-gate", "ヘリオポーズ境界", (3.2, 0.55, -0.18), (46.0, 8.0, -3.5), 2),
        navigation_waypoint("interstellar-corridor", "星間回廊入口", (5.1, 1.2, -0.55), (72.0, 18.0, -8.0), 3),
    ]
    return [solar_system(), *waypoints, *nearby, outer_terminus(world_seed)]
