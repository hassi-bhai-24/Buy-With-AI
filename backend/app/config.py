"""Application settings (pydantic-settings).

The default SQLite file lives next to this package (the backend directory),
regardless of the process working directory. Setting the DATABASE_URL
environment variable overrides it entirely (used by tests).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_database_url() -> str:
    backend_dir = Path(__file__).resolve().parent.parent
    return f"sqlite+aiosqlite:///{backend_dir / 'buy_with_ai.db'}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Buy with AI Backend"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    DATABASE_URL: str = _default_database_url()
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    CACHE_TTL_HOURS: int = 6
    RATE_LIMIT_PER_MINUTE: int = 30
    MAX_CONCURRENT_SCRAPES: int = 4
    REQUEST_TIMEOUT_SECONDS: int = 30
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
