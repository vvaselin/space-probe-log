from typing import Any, Protocol

from app.schemas.domain import ActionContext, GeneratedLog, LogContext, ProposedAction


class LLMClient(Protocol):
    async def propose_action(self, context: ActionContext) -> ProposedAction:
        ...

    async def generate_log(self, context: LogContext) -> GeneratedLog:
        ...


class JsonLLM(Protocol):
    """再設計版の航行（app/voyage）が使う口。system と JSON を渡し、JSON を受け取る。"""

    model: str

    async def complete_json(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...
