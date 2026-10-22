"""Application settings, loaded from environment variables / backend/.env."""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "production", "test"] = "development"

    database_url: str
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = ""

    file_storage_path: str = "/var/crm/documents"
    allowed_origins: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @model_validator(mode="after")
    def _check_secrets(self) -> "Settings":
        if len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        if self.is_production and "CHANGE_ME" in (self.secret_key + self.database_url):
            raise ValueError("Placeholder values from .env.example are not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
