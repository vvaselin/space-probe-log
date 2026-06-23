import math
from collections.abc import Iterable

from app.schemas.domain import RouteHazard
from app.world.generator import SmallBodyLayerSpec

DisplayPoint = tuple[float, float, float]
Interval = tuple[float, float]
EPSILON = 1e-9


def _quadratic_inside_interval(a: float, b: float, c: float) -> list[Interval]:
    if a <= EPSILON:
        return [(0.0, 1.0)] if c <= 0 else []
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return [(0.0, 1.0)] if c <= 0 else []
    root = math.sqrt(max(0.0, discriminant))
    low = max(0.0, (-b - root) / (2 * a))
    high = min(1.0, (-b + root) / (2 * a))
    return [(low, high)] if low <= high else []


def _sphere_interval(
    start: DisplayPoint, delta: DisplayPoint, center: DisplayPoint, radius: float
) -> list[Interval]:
    offset = tuple(start[index] - center[index] for index in range(3))
    return _quadratic_inside_interval(
        sum(value * value for value in delta),
        2 * sum(offset[index] * delta[index] for index in range(3)),
        sum(value * value for value in offset) - radius * radius,
    )


def _xz_cylinder_interval(
    start: DisplayPoint, delta: DisplayPoint, center: DisplayPoint, radius: float
) -> list[Interval]:
    offset_x = start[0] - center[0]
    offset_z = start[2] - center[2]
    return _quadratic_inside_interval(
        delta[0] * delta[0] + delta[2] * delta[2],
        2 * (offset_x * delta[0] + offset_z * delta[2]),
        offset_x * offset_x + offset_z * offset_z - radius * radius,
    )


def _y_slab_interval(start: DisplayPoint, delta: DisplayPoint, center_y: float, half_thickness: float) -> list[Interval]:
    relative_y = start[1] - center_y
    if abs(delta[1]) <= EPSILON:
        return [(0.0, 1.0)] if abs(relative_y) <= half_thickness else []
    first = (-half_thickness - relative_y) / delta[1]
    second = (half_thickness - relative_y) / delta[1]
    low = max(0.0, min(first, second))
    high = min(1.0, max(first, second))
    return [(low, high)] if low <= high else []


def _intersect(left: list[Interval], right: list[Interval]) -> list[Interval]:
    result: list[Interval] = []
    for left_low, left_high in left:
        for right_low, right_high in right:
            low = max(left_low, right_low)
            high = min(left_high, right_high)
            if low <= high:
                result.append((low, high))
    return result


def _subtract(intervals: list[Interval], excluded: list[Interval]) -> list[Interval]:
    result = intervals
    for excluded_low, excluded_high in excluded:
        next_result: list[Interval] = []
        for low, high in result:
            if excluded_high <= low or excluded_low >= high:
                next_result.append((low, high))
                continue
            if low < excluded_low:
                next_result.append((low, excluded_low))
            if excluded_high < high:
                next_result.append((excluded_high, high))
        result = next_result
    return [(low, high) for low, high in result if high - low > EPSILON]


def _occupied_intervals(layer: SmallBodyLayerSpec, start: DisplayPoint, delta: DisplayPoint) -> list[Interval]:
    if layer.layer_type == "asteroid_belt":
        outer = _xz_cylinder_interval(start, delta, layer.center, layer.outer_radius)
        slab = _y_slab_interval(start, delta, layer.center[1], max(0.0, layer.thickness) / 2)
        return _subtract(_intersect(outer, slab), _xz_cylinder_interval(start, delta, layer.center, layer.inner_radius))
    outer = _sphere_interval(start, delta, layer.center, layer.outer_radius)
    return _subtract(outer, _sphere_interval(start, delta, layer.center, layer.inner_radius))


def _point_at(start: DisplayPoint, delta: DisplayPoint, progress: float) -> DisplayPoint:
    return tuple(start[index] + delta[index] * progress for index in range(3))  # type: ignore[return-value]


