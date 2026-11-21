from typing import Any, Protocol


class JsonLLM(Protocol):
    """航行（app/voyage）が使う LLM の口。system と JSON を渡し、JSON を受け取る。"""

    model: str

    async def complete_json(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...
