from typing import Literal

from app.core.config import Settings, get_settings
from app.llm.client import JsonLLM
from app.llm.mock import MockVoyageLLM
from app.llm.openai_compatible import OpenAICompatibleLLMClient


def get_voyage_llm(purpose: Literal["route", "log"], seed: str = "", settings: Settings | None = None) -> JsonLLM:
    """用途（route＝行き先の選択、log＝ログ本文）ごとに、mock か openai_compatible を明示して選ぶ。"""
    s = settings or get_settings()
    if getattr(s, f"voyage_llm_{purpose}_provider") == "mock":
        return MockVoyageLLM(purpose, seed)
    base_url: str | None = getattr(s, f"voyage_llm_{purpose}_base_url")
    # 接続先を変えた時は、OpenAI 用のキーを別のサーバーへ送らない。
    api_key = getattr(s, f"voyage_llm_{purpose}_api_key") or (s.openai_api_key if base_url is None else None)
    model: str = getattr(s, f"voyage_llm_{purpose}_model") or s.openai_model
    return OpenAICompatibleLLMClient(api_key, base_url or s.openai_base_url, model, s.voyage_llm_timeout_seconds)
