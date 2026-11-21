import asyncio
from collections.abc import Generator
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import voyage as voyage_api
from app.llm.mock import MockVoyageLLM
from app.core.time import utcnow
from app.services.auth import require_admin
from app.voyage import clock
from app.voyage.scheduler import publish_if_due, step_latest
from app.voyage.service import StepConflictError, create_voyage, current_logs, latest_voyage, load_legs
from app.voyage.store import VoyageRecord, open_session
from app.voyage.sync import build_timetable, sim_time_at
from app.voyage.world import load_world


def mock_llm(purpose: str, seed: str) -> MockVoyageLLM:
    return MockVoyageLLM(purpose, seed)


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'voyage_clock.db'}"


@pytest.fixture()
def db(db_url: str) -> Session:
    return open_session(db_url)


async def _voyage_with_logs(db: Session, count: int) -> VoyageRecord:
    voyage = create_voyage(db, "clock-seed")
    for _ in range(count):
        await step_latest(db, mock_llm)
    return voyage


def test_new_voyage_starts_in_manual_mode(db: Session) -> None:
    voyage = create_voyage(db, "clock-seed")
    status = clock.status(db, voyage)
    assert status.mode == "manual" and not status.paused and status.last_published_at is None


async def test_pause_shifts_the_next_publication(db: Session) -> None:
    voyage = await _voyage_with_logs(db, 3)
    clock.configure(db, voyage, mode="auto", interval=3600)
    last = clock.last_published_at(db, voyage)
    assert last is not None
    assert clock.status(db, voyage, now=last).next_publish_at == last + timedelta(hours=1)
    clock.pause(db, voyage, now=last + timedelta(minutes=10))
    # 止まっている間は、次の予定も止まっている時間だけ後ろへずれ続ける
    assert clock.status(db, voyage, now=last + timedelta(minutes=40)).next_publish_at == last + timedelta(hours=1, minutes=30)
    clock.resume(db, voyage, now=last + timedelta(minutes=50))
    assert clock.status(db, voyage, now=last + timedelta(hours=5)).next_publish_at == last + timedelta(hours=1, minutes=40)


async def test_time_does_not_advance_while_paused(db: Session) -> None:
    voyage = await _voyage_with_logs(db, 4)
    voyage_clock = clock.ensure_clock(db, voyage)
    clock.configure(db, voyage, interval=3600)
    last = clock.last_published_at(db, voyage)
    assert last is not None
    world, legs = load_world(), load_legs(db, voyage.id)

    def table() -> list[Any]:
        spans = clock.pause_spans(voyage_clock, clock.anchor_at(db, voyage))
        return build_timetable(db, voyage, world, legs, clock.interval_seconds(voyage_clock), spans)

    before = sim_time_at(table(), last + timedelta(minutes=20))
    clock.pause(db, voyage, now=last + timedelta(minutes=20))
    during = table()
    assert during[-1].label == "一時停止" and not any(not p.published for p in during)
    assert sim_time_at(during, last + timedelta(minutes=20)) == before
    assert sim_time_at(during, last + timedelta(days=2)) == before  # 止まったまま
    clock.resume(db, voyage, now=last + timedelta(minutes=50))
    after = table()
    assert [p.label for p in after][-3:-1] == ["一時停止", "再開"]
    assert sim_time_at(after, last + timedelta(minutes=35)) == before  # 止まっていた区間は進まない
    assert after[-1].real_at == last + timedelta(hours=1, minutes=30)


async def test_scheduler_publishes_only_when_due(db: Session) -> None:
    voyage = await _voyage_with_logs(db, 1)
    last = clock.last_published_at(db, voyage)
    assert last is not None
    later = last + timedelta(days=2)
    assert await publish_if_due(db, later, mock_llm) is None  # 手動モード
    clock.configure(db, voyage, mode="auto", interval=60)
    assert await publish_if_due(db, last + timedelta(seconds=30), mock_llm) is None  # 予定の前
    clock.pause(db, voyage, now=last + timedelta(seconds=40))
    assert await publish_if_due(db, later, mock_llm) is None  # 一時停止中
    clock.resume(db, voyage, now=last + timedelta(seconds=50))
    record = await publish_if_due(db, later, mock_llm)
    assert record is not None and record.log_number == 2
    # まとめて書かない：次の予定は、いま書いた時刻（実際の現在時刻）から数え直す
    assert clock.status(db, voyage).next_publish_at >= record.created_at.replace(tzinfo=UTC) + timedelta(seconds=60)
    assert await publish_if_due(db, utcnow() + timedelta(seconds=30), mock_llm) is None


class SlowLLM(MockVoyageLLM):
    """ほかの処理が割り込めるよう、答える前に待つ。"""

    async def complete_json(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        return await super().complete_json(system, payload)


async def test_two_simultaneous_steps_publish_only_one_log(db_url: str) -> None:
    first = open_session(db_url)
    await _voyage_with_logs(first, 1)
    second = open_session(db_url)

    def slow(purpose: str, seed: str) -> SlowLLM:
        return SlowLLM(purpose, seed)

    results = await asyncio.gather(step_latest(first, slow), step_latest(second, slow), return_exceptions=True)
    assert sum(isinstance(r, StepConflictError) for r in results) == 1
    voyage = latest_voyage(open_session(db_url))
    assert voyage is not None
    assert [log.log_number for log in current_logs(open_session(db_url), voyage.id)] == [1, 2]


@pytest.fixture()
def client(db: Session) -> TestClient:
    def override() -> Generator[Session, None, None]:
        yield db

    app = FastAPI()
    app.include_router(voyage_api.router)
    app.dependency_overrides[voyage_api.get_voyage_db] = override
    app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app)


async def test_clock_admin_api(db: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    await _voyage_with_logs(db, 1)
    monkeypatch.setattr("app.voyage.scheduler._llm", mock_llm)
    assert client.get("/api/voyage/clock").json()["mode"] == "manual"
    updated = client.patch("/api/voyage/clock", json={"mode": "auto", "interval_seconds": 300}).json()
    assert updated["mode"] == "auto" and updated["interval_seconds"] == 300
    assert client.patch("/api/voyage/clock", json={"interval_seconds": 0}).status_code == 422
    assert client.post("/api/voyage/clock/pause").json()["paused"] is True
    sync = client.get("/api/voyage/sync").json()
    assert sync["clock"]["paused"] is True and sync["timetable"][-1]["label"] == "一時停止"
    assert client.post("/api/voyage/clock/resume").json()["paused"] is False
    stepped = client.post("/api/voyage/step").json()
    assert stepped["log_number"] == 2


def test_admin_api_requires_login(db: Session) -> None:
    create_voyage(db, "clock-seed")
    app = FastAPI()
    app.include_router(voyage_api.router)
    app.dependency_overrides[voyage_api.get_voyage_db] = lambda: db
    raw = TestClient(app)
    assert raw.get("/api/voyage/clock").status_code == 200  # 読むのは誰でもよい
    assert raw.post("/api/voyage/clock/pause").status_code == 401
    assert raw.post("/api/voyage/step").status_code == 401
