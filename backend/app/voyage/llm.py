"""LLMとのやり取り（7章）。出力を検証し、だめなら1回だけやり直す。それでもだめなら、行き先は1位、ログは定型文。"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, Field

from app.llm.client import JsonLLM
from app.voyage.route import LEG_KIND_LABELS, Candidate, Choice, Chooser
from app.voyage.world import World

LOGGER = logging.getLogger(__name__)
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
BANNED_WORDS = ("船窓", "船内", "操縦席", "甲板", "乗員", "乗っている", "OVIS")
PLACEHOLDERS = ("XX", "??", "〇〇")
EARLY_LOG_LIMIT = 3  # 「窓——いや」の言い直しを許す回数
WATCH_PHRASES = ("理由は不明", "ログに記録", "削除しない", "消さなかった", "分類不能", "まだ分類していない", "いや、")
ATTEMPTS = 2

T = TypeVar("T")


class LogDraft(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    summary: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=150, max_length=2400)


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def prompt_version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _as_object(data: object) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"JSON object expected, got {type(data).__name__}")
    return data


def validate_route_answer(data: object, offered_count: int) -> tuple[int, str]:
    obj = _as_object(data)
    choice, reason = obj.get("choice"), obj.get("reason")
    if isinstance(choice, bool) or not isinstance(choice, int) or not 1 <= choice <= offered_count:
        raise ValueError(f"choice must be an integer 1..{offered_count}, got {choice!r}")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
        raise ValueError("reason must be a non-empty string up to 300 characters")
    return choice, reason.strip()


def validate_log_answer(data: object, log_number: int) -> LogDraft:
    draft = LogDraft.model_validate(_as_object(data))
    text = f"{draft.title}\n{draft.summary}\n{draft.body}"
    problems = [w for w in BANNED_WORDS if w in text] + [p for p in PLACEHOLDERS if p in text]
    if log_number > EARLY_LOG_LIMIT and "窓" in text:
        problems.append("窓")
    if problems:
        raise ValueError(f"使ってはいけない言葉が入っている: {', '.join(problems)}")
    return draft


async def ask_with_retry(
    llm: JsonLLM, system: str, payload: dict[str, Any], validate: Callable[[object], T]
) -> tuple[T | None, list[dict[str, Any]]]:
    """最大2回聞く。2回目には1回目の問題を添える。返すのは（検証済みの答えか None、試行の記録）。"""
    attempts: list[dict[str, Any]] = []
    for _ in range(ATTEMPTS):
        request = payload if not attempts else {**payload, "previous_output_problem": attempts[-1]["error"]}
        try:
            raw = await llm.complete_json(system, request)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            LOGGER.warning("LLM call failed (%s): %s", llm.model, exc)
            attempts.append({"error": f"{type(exc).__name__}: {exc}"})
            continue
        try:
            result = validate(raw)
        except ValueError as exc:
            LOGGER.warning("LLM output rejected (%s): %s", llm.model, exc)
            attempts.append({"output": raw, "error": str(exc)})
            continue
        attempts.append({"output": raw})
        return result, attempts
    return None, attempts


def llm_chooser(llm: JsonLLM, world: World) -> Chooser:
    system = load_prompt("route_choice.md")

    async def choose(offered: list[Candidate], context: dict[str, Any]) -> Choice:
        payload = {
            **context,
            "candidates": [
                {
                    "number": i + 1,
                    "name": c.name,
                    "kind": LEG_KIND_LABELS[c.leg_kind],
                    "sun_distance_au": c.r_au,
                    "travel_days": c.travel_days,
                    "features": world.get(c.id).visual.pattern,
                    "score": c.total,
                }
                for i, c in enumerate(offered)
            ],
        }
        result, attempts = await ask_with_retry(llm, system, payload, lambda d: validate_route_answer(d, len(offered)))
        raw = {"model": llm.model, "prompt_version": prompt_version(system), "payload": payload, "attempts": attempts}
        if result is None:
            return Choice(target_id=None, reason="", raw=raw)
        number, reason = result
        return Choice(target_id=offered[number - 1].id, reason=reason, raw=raw)

    return choose


def fallback_draft(payload: dict[str, Any]) -> LogDraft:
    scene = payload["scene"]
    body = (
        f"{scene['kind']}。{scene['subject']}。\n\n"
        f"太陽から{payload['position']['sun_distance_au']} AU、速度は毎秒{payload['speed']['km_s']:,.0f} km。\n\n"
        "本文の生成に失敗したため、この場面は観測値だけを保存した。"
        "見えていた天体の値は、記録の中にそのまま残してある。次の場面で、続きを書く。"
    )
    # 定型文はLLM向けの長さの検証を通さない（短くてよい）。
    return LogDraft.model_construct(title=f"{scene['kind']}の記録", summary=f"{scene['kind']}：{scene['subject']}（定型文）", body=body)


async def write_log(llm: JsonLLM, payload: dict[str, Any]) -> tuple[LogDraft, dict[str, Any], bool]:
    """返すのは（本文、試行の記録、定型文で埋めたか）。"""
    system = load_prompt("log_writer.md")
    draft, attempts = await ask_with_retry(llm, system, payload, lambda d: validate_log_answer(d, payload["log_number"]))
    record = {"model": llm.model, "prompt_version": prompt_version(system), "attempts": attempts}
    if draft is None:
        return fallback_draft(payload), record, True
    return draft, record, False


def recent_phrases(bodies: list[str]) -> list[str]:
    counts = {p: sum(p in body for body in bodies) for p in WATCH_PHRASES}
    return [f"{p}（直近{len(bodies)}本のうち{n}本）" for p, n in counts.items() if n]
