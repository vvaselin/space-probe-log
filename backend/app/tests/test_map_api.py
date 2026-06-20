from fastapi.testclient import TestClient
import pytest

import app.api.simulation as simulation_api
from app.core.config import get_settings
from app.llm.mock import MockLLMClient
from app.main import app
from app.services.auth import require_admin


@pytest.fixture(autouse=True)
def admin_api_override():
    settings = get_settings()
    previous_scheduler_enabled = settings.simulation_scheduler_enabled
    settings.simulation_scheduler_enabled = False
    app.dependency_overrides[require_admin] = lambda: None
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_admin, None)
        settings.simulation_scheduler_enabled = previous_scheduler_enabled


def test_map_contains_dynamic_frontier_and_distant_stars() -> None:
    with TestClient(app) as client:
        client.post("/api/simulation/reset", json={"world_seed": "map-test"})
        payload = client.get("/api/world/map").json()
    assert not any(system["object_role"] == "far_objective" for system in payload["systems"])
    assert any(system["object_role"] == "frontier_system" for system in payload["systems"])
    assert any(system["object_role"] == "navigation_waypoint" for system in payload["systems"])
    assert len(payload["distant_stars"]) >= 100
    assert len(payload["environment_objects"]) >= 3
    assert all(item["source"] == "generated" for item in payload["environment_objects"])
    assert payload["map_origin"]["id"] == "earth"
    assert payload["probe"]["specification"]["length_m"] == 18
    assert next(body for body in payload["bodies"] if body["id"] == "earth")["physical_radius_km"] == 6371.0
    assert next(signal for signal in payload["signals"] if signal["id"] == "signal-sol-001")["body_id"] == "earth"


def test_world_reset_starts_with_paused_clock() -> None:
    with TestClient(app) as client:
        client.post("/api/simulation/reset", json={"world_seed": "paused-reset"})
        clock = client.get("/api/simulation/clock").json()
    assert clock["clock_state"] == "paused"
    assert clock["time_scale"] > 0


def test_map_exposes_compact_small_body_layers() -> None:
    with TestClient(app) as client:
        client.post("/api/simulation/reset", json={"world_seed": "small-body-map"})
        payload = client.get("/api/world/map").json()
    assert [item["layer_type"] for item in payload["small_body_layers"]] == ["asteroid_belt", "comet_population", "oort_cloud"]
    assert all("positions" not in item for item in payload["small_body_layers"])


def test_map_includes_route_prediction_while_probe_is_underway(monkeypatch) -> None:
    monkeypatch.setattr(simulation_api, "get_llm_client", lambda: MockLLMClient())
    with TestClient(app) as client:
        client.post("/api/simulation/reset", json={"world_seed": "map-test"})
        client.post("/api/simulation/step")
        client.post("/api/simulation/step")
        client.post("/api/simulation/step")
        payload = client.get("/api/world/map").json()
    assert payload["probe"]["system_id"] in {"sol", "outer-solar-marker"}
    if payload["probe"]["target_id"] is not None:
        assert payload["route_prediction"]["target_id"] == payload["probe"]["target_id"]
    else:
        assert payload["route_prediction"] is None
    assert payload["primary_route_prediction"] is not None
    assert payload["primary_route_prediction"]["target_id"] != "sys-outer-terminus"
    predicted = next(system for system in payload["systems"] if system["id"] == payload["primary_route_prediction"]["target_id"])
    assert predicted["object_role"] != "far_objective"
    assert payload["navigation_intent"] in {"main_route", "detour_signal", "survey", "resource", "recovery"}
