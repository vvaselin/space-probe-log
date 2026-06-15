from typing import Protocol

from app.schemas.domain import ActionContext, GeneratedLog, LogContext, ProposedAction


class LLMClient(Protocol):
    async def propose_action(self, context: ActionContext) -> ProposedAction:
        ...

    async def generate_log(self, context: LogContext) -> GeneratedLog:
        ...
