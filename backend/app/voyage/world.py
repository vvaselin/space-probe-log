"""世界データ（4章）。行き先の共通の型と、時刻ごとの位置。"""

from __future__ import annotations

import json
import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.voyage.orbits import AU_KM, Vec3, add, cross, days_since, kepler_position, scale

DATA_PATH = Path(__file__).resolve().parent / "data" / "solar_system.json"

DestinationKind = Literal["body", "star_system", "region", "waypoint"]
Realism = Literal["real", "estimated", "fictional", "unknown"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class JplPlanetOrbit(_Frozen):
    """JPL 近似軌道要素 表2a/2b（紀元前3000年〜西暦3000年）。各要素は (J2000の値, 1世紀あたりの変化)。"""

    kind: Literal["jpl_planet"]
    a: tuple[float, float]
    e: tuple[float, float]
    i: tuple[float, float]
    mean_longitude: tuple[float, float]
    long_perihelion: tuple[float, float]
    long_node: tuple[float, float]
    b: float = 0.0
    c: float = 0.0
    s: float = 0.0
    f: float = 0.0


class KeplerOrbit(_Frozen):
    """ある時刻の接触軌道要素（JPL Horizons）。"""

    kind: Literal["kepler"]
    epoch: datetime
    a_au: float
    e: float
    i_deg: float
    node_deg: float
    peri_deg: float
    mean_anomaly_deg: float
    mean_motion_deg_per_day: float


class CircularOrbit(_Frozen):
    """母天体を中心にした円軌道。r0 は epoch の向き、normal は軌道面の法線（どちらも単位ベクトル）。"""

    kind: Literal["circular"]
    epoch: datetime
    orbit_radius_km: float
    period_days: float
    r0: Vec3
    normal: Vec3


class FixedOrbit(_Frozen):
    kind: Literal["fixed"]
    position_au: Vec3 = (0.0, 0.0, 0.0)


Orbit = Annotated[JplPlanetOrbit | KeplerOrbit | CircularOrbit | FixedOrbit, Field(discriminator="kind")]


class Rings(_Frozen):
    prominent: bool
    description: str


class Visual(_Frozen):
    colors: list[str]
    pattern: str
    albedo: float
    atmosphere: bool = False
    rings: Rings | None = None
    moon_count: int = 0
    pole_ra_dec: tuple[float, float] | None = None
    spectral_type: str | None = None


class Destination(_Frozen):
    id: str
    name: str
    kind: DestinationKind = "body"
    subtype: str
    realism: Realism = "real"
    radius_km: float
    parent_id: str | None = None
    orbit: Orbit
    visual: Visual
    highlight: float = Field(default=0.0, ge=0.0, le=1.0)
    abs_magnitude: float | None = None


class Milestone(_Frozen):
    id: str
    name: str
    r_au: float


class World(_Frozen):
    destinations: dict[str, Destination]
    milestones: list[Milestone]

    def get(self, dest_id: str) -> Destination:
        try:
            return self.destinations[dest_id]
        except KeyError as exc:
            raise KeyError(f"unknown destination id: {dest_id}") from exc

    def children(self, parent_id: str) -> list[Destination]:
        return [d for d in self.destinations.values() if d.parent_id == parent_id]


@lru_cache
def load_world(path: Path = DATA_PATH) -> World:
    raw = json.loads(path.read_text(encoding="utf-8"))
    destinations = [Destination.model_validate(item) for item in raw["destinations"]]
    ids = [d.id for d in destinations]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate destination ids in {path}")
    world = World(destinations={d.id: d for d in destinations}, milestones=raw["milestones"])
    for d in destinations:
        if d.parent_id is not None:
            world.get(d.parent_id)
    return world


def position_au(world: World, dest: Destination, t: datetime) -> Vec3:
    orbit = dest.orbit
    if isinstance(orbit, FixedOrbit):
        return orbit.position_au
    if isinstance(orbit, JplPlanetOrbit):
        cy = days_since(t) / 36525.0

        def at(pair: tuple[float, float]) -> float:
            return pair[0] + pair[1] * cy

        long_peri, node = at(orbit.long_perihelion), at(orbit.long_node)
        f_rad = math.radians(orbit.f * cy)
        mean_anomaly = (
            at(orbit.mean_longitude) - long_peri + orbit.b * cy * cy + orbit.c * math.cos(f_rad) + orbit.s * math.sin(f_rad)
        )
        return kepler_position(at(orbit.a), at(orbit.e), at(orbit.i), node, long_peri - node, mean_anomaly)
    if isinstance(orbit, KeplerOrbit):
        mean_anomaly = orbit.mean_anomaly_deg + orbit.mean_motion_deg_per_day * days_since(t, orbit.epoch)
        return kepler_position(orbit.a_au, orbit.e, orbit.i_deg, orbit.node_deg, orbit.peri_deg, mean_anomaly)
    if dest.parent_id is None:
        raise ValueError(f"circular orbit needs a parent: {dest.id}")
    center = position_au(world, world.get(dest.parent_id), t)
    theta = 2 * math.pi * days_since(t, orbit.epoch) / orbit.period_days
    side = cross(orbit.normal, orbit.r0)
    offset = add(scale(orbit.r0, math.cos(theta)), scale(side, math.sin(theta)))
    return add(center, scale(offset, orbit.orbit_radius_km / AU_KM))
