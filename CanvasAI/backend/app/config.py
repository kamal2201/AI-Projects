from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)
else:
    load_dotenv(override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH) if ENV_PATH.exists() else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CanvasAI Stream API"
    environment: str = "development"
    google_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    temperature: Optional[float] = None
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

    @property
    def effective_api_key(self) -> str:
        key = (
            self.gemini_api_key
            or self.google_api_key
            or os.environ.get("GEMINI_API_KEY", "")
            or os.environ.get("GOOGLE_API_KEY", "")
        )
        return key.strip().strip('"').strip("'")


@lru_cache
def get_settings() -> Settings:
    return Settings()
