import pytest

from app.services.route_hazards import display_route_hazard, display_route_hazards
from app.world.generator import SmallBodyLayerSpec


def layer(layer_type: str, inner: float = 10.0, outer: float = 20.0, thickness: float = 2.0) -> SmallBodyLayerSpec:
    return SmallBodyLayerSpec(
        id=f"test-{layer_type}",
        name=layer_type.replace("_", " ").title(),
        layer_type=layer_type,
        center=(0.0, 0.0, 0.0),
        inner_radius=inner,
        outer_radius=outer,
        thickness=thickness,
        particle_count=10,
        seed=1,
        visual_data={},
    )


def test_asteroid_belt_crossing_inside_near_pass_and_miss() -> None:
    belt = layer("asteroid_belt")

    crossing = display_route_hazard(belt, (0.0, 0.0, 0.0), (30.0, 0.0, 0.0))
    assert crossing is not None
    assert crossing.relation == "crossing"
    assert crossing.entry_progress == pytest.approx(1 / 3, abs=1e-5)
    assert crossing.exit_progress == pytest.approx(2 / 3, abs=1e-5)

    inside = display_route_hazard(belt, (15.0, 0.0, 0.0), (30.0, 0.0, 0.0))
    assert inside is not None
    assert inside.relation == "inside"
    assert inside.entry_progress == 0

    near_pass = display_route_hazard(belt, (0.0, 2.0, 0.0), (30.0, 2.0, 0.0))
    assert near_pass is not None
    assert near_pass.relation == "near_pass"

    assert display_route_hazard(belt, (0.0, 5.0, 0.0), (30.0, 5.0, 0.0)) is None


@pytest.mark.parametrize("layer_type", ["oort_cloud", "comet_population"])
def test_spherical_shell_crossing_inside_and_miss(layer_type: str) -> None:
    shell = layer(layer_type)
    crossing = display_route_hazard(shell, (-30.0, 0.0, 0.0), (30.0, 0.0, 0.0))
    assert crossing is not None
    assert crossing.relation == "crossing"
    assert crossing.entry_progress == pytest.approx(1 / 6, abs=1e-5)
    assert crossing.exit_progress == pytest.approx(5 / 6, abs=1e-5)

    inside = display_route_hazard(shell, (15.0, 0.0, 0.0), (30.0, 0.0, 0.0))
    assert inside is not None
    assert inside.relation == "inside"

    assert display_route_hazard(shell, (-30.0, 30.0, 0.0), (30.0, 30.0, 0.0)) is None


def test_hazard_attributes_and_ordering() -> None:
    hazards = display_route_hazards(
        (0.0, 0.0, 0.0),
        (40.0, 0.0, 0.0),
        [layer("oort_cloud", 25, 35), layer("comet_population", 5, 12), layer("asteroid_belt", 14, 20)],
    )
    assert [item.type for item in hazards] == ["comet_population", "asteroid_belt", "oort_cloud"]
    assert hazards[0].severity == "medium"
    assert hazards[0].recommended_action == "monitor_and_prepare_course_offset"
    assert hazards[1].severity == "medium"
    assert hazards[2].severity == "low"
    assert hazards[2].recommended_action == "passive_monitoring"
