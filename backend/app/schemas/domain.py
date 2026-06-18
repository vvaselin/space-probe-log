from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ActionName = Literal["move", "observe", "investigate_signal", "collect_resource", "wait"]


class DriveMode(StrEnum):
    conventional = "conventional"
    piano_drive = "piano_drive"


class NavigationPhase(StrEnum):
    idle = "idle"
    local_navigation = "local_navigation"
    system_departure = "system_departure"
    accelerating = "accelerating"
    interstellar_cruise = "interstellar_cruise"
    decelerating = "decelerating"
    system_arrival = "system_arrival"
    arrived = "arrived"


class ClockState(StrEnum):
    running = "running"
    paused = "paused"


class Vector3(BaseModel):
    x: float
    y: float
    z: float


class ProposedAction(BaseModel):
    action: ActionName
    target_id: str | None = None
    reason: str = Field(min_length=1, max_length=500)


class ObservationFact(BaseModel):
    type: str
    value: str
    reliability: float = Field(ge=0.0, le=1.0)
    sighting_level: Literal["detected", "resolved", "confirmed"] = "confirmed"
    source: str | None = None
    distance_hint: str | None = None


class Interpretation(BaseModel):
    hypothesis: str
    confidence: float = Field(ge=0.0, le=1.0)


class GeneratedLog(BaseModel):
    title: str
    summary: str
    body_markdown: str
    reliability: float = Field(ge=0.0, le=1.0)


class ActionContext(BaseModel):
    probe: dict[str, Any]
    nearby_systems: list[dict[str, Any]]
    navigation_targets: list[dict[str, Any]] = Field(default_factory=list)
    visible_signals: list[dict[str, Any]]
    mission: str
    prompt_settings: dict[str, str] = Field(default_factory=dict)


class LogContext(BaseModel):
    action: dict[str, Any]
    event: dict[str, Any]
    probe_snapshot: dict[str, Any]
    observations: list[ObservationFact]
    interpretations: list[Interpretation]
    prompt_settings: dict[str, str] = Field(default_factory=dict)


class ResetRequest(BaseModel):
    world_seed: str | None = None


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=512)


class AdminSessionRead(BaseModel):
    authenticated: bool
    username: str
    csrf_token: str
    expires_at: datetime


class PromptSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    probe_profile: str
    action_policy: str
    log_writer_style: str
    updated_at: datetime


class PromptSettingsUpdate(BaseModel):
    probe_profile: str = Field(default="", max_length=4000)
    action_policy: str = Field(default="", max_length=4000)
    log_writer_style: str = Field(default="", max_length=4000)


class ProbeSpecification(BaseModel):
    id: str
    display_name: str
    vessel_type: str
    length_m: float
    width_m: float
    height_m: float
    deployed_max_width_m: float
    launch_mass_kg: float
    dry_mass_kg: float
    propellant_mass_kg: float
    repair_resource_feedstock_kg: float
    cruise_speed_fraction_c: float
    cruise_speed_m_s: float
    cruise_speed_km_s: float
    max_cruise_speed_fraction_c: float
    max_cruise_speed_m_s: float
    max_cruise_speed_km_s: float
    planned_operational_years: int
    local_drive_mode: DriveMode
    interstellar_drive_mode: DriveMode
    defense: str
    capabilities: list[str]


class SimulationClockRead(BaseModel):
    simulation_datetime: datetime
    mission_clock: str
    time_scale: float
    clock_state: ClockState
    last_real_datetime: datetime
    real_elapsed_seconds_applied: float = 0.0


class SimulationClockUpdate(BaseModel):
    time_scale: float | None = Field(default=None, ge=0)
    clock_state: ClockState | None = None


class SimulationSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    default_time_scale: float
    advance_offline: bool
    max_offline_elapsed_seconds: int
    time_scale_presets: list[float]
    updated_at: datetime


class SimulationSettingsUpdate(BaseModel):
    default_time_scale: float | None = Field(default=None, ge=0)
    advance_offline: bool | None = None
    max_offline_elapsed_seconds: int | None = Field(default=None, ge=0)
    time_scale_presets: list[float] | None = None


