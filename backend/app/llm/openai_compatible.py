import json
from typing import Any

import httpx


class OpenAICompatibleLLMClient:
    def __init__(self, api_key: str | None, base_url: str, model: str, timeout: float = 30) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def complete_json(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        # APIキーの要らないローカルLLM（Ollama、LM Studio、llama.cpp）では Authorization を付けない。
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
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
        content = response.json()["choices"][0]["message"]["content"].strip()
        # 小さいモデルは ```json で囲んで返すことがある。
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```")
        return json.loads(content)
