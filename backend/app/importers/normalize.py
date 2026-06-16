import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

LIGHT_YEARS_PER_PC = 3.261563777
MAX_NEARBY_DISTANCE_PC = 100.0 / LIGHT_YEARS_PER_PC


@dataclass(frozen=True)
class RealSpaceObject:
    id: str
    name: str
    object_type: str
    source: str
    source_id: str
    source_epoch: str | None
    physical_data: dict[str, Any] = field(default_factory=dict)
    position_data: dict[str, Any] = field(default_factory=dict)
    visual_data: dict[str, Any] = field(default_factory=dict)
    fictional_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def split_real_and_fictional(
    *,
    physical_data: dict[str, Any] | None = None,
    position_data: dict[str, Any] | None = None,
    visual_data: dict[str, Any] | None = None,
    fictional_data: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    return physical_data or {}, position_data or {}, visual_data or {}, fictional_data or {}


def equatorial_to_cartesian_pc(ra_deg: float, dec_deg: float, distance_pc: float) -> dict[str, float]:
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    x = distance_pc * math.cos(dec) * math.cos(ra)
    y = distance_pc * math.sin(dec)
    z = distance_pc * math.cos(dec) * math.sin(ra)
    return {"x": x, "y": y, "z": z, "unit": "pc", "frame": "heliocentric_equatorial"}


def normalize_exoplanet_row(row: dict[str, Any]) -> RealSpaceObject | None:
    distance_pc = _float(row.get("sy_dist"))
    ra_deg = _float(row.get("ra"))
    dec_deg = _float(row.get("dec"))
    planet_name = str(row.get("pl_name") or "").strip()
    hostname = str(row.get("hostname") or "").strip()
    if not planet_name or not hostname or distance_pc is None or ra_deg is None or dec_deg is None:
        return None
    if distance_pc > MAX_NEARBY_DISTANCE_PC:
        return None
    physical_data, position_data, visual_data, fictional_data = split_real_and_fictional(
        physical_data={
            "hostname": hostname,
            "planet_radius_earth": _float(row.get("pl_rade")),
            "planet_mass_earth": _float(row.get("pl_masse")),
            "best_mass_jupiter": _float(row.get("pl_bmassj")),
            "orbital_period_days": _float(row.get("pl_orbper")),
            "semi_major_axis_au": _float(row.get("pl_orbsmax")),
            "stellar_teff_k": _float(row.get("st_teff")),
            "stellar_radius_solar": _float(row.get("st_rad")),
            "stellar_mass_solar": _float(row.get("st_mass")),
            "system_distance_pc": distance_pc,
            "system_distance_ly": distance_pc * LIGHT_YEARS_PER_PC,
        },
        position_data={
            "interstellar_pc": equatorial_to_cartesian_pc(ra_deg, dec_deg, distance_pc),
            "ra_deg": ra_deg,
            "dec_deg": dec_deg,
        },
        visual_data={"texture_key": _planet_texture_key(row), "display_scale": "interstellar"},
        fictional_data={},
    )
    return RealSpaceObject(
        id=f"nea-{_slug(planet_name)}",
        name=planet_name,
        object_type=_planet_object_type(row),
        source="nasa_exoplanet_archive",
        source_id=planet_name,
        source_epoch=str(row.get("releasedate") or row.get("rowupdate") or ""),
        physical_data=physical_data,
        position_data=position_data,
        visual_data=visual_data,
        fictional_data=fictional_data,
    )


def normalize_horizons_vector(
    *,
    body_id: str,
    name: str,
    object_type: str,
    source_id: str,
    result_text: str,
    visual_data: dict[str, Any] | None = None,
    physical_data: dict[str, Any] | None = None,
) -> RealSpaceObject:
    vector = parse_horizons_vector_text(result_text)
    real_physical, real_position, real_visual, fictional_data = split_real_and_fictional(
        physical_data=physical_data,
        position_data={
            "solar_system_au": {
                "x": vector["x"],
                "y": vector["y"],
                "z": vector["z"],
                "vx": vector["vx"],
                "vy": vector["vy"],
                "vz": vector["vz"],
                "unit": "AU-D",
                "frame": "heliocentric_ecliptic",
            }
        },
        visual_data=visual_data or {},
        fictional_data={},
    )
    return RealSpaceObject(
        id=body_id,
        name=name,
        object_type=object_type,
        source="jpl_horizons",
        source_id=source_id,
        source_epoch=vector["epoch"],
        physical_data=real_physical,
        position_data=real_position,
        visual_data=real_visual,
        fictional_data=fictional_data,
    )


def parse_horizons_vector_text(text: str) -> dict[str, float | str]:
    if "$$SOE" in text and "$$EOE" in text:
        text = text.split("$$SOE", 1)[1].split("$$EOE", 1)[0]
    epoch_match = re.search(r"(\d{4}-[A-Za-z]{3}-\d{2}|\d{4}-\d{2}-\d{2}|JDTDB\s*=\s*[-+0-9.]+)", text)
    values = {key.lower(): _extract_vector_value(text, key) for key in ("X", "Y", "Z", "VX", "VY", "VZ")}
    missing = [key for key, value in values.items() if value is None]
    if missing:
        raise ValueError(f"Horizons vector response is missing fields: {', '.join(missing)}")
    return {
        "epoch": epoch_match.group(0) if epoch_match else "",
        "x": values["x"],
        "y": values["y"],
        "z": values["z"],
        "vx": values["vx"],
        "vy": values["vy"],
        "vz": values["vz"],
    }


def _extract_vector_value(text: str, key: str) -> float | None:
    match = re.search(rf"\b{key}\s*=\s*([-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?)", text)
    return float(match.group(1)) if match else None


def _planet_object_type(row: dict[str, Any]) -> str:
    radius = _float(row.get("pl_rade"))
    mass_jupiter = _float(row.get("pl_bmassj"))
    if mass_jupiter is not None and mass_jupiter >= 0.25:
        return "gas_giant"
    if radius is None:
        return "rocky_planet"
    if radius >= 6:
        return "gas_giant"
    if radius >= 2.2:
        return "ice_planet"
    return "rocky_planet"


def _planet_texture_key(row: dict[str, Any]) -> str:
    object_type = _planet_object_type(row)
    if object_type == "gas_giant":
        return "gas_blue_01"
    if object_type == "ice_planet":
        return "ice_01"
    return "rocky_01"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
