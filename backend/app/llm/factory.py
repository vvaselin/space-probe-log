from app.core.config import get_settings
from app.llm.client import LLMClient
from app.llm.mock import MockLLMClient
from app.llm.openai_compatible import OpenAICompatibleLLMClient


def get_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.openai_api_key:
        return OpenAICompatibleLLMClient(settings.openai_api_key, settings.openai_base_url, settings.openai_model)
    return MockLLMClient()
