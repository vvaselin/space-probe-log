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
            "title must be a string. summary must be a string. body_markdown must be a markdown string. "
            "reliability must be a number from 0.0 to 1.0. "
            "Write like a quiet first-person navigation journal from OVIS, not a dry report. "
            "Use restrained wonder grounded in sensor facts, similar to a fictional exploration blog. "
            "Avoid merely repeating the action summary or turning the body into bullet points. "
            "The application will prepend the transmission header, so do not invent dates or locations. "
            "Observation facts may include sighting_level: detected, resolved, or confirmed. "
            "detected means the sensor only picked up a faint sign; narrate it as an unconfirmed sighting. "
            "resolved means it matches a known object and can be named. "
            "confirmed means an explicit observe or investigate action verified it. "
            "For move logs, include passive_sighting or passive_signal details when present so the log is not only a distance report. "
            "The markdown body must include separate sections named '確認済みの事実' and 'OVISの解釈'. "
            "Do not add unconfirmed world facts, damage, resources, life, or discoveries. "
            f"Log writer style:\n{prompts.get('log_writer_style', '')}",
            context.model_dump(),
        )
        try:
            normalized = normalize_generated_log_payload(data, context.event["summary"])
            if not normalized["body_markdown"]:
                raise ValueError("missing body_markdown")
            return GeneratedLog.model_validate(normalized)
        except (ValidationError, TypeError, ValueError):
            return GeneratedLog(
                title="INSOMNIA-07 航行ログ",
                summary=context.event["summary"],
                body_markdown=(
                    "## 確認済みの事実\n"
                    "ログ生成応答が不正だったため、入力された観測事実だけを保存しました。\n\n"
                    "## OVISの解釈\n"
                    "通信文の整形に失敗しました。記録の信頼度を下げて保持します。\n\n"
                    f"## 航行メモ\n{context.event['summary']}"
                ),
                reliability=0.5,
            )
