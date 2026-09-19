from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SAMPLE_SECRET_PREFIX = "dev-only-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "StockSense API"
    environment: Literal["development", "production"] = "development"

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "stocksense"

    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    cookie_name: str = "access_token"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    first_admin_email: str = ""
    first_admin_password: str = ""
    first_admin_name: str = "Administrator"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    @model_validator(mode="after")
    def _reject_sample_secret_in_production(self) -> "Settings":
        if self.environment == "production" and self.jwt_secret_key.startswith(SAMPLE_SECRET_PREFIX):
            raise ValueError("JWT_SECRET_KEY is still the sample value; generate a real one for production")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment / .env