def _region_clearance(layer: SmallBodyLayerSpec, point: DisplayPoint) -> float:
    offset_x = point[0] - layer.center[0]
    offset_y = point[1] - layer.center[1]
    offset_z = point[2] - layer.center[2]
    if layer.layer_type == "asteroid_belt":
        radial = math.hypot(offset_x, offset_z)
        radial_gap = max(layer.inner_radius - radial, radial - layer.outer_radius, 0.0)
        vertical_gap = max(abs(offset_y) - max(0.0, layer.thickness) / 2, 0.0)
        return math.hypot(radial_gap, vertical_gap)
    radius = math.sqrt(offset_x * offset_x + offset_y * offset_y + offset_z * offset_z)
    return max(layer.inner_radius - radius, radius - layer.outer_radius, 0.0)


def _minimum_clearance(layer: SmallBodyLayerSpec, start: DisplayPoint, delta: DisplayPoint) -> tuple[float, float]:
    sample_count = 256
    samples = [
        (_region_clearance(layer, _point_at(start, delta, index / sample_count)), index / sample_count)
        for index in range(sample_count + 1)
    ]
    _, best_progress = min(samples)
    step = 1 / sample_count
    low = max(0.0, best_progress - step)
    high = min(1.0, best_progress + step)
    for _ in range(24):
        left = low + (high - low) / 3
        right = high - (high - low) / 3
        left_clearance = _region_clearance(layer, _point_at(start, delta, left))
        right_clearance = _region_clearance(layer, _point_at(start, delta, right))
        if left_clearance <= right_clearance:
            high = right
        else:
            low = left
    progress = (low + high) / 2
    return _region_clearance(layer, _point_at(start, delta, progress)), progress


def _closest_approach(center: DisplayPoint, start: DisplayPoint, delta: DisplayPoint) -> float:
    length_squared = sum(value * value for value in delta)
    if length_squared <= EPSILON:
        return math.dist(center, start)
    offset = tuple(center[index] - start[index] for index in range(3))
    progress = max(0.0, min(1.0, sum(offset[index] * delta[index] for index in range(3)) / length_squared))
    return math.dist(center, _point_at(start, delta, progress))


def _hazard_attributes(layer_type: str, relation: str) -> tuple[str, str]:
    if layer_type == "asteroid_belt":
        return "medium", "monitor_and_minor_course_offset"
    if layer_type == "comet_population":
        severity = "low" if relation == "near_pass" else "medium"
        return severity, "monitor_and_prepare_course_offset"
    return "low", "passive_monitoring"


def _description(layer: SmallBodyLayerSpec, relation: str) -> str:
    relation_text = {
        "inside": "currently lies within",
        "crossing": "crosses",
        "near_pass": "passes near",
    }[relation]
    return f"Current route {relation_text} {layer.name}."


def display_route_hazard(layer: SmallBodyLayerSpec, start: DisplayPoint, end: DisplayPoint) -> RouteHazard | None:
    """Evaluate one generated layer against a straight route in Three.js display space."""
    delta = tuple(end[index] - start[index] for index in range(3))
    intervals = _occupied_intervals(layer, start, delta)
    start_inside = bool(intervals and intervals[0][0] <= EPSILON)
    if intervals:
        relation = "inside" if start_inside else "crossing"
        entry_progress = 0.0 if start_inside else intervals[0][0]
        exit_progress = intervals[-1][1]
    else:
        clearance, nearest_progress = _minimum_clearance(layer, start, delta)
        near_margin = max(2.0, min(8.0, (layer.outer_radius - layer.inner_radius) * 0.1))
        if clearance > near_margin:
            return None
        relation = "near_pass"
        entry_progress = nearest_progress
        exit_progress = nearest_progress
    severity, recommended_action = _hazard_attributes(layer.layer_type, relation)
    return RouteHazard(
        id=layer.id,
        name=layer.name,
        type=layer.layer_type,
        severity=severity,
        relation=relation,
        closest_approach=round(_closest_approach(layer.center, start, delta), 4),
        entry_progress=round(entry_progress, 6),
        exit_progress=round(exit_progress, 6),
        recommended_action=recommended_action,
        description=_description(layer, relation),
    )


def display_route_hazards(
    start: DisplayPoint,
    end: DisplayPoint,
    layers: Iterable[SmallBodyLayerSpec],
) -> list[RouteHazard]:
    hazards = [hazard for layer in layers if (hazard := display_route_hazard(layer, start, end)) is not None]
    return sorted(hazards, key=lambda item: (item.entry_progress, item.id))
