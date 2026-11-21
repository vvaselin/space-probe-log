"""航行の保存先。既存の Base とは別のテーブル群で、本番とデバッグでDBファイルを分ける。"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.time import utcnow

# shortcut: create_all だけでテーブルを作る。既存の画面へ切り替える時に alembic の移行を足す。


class VoyageBase(DeclarativeBase):
    pass


class VoyageRecord(VoyageBase):
    __tablename__ = "voyages"

    id: Mapped[int] = mapped_column(primary_key=True)
    seed: Mapped[str] = mapped_column(String(120))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def start_at_utc(self) -> datetime:
        # SQLite はタイムゾーンを落とすので付け直す。
        return self.start_at if self.start_at.tzinfo else self.start_at.replace(tzinfo=UTC)


class LegRecord(VoyageBase):
    __tablename__ = "voyage_legs"
    __table_args__ = (UniqueConstraint("voyage_id", "index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    voyage_id: Mapped[int] = mapped_column(ForeignKey("voyages.id"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class LogRecord(VoyageBase):
    __tablename__ = "voyage_logs"
    __table_args__ = (UniqueConstraint("voyage_id", "log_number", "revision"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    voyage_id: Mapped[int] = mapped_column(ForeignKey("voyages.id"), index=True)
    log_number: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    leg_index: Mapped[int] = mapped_column(Integer)
    scene_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text)
    body_markdown: Mapped[str] = mapped_column(Text)
    llm_input: Mapped[dict[str, Any]] = mapped_column(JSON)
    llm_output: Mapped[dict[str, Any]] = mapped_column(JSON)
    fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def _session_factory(url: str) -> sessionmaker[Session]:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    VoyageBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def open_session(url: str) -> Session:
    """呼ぶたびに新しいエンジン（CLI とテスト用。メモリ上のDBはテストごとに別になる）。"""
    return _session_factory(url)()


@lru_cache
def cached_session_factory(url: str) -> sessionmaker[Session]:
    """API 用。エンジンを使い回す。"""
    return _session_factory(url)