class ProbeNavigationRead(BaseModel):
    active: bool = False
    phase: NavigationPhase = NavigationPhase.idle
    drive_mode: DriveMode = DriveMode.conventional
    origin_system_id: str | None = None
    destination_system_id: str | None = None
    destination_name: str | None = None
    started_at: datetime | None = None
    eta_datetime: datetime | None = None
    arrived_at: datetime | None = None
    sampled_at: datetime | None = None
    total_distance_pc: float = 0.0
    total_distance_km: float = 0.0
    remaining_distance_pc: float = 0.0
    remaining_distance_km: float = 0.0
    progress: float = 0.0
    progress_percent: float = 0.0
    current_speed_m_s: float = 0.0
    current_speed_km_s: float = 0.0
    cruise_speed_m_s: float = 0.0
    max_speed_m_s: float = 0.0
    galactic_position_pc: Vector3 | None = None
    local_position_au: Vector3 | None = None
    display_position: Vector3 | None = None
    origin_display_position: Vector3 | None = None
    destination_display_position: Vector3 | None = None
    display_velocity: Vector3 | None = None


class ProbeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    current_system_id: str
    target_id: str | None
    x: float
    y: float
    z: float
    display_x: float
    display_y: float
    display_z: float
    velocity: float
    energy: float
    fuel: float
    hull: float
    communication: float
    sensors: float
    propulsion: float
    storage_used: float
    storage_capacity: float
    collected_resources: dict[str, float]
    discovered_body_ids: list[str]
    current_mission: str
    last_updated_at: datetime
    mission_time: int
    mission_clock: str
    sim_timestamp: str
    sim_elapsed_seconds: int
    specification: ProbeSpecification | None = None
    navigation: ProbeNavigationRead | None = None
    simulation_datetime: datetime | None = None


class BodyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    body_type: str
    orbit_radius_km: float | None
    radius_km: float
    sim_x: float
    sim_y: float
    sim_z: float
    display_x: float
    display_y: float
    display_z: float
    display_radius: float
    discovered: bool
    details: dict[str, Any]


class SignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    system_id: str
    body_id: str | None
    kind: str
    strength: float
    display_x: float
    display_y: float
    display_z: float
    discovered: bool
    investigated: bool
    details: dict[str, Any]


class SystemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    kind: str
    x: float
    y: float
    z: float
    display_x: float
    display_y: float
    display_z: float
    discovered: bool
    generated_seed: str
    has_life: bool
    resources: dict[str, Any]
    details: dict[str, Any]


class SystemDetail(SystemRead):
    bodies: list[BodyRead]
    signals: list[SignalRead]


class LogListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    summary: str
    log_type: str
    mission_time: int
    generated_at: datetime
    probe_position: dict[str, Any]
    reliability: float


class LogDetail(LogListItem):
    body_markdown: str
    related_event_ids: list[int]
    related_body_ids: list[str]
    probe_state_snapshot: dict[str, Any]
    communication_status: str
    observations: list[dict[str, Any]]
    interpretations: list[dict[str, Any]]


class MapPayload(BaseModel):
    systems: list[dict[str, Any]]
    bodies: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    environment_objects: list[dict[str, Any]] = Field(default_factory=list)
    probe: dict[str, Any]
    route: list[dict[str, float]]
    route_prediction: dict[str, Any] | None = None
    primary_route_prediction: dict[str, Any] | None = None
    navigation_intent: str | None = None
    map_origin: dict[str, Any] | None = None
    focus: dict[str, float] | None = None
    distant_stars: list[dict[str, Any]] = Field(default_factory=list)
    real_data_epoch: str | None = None


class SimulationStepResponse(BaseModel):
    action: dict[str, Any]
    event: dict[str, Any]
    log: LogListItem
    probe: ProbeRead
    mission_clock: str | None = None
    sim_timestamp: str | None = None
    sim_elapsed_seconds: int | None = None


class SimulationTickResponse(BaseModel):
    action: dict[str, Any]
    event: dict[str, Any]
    log: LogListItem | None = None
    probe: ProbeRead
    route: dict[str, Any] | None = None
    mission_clock: str
    sim_timestamp: str
    sim_elapsed_seconds: int
