from fastapi.testclient import TestClient

import app.api.simulation as simulation_api
from app.llm.mock import MockLLMClient
from app.main import app


def test_map_contains_far_objective_and_distant_stars() -> None:
    with TestClient(app) as client:
        client.post("/api/simulation/reset", json={"world_seed": "map-test"})
        payload = client.get("/api/world/map").json()
    assert any(system["object_role"] == "far_objective" for system in payload["systems"])
    assert any(system["object_role"] == "navigation_waypoint" for system in payload["systems"])
    assert len(payload["distant_stars"]) >= 100
    assert len(payload["environment_objects"]) >= 3
    assert all(item["source"] == "generated" for item in payload["environment_objects"])
    assert payload["map_origin"]["id"] == "earth"


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
    assert payload["primary_route_prediction"]["target_id"] == "sys-outer-terminus"
    assert payload["navigation_intent"] in {"main_route", "detour_signal", "survey", "resource", "recovery"}
