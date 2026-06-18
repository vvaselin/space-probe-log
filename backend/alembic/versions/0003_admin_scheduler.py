"""admin sessions and scheduler lease

Revision ID: 0003_admin_scheduler
Revises: 0002_simulation_clock_navigation
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_admin_scheduler"
down_revision = "0002_simulation_clock_navigation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_sessions",
        sa.Column("token_hash", sa.String(length=64), primary_key=True),
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("csrf_token", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_sessions_username", "admin_sessions", ["username"])
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])
    op.create_table(
        "scheduler_leases",
        sa.Column("name", sa.String(length=80), primary_key=True),
        sa.Column("owner_id", sa.String(length=80), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tick_in_progress", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scheduler_leases_owner_id", "scheduler_leases", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_scheduler_leases_owner_id", table_name="scheduler_leases")
    op.drop_table("scheduler_leases")
    op.drop_index("ix_admin_sessions_expires_at", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_username", table_name="admin_sessions")
    op.drop_table("admin_sessions")
