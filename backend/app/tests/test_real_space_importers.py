import json

from app.importers.normalize import normalize_exoplanet_row, normalize_horizons_vector
from app.world import generator


HORIZONS_SAMPLE = """
$$SOE
 2026-Jun-16 00:00:00.0000 TDB
 X = 1.234000000000000E+00 Y =-2.500000000000000E-01 Z = 3.000000000000000E-02
 VX= 1.000000000000000E-03 VY=-2.000000000000000E-03 VZ= 3.000000000000000E-04
$$EOE
"""


def test_horizons_vector_normalization_separates_real_and_fictional_data() -> None:
    item = normalize_horizons_vector(
        body_id="mars",
        name="火星",
        object_type="rocky_planet",
        source_id="499",
        result_text=HORIZONS_SAMPLE,
        physical_data={"radius_km": 3389.5},
        visual_data={"texture_key": "rocky_01"},
    )
    assert item.source == "jpl_horizons"
    assert item.position_data["solar_system_au"]["x"] == 1.234
    assert item.position_data["solar_system_au"]["vy"] == -0.002
    assert item.physical_data["radius_km"] == 3389.5
    assert item.visual_data["texture_key"] == "rocky_01"
    assert item.fictional_data == {}


def test_exoplanet_normalization_filters_100_light_years_and_computes_pc_coordinates() -> None:
    row = {
        "pl_name": "Example b",
        "hostname": "Example",
        "ra": 0,
        "dec": 0,
        "sy_dist": 10,
        "pl_rade": 1.2,
        "pl_masse": 2.0,
        "pl_orbsmax": 0.8,
        "st_teff": 5800,
        "releasedate": "2026-01-01",
    }
    item = normalize_exoplanet_row(row)
    assert item is not None
    assert item.source == "nasa_exoplanet_archive"
    assert item.position_data["interstellar_pc"]["x"] == 10
    assert item.position_data["interstellar_pc"]["y"] == 0
    assert item.object_type == "rocky_planet"
    assert item.fictional_data == {}
    assert normalize_exoplanet_row({**row, "sy_dist": 40}) is None


def test_world_uses_real_solar_cache_when_available(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "solar_system.json"
    cache.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "jpl_horizons",
                "source_epoch": "2026-06-16",
                "objects": [
                    {
                        "id": "earth",
                        "name": "地球",
                        "object_type": "rocky_planet",
                        "source": "jpl_horizons",
                        "source_id": "399",
                        "source_epoch": "2026-06-16",
                        "physical_data": {"radius_km": 6371},
                        "position_data": {"solar_system_au": {"x": 1, "y": 0.1, "z": 0.2, "vx": 0, "vy": 0, "vz": 0}},
                        "visual_data": {"texture_key": "rocky_01"},
                        "fictional_data": {},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(generator, "SOLAR_SYSTEM_CACHE", cache)
    monkeypatch.setattr(generator, "EXOPLANET_CACHE", tmp_path / "missing-exoplanets.json")
    world = generator.generate_world("real-cache-test")
    sol = next(item for item in world if item.id == "sol")
    earth = next(body for body in sol.bodies if body.id == "earth")
    assert sol.details["source"] == "jpl_horizons"
    assert earth.details["source"] == "jpl_horizons"
    assert earth.details["position_data"]["solar_system_au"]["x"] == 1


def test_environment_objects_are_seeded_and_have_visual_data() -> None:
    world = generator.generate_world("env-seed")
    first = generator.generated_environment_objects("env-seed", world)
    second = generator.generated_environment_objects("env-seed", world)
    assert [(item.id, item.display, item.details["texture_key"]) for item in first] == [
        (item.id, item.display, item.details["texture_key"]) for item in second
    ]
    assert {item.object_type for item in first} <= {"nebula", "dust_cloud", "anomaly_region"}
    assert all(item.details["source"] == "generated" for item in first)
