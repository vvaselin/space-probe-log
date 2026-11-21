"""航行のCLI（12章）。backend/ で実行する。

  python -m app.voyage.cli route-table --legs 100   # LLMなし（モック）で航路を表に出す。DBは使わない
  python -m app.voyage.cli new                      # デバッグ用DBに航海を作る
  python -m app.voyage.cli step [--count N]         # 次の場面へ進め、ログを1本書く
  python -m app.voyage.cli rewrite LOG_ID           # 保存した入力から、ログだけを書き直す
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import unicodedata
from datetime import datetime

from app.core.config import get_settings
from app.llm.factory import get_voyage_llm
from app.llm.mock import MockVoyageLLM
from app.models.entities import MISSION_START_AT
from app.voyage.llm import llm_chooser
from app.voyage.orbits import AU_KM, norm
from app.voyage.route import INWARD_LIMIT, LEG_KIND_LABELS, Chooser, Leg, plan_leg
from app.voyage.scenes import SCENE_LABELS
from app.voyage.service import create_voyage, latest_voyage, rewrite, step
from app.voyage.store import open_session
from app.voyage.world import load_world


def _pad(text: str, width: int) -> str:
    used = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - used)


def _duration(seconds: float) -> str:
    return f"{seconds / 3600:.1f}時間" if seconds < 86_400 else f"{seconds / 86_400:.1f}日"


def mock_chooser(seed: str) -> Chooser:
    return llm_chooser(MockVoyageLLM("route", seed), load_world())


async def simulate_route(max_legs: int, start_at: datetime, choose: Chooser) -> list[Leg]:
    world = load_world()
    legs: list[Leg] = []
    while len(legs) < max_legs:
        leg = await plan_leg(world, legs, start_at, choose)
        if leg is None:
            break
        legs.append(leg)
    return legs


def print_route_table(legs: list[Leg]) -> None:
    world = load_world()
    header = (
        f"{_pad('#', 4)}{_pad('種別', 12)}{_pad('出発地 → 行き先', 30)}{_pad('太陽距離 AU', 18)}"
        f"{_pad('距離 AU', 10)}{_pad('速度 km/s', 11)}{_pad('所要', 10)}{_pad('到着 (UTC)', 18)}{_pad('場面', 34)}候補（点数、*が選んだ物）"
    )
    print(header)
    print("-" * 200)
    for leg in legs:
        p = leg.profile
        r0, r1 = norm(p.origin_au), norm(p.destination_au)
        scenes = "・".join(SCENE_LABELS[s.kind] for s in leg.scenes[1:-1]) or "-"
        offered = " | ".join(
            f"{'*' if c.id == leg.target.id else ''}{c.name} {c.total:.2f}" for c in leg.planning.candidates[:3]
        )
        route = f"{world.get(leg.origin_id).name} → {leg.target.name}"
        print(
            f"{_pad(str(leg.index), 4)}{_pad(LEG_KIND_LABELS[leg.leg_kind], 12)}{_pad(route, 30)}"
            f"{_pad(f'{r0:.2f} → {r1:.2f}', 18)}{_pad(f'{p.distance_km / AU_KM:.4f}', 10)}"
            f"{_pad(f'{p.cruise_speed_km_s:,.0f}', 11)}{_pad(_duration(p.duration_s), 10)}"
            f"{_pad(p.arrive_at.strftime('%Y-%m-%d %H:%M'), 18)}{_pad(scenes, 34)}{offered}"
            f"{'  ※1位に戻した' if leg.planning.fell_back else ''}"
        )
    inward = [
        leg.index
        for leg in legs
        if leg.leg_kind != "tour" and norm(leg.profile.destination_au) < INWARD_LIMIT * norm(leg.profile.origin_au)
    ]
    counts = {kind: sum(leg.leg_kind == kind for leg in legs) for kind in LEG_KIND_LABELS}
    print()
    print(f"区間 {len(legs)} 本（" + "、".join(f"{LEG_KIND_LABELS[k]} {v}" for k, v in counts.items()) + "）")
    print(f"場面 {sum(len(leg.scenes) for leg in legs)} 個 / 0.8倍より内側へ戻った区間: {inward or 'なし'}")
    if legs:
        last = legs[-1]
        print(f"最後の到着: {last.target.name}（太陽から {norm(last.profile.destination_au):.1f} AU、{last.profile.arrive_at:%Y-%m-%d}）")


async def _step(db_url: str, count: int) -> None:
    db = open_session(db_url)
    voyage = latest_voyage(db)
    if voyage is None:
        raise SystemExit(f"航海がありません。先に `new` を実行してください（DB: {db_url}）")
    world = load_world()
    route_llm, log_llm = get_voyage_llm("route", voyage.seed), get_voyage_llm("log", voyage.seed)
    for _ in range(count):
        record = await step(db, voyage, world, route_llm, log_llm)
        if record is None:
            print("航路の端に着いた。これ以上進める場面がない（空白を埋める生成は今回の範囲外）。")
            return
        print(record.body_markdown)
        note = "  ※定型文で埋めた" if record.fallback else ""
        print(f"(log id {record.id} / LOG #{record.log_number:03d} / model {record.llm_output['model']}){note}\n")


async def _rewrite(db_url: str, log_id: int) -> None:
    db = open_session(db_url)
    try:
        record = await rewrite(db, log_id, get_voyage_llm("log"))
    except LookupError as exc:
        raise SystemExit(str(exc)) from exc
    print(record.body_markdown)
    print(f"(log id {record.id} / LOG #{record.log_number:03d} 第{record.revision}版)")


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="python -m app.voyage.cli", description="INSOMNIA 航行（再設計版）のCLI")
    sub = parser.add_subparsers(dest="command", required=True)
    table = sub.add_parser("route-table", help="LLMなし（モック）で航路を計画して表に出す。DBは使わない")
    table.add_argument("--seed", default=settings.default_world_seed)
    table.add_argument("--legs", type=int, default=100)
    for name, help_text in (("new", "航海を作る"), ("step", "次の場面へ進め、ログを書く"), ("rewrite", "ログだけを書き直す")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--db", default=settings.voyage_debug_database_url, help="既定はデバッグ用DB")
        if name == "new":
            command.add_argument("--seed", default=settings.default_world_seed)
        if name == "step":
            command.add_argument("--count", type=int, default=1)
        if name == "rewrite":
            command.add_argument("log_id", type=int)
    args = parser.parse_args(argv)

    if args.command == "route-table":
        legs = asyncio.run(simulate_route(args.legs, MISSION_START_AT, mock_chooser(args.seed)))
        print_route_table(legs)
        if len(legs) < args.legs:
            print(f"候補がなくなったため {len(legs)} 区間で終了（空白を埋める生成は今回の範囲外）")
    elif args.command == "new":
        voyage = create_voyage(open_session(args.db), args.seed)
        print(f"航海 {voyage.id} を作った（seed={voyage.seed}、出発 {voyage.start_at:%Y-%m-%d %H:%M} UTC、DB: {args.db}）")
    elif args.command == "step":
        asyncio.run(_step(args.db, args.count))
    elif args.command == "rewrite":
        asyncio.run(_rewrite(args.db, args.log_id))


if __name__ == "__main__":
    main()
