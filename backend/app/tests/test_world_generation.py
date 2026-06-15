from app.world.generator import generate_world


def simplified(seed: str) -> list[tuple[str, str, tuple[float, float, float], str]]:
    return [(item.id, item.name, item.position, item.generated_seed) for item in generate_world(seed)]


def test_same_seed_generates_same_systems() -> None:
    assert simplified("alpha") == simplified("alpha")


def test_different_seed_changes_fictional_systems() -> None:
    assert simplified("alpha")[1:] != simplified("beta")[1:]


def test_world_includes_far_objective() -> None:
    world = generate_world("alpha")
    objective = next(item for item in world if item.id == "sys-outer-terminus")
    assert objective.details["object_role"] == "far_objective"
    assert objective.display[0] > 100


def test_world_includes_outward_navigation_waypoints() -> None:
    world = generate_world("alpha")
    waypoints = [item for item in world if item.kind == "waypoint"]
    assert [item.id for item in waypoints] == ["outer-solar-marker", "heliopause-gate", "interstellar-corridor"]
    assert all(item.details["object_role"] == "navigation_waypoint" for item in waypoints)
