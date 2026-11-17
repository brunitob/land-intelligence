"""Configuración central: variables de entorno + YAML en config/."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://patagonia:patagonia@localhost:5432/patagonia_land"

    user_agent: str = "PatagoniaLandBot/0.1"
    request_delay_seconds: float = 2.0
    request_timeout_seconds: float = 20.0
    respect_robots: bool = True
    enable_playwright: bool = False
    max_response_bytes: int = 8_000_000

    anthropic_api_key: str = ""
    llm_model: str = "claude-haiku-5-5"
    llm_enabled: bool = False

    ors_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    api_token: str = ""

    # Monitoreo: cuántas ausencias consecutivas (en corridas sanas) antes de marcar REMOVED.
    removal_missed_runs: int = 3
    # Si una corrida encuentra menos de esta fracción de lo habitual, se considera posible rotura.
    broken_run_ratio: float = 0.5

    @property
    def llm_available(self) -> bool:
        return self.llm_enabled and bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with path.open() as fh:
        return yaml.safe_load(fh) or {}
