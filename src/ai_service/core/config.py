"""Application configuration loaded and validated from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory for ai-service
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


class Settings(BaseSettings):
    # Application settings with strict environment choices
    ENVIRONMENT: Literal["development", "staging", "production", "testing"] = (
        "development"
    )
    DEBUG: bool = True
    PROJECT_NAME: str = "ai-service"
    API_V1_PREFIX: str = "/api/v1"

    # Strictly required: No defaults. Must come from .env or environment
    SECRET_KEY: str = Field(
        ...,
        min_length=32,
        description="Secret key for JWT generation; must be at least 32 characters.",
    )
    DATABASE_URL: str = Field(
        ...,
        description="Async database connection URL, e.g. postgresql+asyncpg://...",
    )

    # Security settings
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=1440, gt=0)

    # Optional / Test settings
    TEST_DATABASE_URL: str = "sqlite+aiosqlite:///:memory:"

    # Uploads & Limits (bytes, must be positive)
    MAX_UPLOAD_SIZE_BYTES: int = Field(default=20 * 1024 * 1024, gt=0)

    # Browser origins allowed to call the API, as a JSON list in .env, e.g. ["http://localhost:3000"].
    # Empty means no CORS middleware at all.
    CORS_ORIGINS: list[str] = Field(default_factory=list)

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        valid_prefixes = ("postgresql+asyncpg://", "sqlite+aiosqlite://")
        if not any(v.startswith(prefix) for prefix in valid_prefixes):
            raise ValueError(
                f"DATABASE_URL must start with one of {valid_prefixes}. Got: {v}"
            )
        return v

    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
