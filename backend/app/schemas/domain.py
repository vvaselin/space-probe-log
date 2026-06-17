from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ActionName = Literal["move", "observe", "investigate_signal", "collect_resource", "wait"]


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
