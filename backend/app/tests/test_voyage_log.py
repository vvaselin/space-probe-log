from typing import Any

import pytest

from app.core.config import Settings
from app.llm.factory import get_voyage_llm
from app.llm.mock import MockVoyageLLM
from app.llm.openai_compatible import OpenAICompatibleLLMClient
from app.voyage.llm import llm_chooser, validate_log_answer, write_log
from app.voyage.route import START_AT, plan_leg
from app.voyage.service import create_voyage, current_logs, load_legs, rewrite, step
from app.voyage.store import LogRecord, open_session
from app.voyage.world import load_world

GOOD_BODY = "月が前方の光学センサーの視野を埋めている。" * 10


class ScriptedLLM:
    """決めた答えを順に返す。呼ばれた回数と受け取った入力を残す。"""

    def __init__(self, answers: list[Any]) -> None:
        self.answers = answers
        self.calls: list[dict[str, Any]] = []
        self.model = "scripted"

    async def complete_json(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        answer = self.answers[len(self.calls) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture()
def db_url() -> str:
    return "sqlite://"  # テストごとに新しいメモリ上のDB


async def test_step_writes_one_log_per_scene_with_mock_and_no_network(db_url: str) -> None:
    db = open_session(db_url)
    voyage = create_voyage(db, "test-seed")
    world = load_world()
    route_llm, log_llm = MockVoyageLLM("route", "test-seed"), MockVoyageLLM("log")
    records = [await step(db, voyage, world, route_llm, log_llm) for _ in range(8)]
    assert all(r is not None for r in records)
    logs = current_logs(db, voyage.id)
    assert [log.log_number for log in logs] == list(range(1, 9))
    first = logs[0]
    assert first.llm_input["scene"]["kind"] == "出発"
    assert "NOCTUA-7" in first.body_markdown and "LOG #001" in first.body_markdown
    assert {s["id"] for s in first.llm_input["internal"]["sightings"]} >= {"sun", "earth", "moon"}
    assert len(first.llm_input["visible"]) <= 3 + 3
    assert all("magnitude" not in s and "size_ratio" not in s for s in first.llm_input["visible"])
    assert first.llm_input["next_destination"]["name"] == "月"
    assert first.llm_input["next_destination"]["remaining_time"].startswith("約")
    assert first.llm_input["speed"]["state"] == "停止"
    assert "加速" in first.llm_input["scene"]["meaning"]
    states = {log.llm_input["speed"]["state"] for log in logs}
    assert states & {"加速中", "巡航中", "減速中"}
    # 最接近の場面では、次の区間が先に決まっている
    legs = load_legs(db, voyage.id)
    closest = next(log for log in logs if log.llm_input["scene"]["kind"] == "最接近・到着")
    assert closest.llm_input["next_destination"]["name"] == legs[closest.leg_index + 1].target.name
    assert len(logs[-1].llm_input["recent_logs"]) == 3
    assert any(s["change"] for s in logs[1].llm_input["visible"])


async def test_rewrite_uses_the_saved_input_and_adds_a_revision(db_url: str) -> None:
    db = open_session(db_url)
    voyage = create_voyage(db, "test-seed")
    world = load_world()
    original = await step(db, voyage, world, MockVoyageLLM("route"), MockVoyageLLM("log"))
    assert original is not None
    llm = ScriptedLLM([{"title": "書き直し", "summary": "書き直した", "body": GOOD_BODY}])
    again = await rewrite(db, original.id, llm)
    sent = {k: v for k, v in original.llm_input.items() if k != "internal"}
    assert llm.calls == [sent]
    assert again.revision == 2 and again.log_number == original.log_number
    assert current_logs(db, voyage.id)[0].id == again.id
    assert db.query(LogRecord).count() == 2


async def test_log_is_retried_once_then_filled_with_a_fixed_text() -> None:
    db_payload = await _sample_payload()
    llm = ScriptedLLM([{"title": "x"}, ValueError("broken json")])
    draft, record, fallback = await write_log(llm, db_payload)
    assert fallback is True and len(llm.calls) == 2
    assert "previous_output_problem" in llm.calls[1]
    assert "本文の生成に失敗した" in draft.body
    assert len(record["attempts"]) == 2


async def test_second_attempt_can_succeed() -> None:
    payload = await _sample_payload()
    llm = ScriptedLLM([{"title": "t", "summary": "s", "body": "短い"}, {"title": "t", "summary": "s", "body": GOOD_BODY}])
    draft, _, fallback = await write_log(llm, payload)
    assert fallback is False and draft.body == GOOD_BODY


def test_avoided_body_words_are_rejected() -> None:
    with pytest.raises(ValueError, match="船内"):
        validate_log_answer({"title": "t", "summary": "s", "body": GOOD_BODY + "船内は静かだ。"}, log_number=1)
    with pytest.raises(ValueError, match="窓"):
        validate_log_answer({"title": "t", "summary": "s", "body": GOOD_BODY + "窓の外。"}, log_number=4)
    validate_log_answer({"title": "t", "summary": "s", "body": GOOD_BODY + "窓——いや、広角光学センサー越しに。"}, log_number=1)


def test_literal_backslash_n_in_body_becomes_a_newline() -> None:
    draft = validate_log_answer({"title": "t", "summary": "s", "body": GOOD_BODY + "\\n\\n次へ。"}, log_number=1)
    assert "\\n" not in draft.body and draft.body.endswith("\n\n次へ。")


async def test_route_answer_outside_the_offer_uses_the_top_candidate() -> None:
    llm = ScriptedLLM([{"choice": 9, "reason": "?"}, {"choice": "1"}])
    leg = await plan_leg(load_world(), [], START_AT, llm_chooser(llm, load_world()))
    assert leg is not None and leg.planning.fell_back is True
    assert leg.target.id == leg.planning.candidates[0].id
    assert len(leg.planning.llm_raw["attempts"]) == 2


def test_llm_provider_is_chosen_explicitly_per_purpose() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="sk-openai",
        voyage_llm_route_provider="openai_compatible",
        voyage_llm_route_base_url="http://localhost:11434/v1",
        voyage_llm_route_model="qwen2.5:7b",
        voyage_llm_log_provider="openai_compatible",
        voyage_llm_log_model="gpt-4.1",
    )
    route = get_voyage_llm("route", settings=settings)
    log = get_voyage_llm("log", settings=settings)
    assert isinstance(route, OpenAICompatibleLLMClient) and route.api_key is None and route.model == "qwen2.5:7b"
    assert isinstance(log, OpenAICompatibleLLMClient) and log.api_key == "sk-openai" and log.model == "gpt-4.1"
    assert isinstance(get_voyage_llm("log", settings=Settings(_env_file=None, openai_api_key="sk")), MockVoyageLLM)


async def _sample_payload() -> dict[str, Any]:
    from app.voyage.service import build_log_payload

    leg = await plan_leg(load_world(), [], START_AT, llm_chooser(MockVoyageLLM("route"), load_world()))
    assert leg is not None
    return build_log_payload(load_world(), START_AT, [leg], 0, 0, 1, {}, [])
