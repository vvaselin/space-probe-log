from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from app.importers.normalize import RealSpaceObject, normalize_horizons_vector

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"


@dataclass(frozen=True)
class HorizonsBody:
    id: str
    name: str
    object_type: str
    command: str
    radius_km: float
    texture_key: str


MAJOR_BODIES = [
    HorizonsBody("sun", "太陽", "star", "10", 696_340, "star_yellow_01"),
    HorizonsBody("mercury", "水星", "rocky_planet", "199", 2_439.7, "rocky_01"),
    HorizonsBody("venus", "金星", "rocky_planet", "299", 6_051.8, "rocky_01"),
    HorizonsBody("earth", "地球", "rocky_planet", "399", 6_371.0, "rocky_01"),
    HorizonsBody("moon", "月", "moon", "301", 1_737.4, "moon_01"),
    HorizonsBody("mars", "火星", "rocky_planet", "499", 3_389.5, "rocky_01"),
    HorizonsBody("jupiter", "木星", "gas_giant", "599", 69_911, "gas_blue_01"),
    HorizonsBody("saturn", "土星", "gas_giant", "699", 58_232, "gas_blue_01"),
    HorizonsBody("uranus", "天王星", "ice_planet", "799", 25_362, "ice_01"),
    HorizonsBody("neptune", "海王星", "ice_planet", "899", 24_622, "ice_01"),
]


async def fetch_solar_system_vectors(epoch: str) -> list[RealSpaceObject]:
    async with httpx.AsyncClient(timeout=45) as client:
        tasks = [_fetch_body(client, body, epoch) for body in MAJOR_BODIES]
        return await asyncio.gather(*tasks)


async def _fetch_body(client: httpx.AsyncClient, body: HorizonsBody, epoch: str) -> RealSpaceObject:
    response = await client.get(HORIZONS_URL, params=_horizons_params(body.command, epoch))
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    return normalize_horizons_vector(
        body_id=body.id,
        name=body.name,
        object_type=body.object_type,
        source_id=body.command,
        result_text=str(data.get("result", "")),
        physical_data={"radius_km": body.radius_km},
        visual_data={"texture_key": body.texture_key, "display_scale": "solar_system"},
    )


def _horizons_params(command: str, epoch: str) -> dict[str, str]:
    return {
        "format": "json",
        "COMMAND": command,
        "OBJ_DATA": "YES",
        "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "VECTORS",
        "CENTER": "500@10",
        "START_TIME": epoch,
        "STOP_TIME": epoch,
        "STEP_SIZE": "1",
        "OUT_UNITS": "AU-D",
        "CSV_FORMAT": "NO",
        "REF_PLANE": "ECLIPTIC",
        "REF_SYSTEM": "ICRF",
        "VEC_TABLE": "3",
        "VEC_LABELS": "YES",
    }
