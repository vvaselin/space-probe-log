"""simulation clock and navigation state

Revision ID: 0002_simulation_clock_navigation
Revises: 0001_initial
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_simulation_clock_navigation"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

RELATED_PROBE_TABLES = [
    "probe_state_history",
    "simulation_actions",
    "simulation_events",
    "discoveries",
    "resource_inventory",
]


def upgrade() -> None:
    op.create_table(
        "simulation_clocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("simulation_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_scale", sa.Float(), nullable=False),
        sa.Column("clock_state", sa.String(length=24), nullable=False),
        sa.Column("last_real_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_simulation_clocks_clock_state", "simulation_clocks", ["clock_state"])

    op.create_table(
        "simulation_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("default_time_scale", sa.Float(), nullable=False),
        sa.Column("advance_offline", sa.Boolean(), nullable=False),
        sa.Column("max_offline_elapsed_seconds", sa.Integer(), nullable=False),
        sa.Column("time_scale_presets", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "probe_navigation_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("probe_id", sa.String(length=80), sa.ForeignKey("probes.id"), nullable=False),
        sa.Column("origin_system_id", sa.String(length=80), nullable=False),
        sa.Column("destination_system_id", sa.String(length=80), nullable=False),
        sa.Column("destination_name", sa.String(length=160), nullable=False),
        sa.Column("phase", sa.String(length=40), nullable=False),
        sa.Column("drive_mode", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eta_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_distance_pc", sa.Float(), nullable=False),
        sa.Column("total_distance_km", sa.Float(), nullable=False),
        sa.Column("remaining_distance_pc", sa.Float(), nullable=False),
        sa.Column("remaining_distance_km", sa.Float(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("current_speed_m_s", sa.Float(), nullable=False),
        sa.Column("cruise_speed_m_s", sa.Float(), nullable=False),
        sa.Column("max_speed_m_s", sa.Float(), nullable=False),
        sa.Column("event_keys", sa.JSON(), nullable=False),
        sa.Column("schedule", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_probe_navigation_states_probe_id", "probe_navigation_states", ["probe_id"])
    op.create_index("ix_probe_navigation_states_origin_system_id", "probe_navigation_states", ["origin_system_id"])
    op.create_index("ix_probe_navigation_states_destination_system_id", "probe_navigation_states", ["destination_system_id"])
    op.create_index("ix_probe_navigation_states_phase", "probe_navigation_states", ["phase"])

    bind = op.get_bind()
    for table_name in RELATED_PROBE_TABLES:
        bind.execute(sa.text(f"UPDATE {table_name} SET probe_id = :new WHERE probe_id = :old"), {"new": "probe-insomnia-07", "old": "probe-aurora"})
    bind.execute(sa.text("UPDATE probes SET id = :new, name = :name WHERE id = :old"), {"new": "probe-insomnia-07", "name": "INSOMNIA-07", "old": "probe-aurora"})
    bind.execute(sa.text("UPDATE probes SET name = :name WHERE name != :name"), {"name": "INSOMNIA-07"})


def downgrade() -> None:
    op.drop_index("ix_probe_navigation_states_phase", table_name="probe_navigation_states")
    op.drop_index("ix_probe_navigation_states_destination_system_id", table_name="probe_navigation_states")
    op.drop_index("ix_probe_navigation_states_origin_system_id", table_name="probe_navigation_states")
    op.drop_index("ix_probe_navigation_states_probe_id", table_name="probe_navigation_states")
    op.drop_table("probe_navigation_states")
    op.drop_table("simulation_settings")
    op.drop_index("ix_simulation_clocks_clock_state", table_name="simulation_clocks")
    op.drop_table("simulation_clocks")
