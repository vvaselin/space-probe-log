from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Space Probe Log"
    database_url: str = "sqlite:///./space_probe_log.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"
    default_world_seed: str = "sol-neighborhood-001"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-6-luna"
    prompt_dir: str = "app/prompts"
    admin_username: str = "admin"
    admin_password_hash: str | None = None
    admin_session_ttl_seconds: int = 43_200
    admin_cookie_secure: bool = False
    admin_session_cookie_name: str = "space_probe_admin"
    simulation_tick_interval_seconds: float = 1.8
    scheduler_lease_seconds: int = 30
    simulation_scheduler_enabled: bool = True
    # 再設計版の航行（app/voyage）。CLI は標準でデバッグ用DBを使う。
    voyage_database_url: str = "sqlite:///./voyage.db"
    voyage_debug_database_url: str = "sqlite:///./voyage_debug.db"
    # 用途ごとの LLM。base_url・model・api_key を省くと OPENAI_* を使う（base_url を変えた時は OPENAI_API_KEY を送らない）。
    voyage_llm_route_provider: Literal["mock", "openai_compatible"] = "mock"
    voyage_llm_route_base_url: str | None = None
    voyage_llm_route_model: str | None = None
    voyage_llm_route_api_key: str | None = None
    voyage_llm_log_provider: Literal["mock", "openai_compatible"] = "mock"
    voyage_llm_log_base_url: str | None = None
    voyage_llm_log_model: str | None = None
    voyage_llm_log_api_key: str | None = None
    voyage_llm_timeout_seconds: float = 120.0

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
