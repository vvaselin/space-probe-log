from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import voyage as voyage_api
from app.llm.mock import MockVoyageLLM
from app.voyage.orbits import norm, sub
from app.voyage.service import create_voyage, current_logs, ensure_voyage, latest_voyage, load_legs, rewrite, step
from app.voyage.store import open_session
from app.voyage.sync import TimetablePoint, build_timetable, monotone_cubic, probe_position, sim_time_at, start_of
from app.voyage.world import load_world

T0 = datetime(2026, 11, 21, 12, tzinfo=UTC)


def test_monotone_cubic_passes_through_points_and_never_overshoots() -> None:
    points = [(0.0, 0.0), (10.0, 100.0), (11.0, 100.0), (30.0, 400.0), (31.0, 1000.0)]
    for x, y in points:
        assert monotone_cubic(points, x) == pytest.approx(y)
    xs = [i / 10 for i in range(0, 311)]
    ys = [monotone_cubic(points, x) for x in xs]
    assert all(b >= a - 1e-9 for a, b in zip(ys, ys[1:]))
    assert all(v == pytest.approx(100.0) for x, v in zip(xs, ys) if 10 <= x <= 11)
    assert monotone_cubic(points, -5) == 0.0 and monotone_cubic(points, 99) == 1000.0
    assert monotone_cubic([(0.0, 1.0)], 5.0) == 1.0


def test_sim_time_stops_at_the_next_scene_until_it_is_published() -> None:
    sim0 = datetime(2080, 5, 2, 12, tzinfo=UTC)
    table = [
        TimetablePoint(real_at=T0, sim_at=sim0, label="a", published=True),
        TimetablePoint(real_at=T0 + timedelta(days=1), sim_at=sim0 + timedelta(hours=6), label="b", published=False),
    ]
    assert sim_time_at(table, T0 + timedelta(hours=12)) == sim0 + timedelta(hours=3)
    assert sim_time_at(table, T0 + timedelta(days=5)) == sim0 + timedelta(hours=6)


@pytest.fixture()
def db(tmp_path: Path) -> Session:
    return open_session(f"sqlite:///{tmp_path / 'voyage_sync.db'}")


async def _stepped(db: Session, count: int) -> None:
    voyage = create_voyage(db, "sync-seed")
    for _ in range(count):
        await step(db, voyage, load_world(), MockVoyageLLM("route", "sync-seed"), MockVoyageLLM("log"))


async def test_timetable_uses_published_logs_and_the_next_planned_scene(db: Session) -> None:
    await _stepped(db, 5)
    voyage = latest_voyage(db)
    world = load_world()
    legs = load_legs(db, voyage.id)
    table = build_timetable(db, voyage, world, legs, publish_interval_s=3600)
    assert [p.published for p in table] == [True, True, True, False]
    assert table[-1].real_at - table[-2].real_at == timedelta(seconds=3600)
    sims = [p.sim_at for p in table]
    assert sims == sorted(sims)
    # 最後に公開した時刻ではその場面の時刻、次の予定より後は次の場面で止まる
    assert sim_time_at(table, table[-2].real_at) == table[-2].sim_at
    assert sim_time_at(table, table[-1].real_at + timedelta(days=3)) == table[-1].sim_at


async def test_probe_position_is_continuous_across_legs(db: Session) -> None:
    await _stepped(db, 6)
    voyage = latest_voyage(db)
    legs = load_legs(db, voyage.id)
    start = start_of(load_world(), voyage)
    for leg in legs:
        before, _ = probe_position(legs, start, leg.profile.arrive_at - timedelta(microseconds=1))
        after, _ = probe_position(legs, start, leg.profile.arrive_at + timedelta(microseconds=1))
        assert norm(sub(before, after)) < 1e-9
    assert probe_position(legs, start, legs[0].profile.depart_at - timedelta(days=1))[0] == legs[0].profile.origin_au


async def test_sync_and_position_api(db: Session) -> None:
    await _stepped(db, 4)

    def override() -> Generator[Session, None, None]:
        yield db

    app = FastAPI()
    app.include_router(voyage_api.router)
    app.dependency_overrides[voyage_api.get_voyage_db] = override
    client = TestClient(app)
    sync = client.get("/api/voyage/sync").json()
    assert {"server_time", "timetable", "legs", "bodies", "start_position_au"} <= set(sync)
    assert sync["legs"] and all({"accel_s", "cruise_s", "decel_s", "depart_at"} <= set(leg["profile"]) for leg in sync["legs"])
    assert any(body["orbit"]["kind"] == "jpl_planet" for body in sync["bodies"])
    last_published = [p for p in sync["timetable"] if p["published"]][-1]
    pos = client.get("/api/voyage/position", params={"real_at": last_published["real_at"]}).json()
    assert datetime.fromisoformat(pos["sim_at"]) == datetime.fromisoformat(last_published["sim_at"])
    assert len(pos["position_au"]) == 3


def test_api_says_when_there_is_no_voyage(tmp_path: Path) -> None:
    empty = open_session(f"sqlite:///{tmp_path / 'empty.db'}")
    app = FastAPI()
    app.include_router(voyage_api.router)
    app.dependency_overrides[voyage_api.get_voyage_db] = lambda: empty
    assert TestClient(app).get("/api/voyage/sync").status_code == 404


def _client(db: Session) -> TestClient:
    app = FastAPI()
    app.include_router(voyage_api.router)
    app.dependency_overrides[voyage_api.get_voyage_db] = lambda: db
    return TestClient(app)


async def test_logs_api_lists_latest_revisions_newest_first(db: Session) -> None:
    await _stepped(db, 3)
    voyage = latest_voyage(db)
    assert voyage is not None
    first = current_logs(db, voyage.id)[0]
    await rewrite(db, first.id, MockVoyageLLM("log"))
    client = _client(db)
    items = client.get("/api/voyage/logs").json()
    assert [item["log_number"] for item in items] == [3, 2, 1]
    assert items[-1]["revision"] == 2 and items[0]["scene"]
    detail = client.get("/api/voyage/logs/1").json()
    assert detail["revision"] == 2 and "LOG #001" in detail["body_markdown"]
    assert detail["visible"] and detail["speed"]["state"] and detail["next_destination"]["name"]
    assert client.get("/api/voyage/logs/99").status_code == 404


def test_ensure_voyage_creates_only_one(db: Session) -> None:
    first = ensure_voyage(db, "seed-a")
    second = ensure_voyage(db, "seed-b")
    assert first.id == second.id and second.seed == "seed-a"
