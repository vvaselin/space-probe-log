import hashlib
import json
import random
from typing import Any


def stable_seed(*parts: object) -> int:
    """同じ入力から同じ乱数の種を作る（Python の hash() は起動ごとに変わるので使わない）。"""
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


class MockVoyageLLM:
    """再設計版の航行（app/voyage）用のモック。ネットワークを使わず、入力だけから決まった答えを返す。"""

    def __init__(self, purpose: str, seed: str = "") -> None:
        self.purpose = purpose
        self.seed = seed
        self.model = f"mock-{purpose}"

    async def complete_json(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.purpose == "route":
            return _mock_route_choice(payload, self.seed)
        return _mock_voyage_log(payload)


def _mock_route_choice(payload: dict[str, Any], seed: str) -> dict[str, Any]:
    candidates = payload["candidates"]
    rng = random.Random(stable_seed(seed, json.dumps(payload, ensure_ascii=False, sort_keys=True)))
    pick = rng.choices(candidates, weights=[6, 3, 1][: len(candidates)])[0]
    return {"choice": pick["number"], "reason": f"{pick['name']}へ向かう。{pick['features']}を、この目で確かめたい。"}


def _mock_voyage_log(payload: dict[str, Any]) -> dict[str, Any]:
    scene = payload["scene"]
    leg = payload["current_leg"]
    lines = [f"{scene['kind']}。{scene['subject']}。"]
    for seen in payload["visible"][:3]:
        lines.append(f"{seen['name']}は{seen['direction']}。{seen['size']}、{seen['brightness']}。{seen['look']}。")
    remaining = f"{leg['to']}に着いた" if leg["remaining_time"] == "到着" else f"{leg['to']}まで、残り{leg['remaining_time']}"
    lines.append(f"速度は毎秒{payload['speed']['km_s']:,.0f}km。{remaining}。")
    lines.append("処理の順番を一度だけ入れ替えた。理由は、まだ分類していない。")
    return {
        "title": f"{scene['kind']}：{scene['subject']}"[:40],
        "summary": f"{scene['kind']}。{scene['subject']}を観測した。"[:120],
        "body": "\n\n".join(lines),
    }
