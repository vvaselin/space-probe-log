"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

# 後の移行（0002、0003）が作るテーブル。ここで作ると、後の移行が「すでにある」で失敗する。
LATER_TABLES = {"simulation_clocks", "simulation_settings", "probe_navigation_states", "admin_sessions", "scheduler_leases"}


def _initial_tables() -> list[sa.Table]:
    import app.models  # noqa: F401  モデルを Base.metadata に登録する
    from app.db.base import Base

    return [table for name, table in Base.metadata.tables.items() if name not in LATER_TABLES]


def upgrade() -> None:
    from app.db.base import Base

    Base.metadata.create_all(bind=op.get_bind(), tables=_initial_tables())


def downgrade() -> None:
    from app.db.base import Base

    Base.metadata.drop_all(bind=op.get_bind(), tables=_initial_tables())
