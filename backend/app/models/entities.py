from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.time import utcnow
from app.db.base import Base


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
