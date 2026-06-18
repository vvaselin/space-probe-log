from app.world.generator import _manual_solar_system, frontier_shell_systems, generate_world, generated_environment_objects, solar_system


def simplified(seed: str) -> list[tuple[str, str, tuple[float, float, float], str]]:
    return [(item.id, item.name, item.position, item.generated_seed) for item in generate_world(seed)]


def test_same_seed_generates_same_systems() -> None:
    assert simplified("alpha") == simplified("alpha")


def test_different_seed_changes_fictional_systems() -> None:
    assert simplified("alpha")[1:] != simplified("beta")[1:]


def test_world_does_not_preseed_far_objective() -> None:
    world = generate_world("alpha")
    assert all(item.id != "sys-outer-terminus" for item in world)
    assert all(item.details.get("object_role") != "far_objective" for item in world)


def test_world_includes_outward_navigation_waypoints() -> None:
    world = generate_world("alpha")
    waypoints = [item for item in world if item.kind == "waypoint"]
    assert [item.id for item in waypoints] == ["outer-solar-marker", "heliopause-gate", "interstellar-corridor"]
    assert all(item.details["object_role"] == "navigation_waypoint" for item in waypoints)


def test_initial_world_is_not_single_display_line() -> None:
    world = generate_world("alpha")
    navigable = [item for item in world if item.id != "sol"]
    y_values = {round(item.display[1], 1) for item in navigable}
    z_values = {round(item.display[2], 1) for item in navigable}
    assert len(y_values) >= 4
    assert len(z_values) >= 4


def test_frontier_shell_is_seeded_and_spread_in_3d() -> None:
    shell_a = frontier_shell_systems("alpha", ring=1, base_radius=12.0)
    shell_b = frontier_shell_systems("alpha", ring=1, base_radius=12.0)
    assert simplified_frontier(shell_a) == simplified_frontier(shell_b)
    assert all(item.details["object_role"] == "frontier_system" for item in shell_a)
    assert len({round(item.display[2], 1) for item in shell_a}) > 2


def test_fallback_solar_system_includes_expected_bodies() -> None:
    sol = solar_system()
    body_ids = {body.id for body in sol.bodies}
    assert {"mercury", "venus", "earth", "moon", "saturn", "uranus", "neptune"} <= body_ids


def test_solar_system_body_details_are_split_by_concern() -> None:
    sol = solar_system()
    earth = next(body for body in sol.bodies if body.id == "earth")
    assert "physical_data" in earth.details
    assert "position_data" in earth.details
    assert "visual_data" in earth.details
    assert "fictional_data" in earth.details


def test_solar_system_display_distance_preserves_planet_order() -> None:
    sol = _manual_solar_system()
    positions = {body.id: body.display for body in sol.bodies}
    order = ["mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune"]
    radii = [sum(axis * axis for axis in positions[body_id]) ** 0.5 for body_id in order]
    assert radii == sorted(radii)


def test_saturn_has_ring_visual_data() -> None:
    sol = solar_system()
    saturn = next(body for body in sol.bodies if body.id == "saturn")
    assert saturn.details["visual_data"]["ring"]["texture_key"] == "ring_01"


def test_environment_objects_include_emission_strength_in_visual_data() -> None:
    environment = generated_environment_objects("alpha", generate_world("alpha"))
    for item in environment:
        emission_strength = item.details["visual_data"]["emission_strength"]
        if item.details["nebula_type"] == "emission":
            assert emission_strength >= 1.2
        if item.details["nebula_type"] == "dark":
            assert emission_strength <= 0.18


def simplified_frontier(items) -> list[tuple[str, str, tuple[float, float, float], str]]:
    return [(item.id, item.name, item.position, item.generated_seed) for item in items]
