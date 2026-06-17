from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.time import utcnow
from app.db.base import Base


MISSION_START_AT = datetime(2080, 5, 2, 12, 0, 0, tzinfo=UTC)
SIM_SECONDS_PER_REAL_SECOND = 600
REAL_SECONDS_PER_TICK = 1.8
SIM_SECONDS_PER_TICK = int(SIM_SECONDS_PER_REAL_SECOND * REAL_SECONDS_PER_TICK)


def _sim_datetime_for_tick(mission_time: int) -> datetime:
    return MISSION_START_AT + timedelta(seconds=max(0, mission_time) * SIM_SECONDS_PER_TICK)


class Universe(Base):
    __tablename__ = "universes"

    id: Mapped[int] = mapped_column(primary_key=True)
    world_seed: Mapped[str] = mapped_column(String(120), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StarSystem(Base):
    __tablename__ = "star_systems"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    universe_id: Mapped[int] = mapped_column(ForeignKey("universes.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="stellar")
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)
    display_x: Mapped[float] = mapped_column(Float)
    display_y: Mapped[float] = mapped_column(Float)
    display_z: Mapped[float] = mapped_column(Float)
    discovered: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    generated_seed: Mapped[str] = mapped_column(String(160))
    has_life: Mapped[bool] = mapped_column(Boolean, default=False)
    resources: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    bodies: Mapped[list["CelestialBody"]] = relationship(back_populates="system", cascade="all, delete-orphan")
    signals: Mapped[list["Signal"]] = relationship(back_populates="system", cascade="all, delete-orphan")


class CelestialBody(Base):
    __tablename__ = "celestial_bodies"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    system_id: Mapped[str] = mapped_column(ForeignKey("star_systems.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    body_type: Mapped[str] = mapped_column(String(60), index=True)
    orbit_radius_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_km: Mapped[float] = mapped_column(Float)
    sim_x: Mapped[float] = mapped_column(Float)
    sim_y: Mapped[float] = mapped_column(Float)
    sim_z: Mapped[float] = mapped_column(Float)
    display_x: Mapped[float] = mapped_column(Float)
    display_y: Mapped[float] = mapped_column(Float)
    display_z: Mapped[float] = mapped_column(Float)
    display_radius: Mapped[float] = mapped_column(Float)
    discovered: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    system: Mapped[StarSystem] = relationship(back_populates="bodies")


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    system_id: Mapped[str] = mapped_column(ForeignKey("star_systems.id"), index=True)
    body_id: Mapped[str | None] = mapped_column(ForeignKey("celestial_bodies.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(80), index=True)
    strength: Mapped[float] = mapped_column(Float)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)
    display_x: Mapped[float] = mapped_column(Float)
    display_y: Mapped[float] = mapped_column(Float)
    display_z: Mapped[float] = mapped_column(Float)
    discovered: Mapped[bool] = mapped_column(Boolean, default=True)
    investigated: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    system: Mapped[StarSystem] = relationship(back_populates="signals")


class Probe(Base):
    __tablename__ = "probes"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    universe_id: Mapped[int] = mapped_column(ForeignKey("universes.id"), index=True)
    current_system_id: Mapped[str] = mapped_column(String(80), index=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float)
    display_x: Mapped[float] = mapped_column(Float)
    display_y: Mapped[float] = mapped_column(Float)
    display_z: Mapped[float] = mapped_column(Float)
    velocity: Mapped[float] = mapped_column(Float, default=0.0)
    energy: Mapped[float] = mapped_column(Float, default=100.0)
    fuel: Mapped[float] = mapped_column(Float, default=100.0)
    hull: Mapped[float] = mapped_column(Float, default=100.0)
    communication: Mapped[float] = mapped_column(Float, default=100.0)
    sensors: Mapped[float] = mapped_column(Float, default=100.0)
    propulsion: Mapped[float] = mapped_column(Float, default=100.0)
    storage_used: Mapped[float] = mapped_column(Float, default=0.0)
    storage_capacity: Mapped[float] = mapped_column(Float, default=100.0)
    current_mission: Mapped[str] = mapped_column(String(240), default="近傍恒星系の基礎探査")
    mission_time: Mapped[int] = mapped_column(Integer, default=0)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    discovered_body_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    collected_resources: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)

    @property
    def sim_elapsed_seconds(self) -> int:
        return max(0, self.mission_time) * SIM_SECONDS_PER_TICK

    @property
    def sim_timestamp(self) -> str:
        return _sim_datetime_for_tick(self.mission_time).isoformat().replace("+00:00", "Z")

    @property
    def mission_clock(self) -> str:
        return _sim_datetime_for_tick(self.mission_time).strftime("%Y/%m/%d %H:%M:%S UTC")


class SimulationClock(Base):
    __tablename__ = "simulation_clocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    simulation_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: MISSION_START_AT)
    time_scale: Mapped[float] = mapped_column(Float, default=360.0)
    clock_state: Mapped[str] = mapped_column(String(24), default="running", index=True)
    last_real_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SimulationSettings(Base):
    __tablename__ = "simulation_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    default_time_scale: Mapped[float] = mapped_column(Float, default=360.0)
    advance_offline: Mapped[bool] = mapped_column(Boolean, default=True)
    max_offline_elapsed_seconds: Mapped[int] = mapped_column(Integer, default=86_400)
    time_scale_presets: Mapped[list[float]] = mapped_column(JSON, default=lambda: [0, 360, 1440, 10080, 525600])
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProbeNavigationState(Base):
    __tablename__ = "probe_navigation_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    probe_id: Mapped[str] = mapped_column(ForeignKey("probes.id"), index=True)
    origin_system_id: Mapped[str] = mapped_column(String(80), index=True)
    destination_system_id: Mapped[str] = mapped_column(String(80), index=True)
    destination_name: Mapped[str] = mapped_column(String(160), default="")
    phase: Mapped[str] = mapped_column(String(40), default="idle", index=True)
    drive_mode: Mapped[str] = mapped_column(String(40), default="conventional")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    eta_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_distance_pc: Mapped[float] = mapped_column(Float, default=0.0)
    total_distance_km: Mapped[float] = mapped_column(Float, default=0.0)
    remaining_distance_pc: Mapped[float] = mapped_column(Float, default=0.0)
    remaining_distance_km: Mapped[float] = mapped_column(Float, default=0.0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_speed_m_s: Mapped[float] = mapped_column(Float, default=0.0)
    cruise_speed_m_s: Mapped[float] = mapped_column(Float, default=23_983_396.64)
    max_speed_m_s: Mapped[float] = mapped_column(Float, default=35_975_094.96)
    event_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProbeStateHistory(Base):
    __tablename__ = "probe_state_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    probe_id: Mapped[str] = mapped_column(ForeignKey("probes.id"), index=True)
    mission_time: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)


class SimulationAction(Base):
    __tablename__ = "simulation_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    probe_id: Mapped[str] = mapped_column(ForeignKey("probes.id"), index=True)
    proposed_action: Mapped[str] = mapped_column(String(60))
    validated_action: Mapped[str] = mapped_column(String(60))
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), index=True)
    validation_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SimulationEvent(Base):
    __tablename__ = "simulation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    probe_id: Mapped[str] = mapped_column(ForeignKey("probes.id"), index=True)
    action_id: Mapped[int | None] = mapped_column(ForeignKey("simulation_actions.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    mission_time: Mapped[int] = mapped_column(Integer, index=True)
    summary: Mapped[str] = mapped_column(Text)
    related_body_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    related_signal_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExplorationLog(Base):
    __tablename__ = "exploration_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(Text)
    body_markdown: Mapped[str] = mapped_column(Text)
    log_type: Mapped[str] = mapped_column(String(60), default="mission")
    mission_time: Mapped[int] = mapped_column(Integer, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    probe_position: Mapped[dict[str, Any]] = mapped_column(JSON)
    related_event_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    related_body_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    probe_state_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    communication_status: Mapped[str] = mapped_column(String(80), default="nominal")
    reliability: Mapped[float] = mapped_column(Float, default=1.0)


class Discovery(Base):
    __tablename__ = "discoveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    probe_id: Mapped[str] = mapped_column(ForeignKey("probes.id"), index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("simulation_events.id"), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    observation_type: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[str] = mapped_column(Text)
    reliability: Mapped[float] = mapped_column(Float)
    interpretations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResourceInventory(Base):
    __tablename__ = "resource_inventory"

    id: Mapped[int] = mapped_column(primary_key=True)
    probe_id: Mapped[str] = mapped_column(ForeignKey("probes.id"), index=True)
    resource_name: Mapped[str] = mapped_column(String(120), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)


class PromptSettings(Base):
    __tablename__ = "prompt_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    probe_profile: Mapped[str] = mapped_column(Text, default="")
    action_policy: Mapped[str] = mapped_column(Text, default="")
    log_writer_style: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
