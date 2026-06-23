import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.schemas.domain import ActionContext, GeneratedLog, LogContext, ProposedAction


def normalize_generated_log_payload(data: dict[str, Any], fallback_summary: str) -> dict[str, Any]:
    return {
        "title": data.get("title") or "INSOMNIA-07 航行ログ",
        "summary": data.get("summary") or fallback_summary,
        "body_markdown": data.get("body_markdown") or data.get("body") or "",
        "reliability": data.get("reliability", 0.75),
    }


class OpenAICompatibleLLMClient:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def _complete_json(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                },
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    async def propose_action(self, context: ActionContext) -> ProposedAction:
        prompts = context.prompt_settings
        data = await self._complete_json(
            "Return only JSON with keys: action, target_id, reason. You are OVIS aboard INSOMNIA-07. "
            "You may propose but never mutate state. Prefer known signal investigation before long-distance travel. "
            "If there are no visible_signals and navigation_targets is not empty, prefer move to one navigation target instead of repeating observe. "
            "Never invent world facts, damage, resources, life, or discoveries. "
            f"Probe profile:\n{prompts.get('probe_profile', '')}\n\n"
            f"Action policy:\n{prompts.get('action_policy', '')}",
            context.model_dump(),
        )
        return ProposedAction.model_validate(data)

    async def generate_log(self, context: LogContext) -> GeneratedLog:
        prompts = context.prompt_settings
        data = await self._complete_json(
            "Return only JSON with exactly these keys: title, summary, body_markdown, reliability. "
            "Use only the mission_clock, simulation_datetime, navigation_state, physical distances, speeds, ETA, position, route, observations, interpretations, nearby_bodies, nearby_environment_objects, and route_context present in the payload. "
            "Do not invent distances, speeds, arrival times, or drive modes; those values are calculated by Python. "
            "Never invent dates or use placeholders like 2024, 2026, XX, or ??. "
            "Write like a quiet first-person navigation journal from OVIS, not a dry report. "
            "If route_phase is course_plotted, describe the route decision while the probe remains stopped. "
            "If route_phase is accelerating, cruising, or decelerating, describe gradual motion and the given velocity/remaining_distance. "
            "If route_phase is arrived, describe the arrival and zero velocity. "
            "For progress_01, progress_50, and progress_99, never write a percentage or describe progress numerically. "
            "Describe them as post-departure acceleration, a mid-route observation, or pre-arrival deceleration, focusing on distance, speed, remaining distance, and scenery. "
            "Observation facts may include sighting_level: detected, resolved, or confirmed. "
            "detected means the sensor only picked up a faint sign; narrate it as an unconfirmed sighting. "
            "resolved means it matches a known object and can be named. "
            "confirmed means an explicit observe or investigate action verified it. "
            "Never mention a celestial body or environment object that is absent from observations, nearby_bodies, and nearby_environment_objects. "
            "Use route_context.route_hazards only as predicted display-space crossings or near passes. Never invent a hazard, claim a collision, or treat a predicted hazard as confirmed damage. "
            "Treat passive_sighting and passive_signal only as weak detection, parallax, spectral hints, reflected light, occultation, or scattered light; never promote them to confirmed discoveries. "
            "Do not add unconfirmed world facts, damage, resources, life, or discoveries. "
            "Do not use fixed report sections named '確認済みの事実', 'OVISの解釈', or '記録'. "
            "Prefer the required INSOMNIA navigation-log shape from the style prompt. "
            f"Log writer style:\n{prompts.get('log_writer_style', '')}",
            context.model_dump(),
        )
        try:
            normalized = normalize_generated_log_payload(data, context.event["summary"])
            if not normalized["body_markdown"]:
                raise ValueError("missing body_markdown")
            return GeneratedLog.model_validate(normalized)
        except (ValidationError, TypeError, ValueError):
            log_number = int(context.probe_snapshot.get("log_number", context.probe_snapshot["mission_time"]))
            mission_clock = context.probe_snapshot.get("mission_clock", "2080/05/02 12:00:00 UTC")
            return GeneratedLog(
                title="INSOMNIA-07 航行ログ",
                summary=context.event["summary"],
                body_markdown=(
                    "# INSOMNIA 航行ログ\n"
                    "**探査機: INSOMNIA-07**\n"
                    "**搭載AI: OVIS**\n\n"
                    f"## LOG #{log_number:03d}\n"
                    f"**{mission_clock} - {context.event['event_type']}**\n\n"
                    f"{context.event['summary']}\n\n"
                    "ログ生成応答の整形に失敗したため、入力された観測事実のみを保存した。"
                ),
                reliability=0.5,
            )
