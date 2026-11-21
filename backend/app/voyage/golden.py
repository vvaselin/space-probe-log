"""Python の答えを JSON に書き出す（11章「2つの言語で同じ式を持つ」）。

  python -m app.voyage.golden            # frontend/tests/golden/voyage.json を書き直す

フロントの `npm test` が、この答えと TypeScript の式の結果を照らし合わせる。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.voyage.cli import mock_chooser, simulate_route
from app.voyage.route import START_AT, start_position
from app.voyage.sync import body_payload, leg_formula, monotone_cubic, probe_position
from app.voyage.world import load_world, position_au

OUT = Path(__file__).resolve().parents[3] / "frontend" / "tests" / "golden" / "voyage.json"
BODY_TIMES = [
    datetime(1990, 3, 1, tzinfo=UTC),
    datetime(2080, 5, 2, 12, tzinfo=UTC),
    datetime(2081, 1, 1, tzinfo=UTC),
    datetime(2100, 6, 15, 6, 30, tzinfo=UTC),
    datetime(2150, 1, 1, tzinfo=UTC),
]
LEG_FRACTIONS = [0.0, 0.004, 0.02, 0.1, 0.5, 0.9, 0.97, 0.996, 1.0]
TIMETABLE_POINTS = [(0.0, 0.0), (10.0, 100.0), (11.0, 100.0), (30.0, 400.0), (31.0, 1000.0), (100.0, 1000.0)]


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


async def build() -> dict[str, Any]:
    world = load_world()
    legs = await simulate_route(8, START_AT, mock_chooser("golden"))
    start = start_position(world, START_AT)
    leg_samples = []
    for leg in legs:
        for f in LEG_FRACTIONS:
            # フロントの Date はミリ秒までなので、ミリ秒に丸めた時刻で比べる
            t = leg.profile.depart_at + timedelta(seconds=leg.profile.duration_s * f)
            t = t.replace(microsecond=t.microsecond // 1000 * 1000)
            position, index = probe_position(legs, start, t)
            leg_samples.append({"sim_at": _iso(t), "position_au": position, "leg_index": index})
    return {
        "generated_by": "python -m app.voyage.golden",
        "bodies": body_payload(world),
        "body_positions": [
            {"id": d.id, "at": _iso(t), "position_au": position_au(world, d, t)}
            for d in world.destinations.values()
            for t in BODY_TIMES
        ],
        "start_position_au": start,
        "legs": [leg_formula(leg) for leg in legs],
        "leg_samples": leg_samples,
        "timetable": {
            "points": TIMETABLE_POINTS,
            "samples": [[x / 4, monotone_cubic(TIMETABLE_POINTS, x / 4)] for x in range(-8, 420)],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.voyage.golden")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(asyncio.run(build()), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
