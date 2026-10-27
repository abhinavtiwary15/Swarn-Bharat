"""Application settings and configuration validation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Any

from pydantic import BeforeValidator, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)

_REPO_ROOT: Path = Path(__file__).parents[4].resolve()


def _parse_str_list(v: Any) -> list[str]:
    """Accept both a comma-separated string and a JSON array."""
    if isinstance(v, list):
        return [str(i) for i in v]
    if isinstance(v, str):
        stripped = v.strip()
        if stripped.startswith("["):
            try:
                return [str(i) for i in json.loads(stripped)]
            except json.JSONDecodeError:
                pass
        return [i.strip() for i in stripped.split(",") if i.strip()]
    raise ValueError(f"Cannot parse as list[str]: {v!r}")


StrList = Annotated[list[str], NoDecode, BeforeValidator(_parse_str_list)]


def _redis_url(base: str, db: int) -> str:
    return f"{base.rstrip('/')}/{db}"


class Settings(BaseSettings):
    """Central configuration for backend services."""

    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: str = "development"
    ENFORCE_HTTPS: bool = False
    ALLOWED_HOSTS: StrList = ["*"]
    CORS_ORIGINS: StrList = []

    API_TITLE: str = "Swarn Bharat API"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = (
        "REST API for the Swarn Bharat platform.\n\n"
        "### Architecture & Contracts\n"
        "- All responses adhere to standard envelopes: `SuccessEnvelope[T]` on success "
        "and `ErrorResponse` on failure.\n"
        "- Authentication uses Bearer JWT tokens. Access tokens expire in 15 minutes; "
        "refresh tokens expire in 7 days with single-use rotation.\n"
        "- Rate limiting is enforced using fixed windows with standard 429 status "
        "and `Retry-After` headers.\n"
        "- Degraded downstream dependencies trigger 503 Service Unavailable "
        "with `Retry-After` headers."
    )
    API_DOCS_URL: str | None = "/api/v1/docs"
    API_REDOC_URL: str | None = "/api/v1/redoc"
    OPENAPI_URL: str = "/api/v1/openapi.json"

    @field_validator("API_DOCS_URL", "API_REDOC_URL", mode="before")
    @classmethod
    def _normalize_docs_url(cls, v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, str) and v.strip().lower() in ("", "null", "none"):
            return None
        return str(v) if v is not None else None

    DATABASE_URL: str

    REDIS_BASE_URL: str = "redis://localhost:6379"
    REDIS_DB_CELERY_BROKER: int = 0
    REDIS_DB_CELERY_RESULT: int = 1
    REDIS_DB_TOKENS: int = 2
    REDIS_DB_RATE_LIMIT: int = 3
    REDIS_DB_LOGIN_THROTTLE: int = 4

    @property
    def celery_broker_url(self) -> str:
        return _redis_url(self.REDIS_BASE_URL, self.REDIS_DB_CELERY_BROKER)

    @property
    def celery_result_backend(self) -> str:
        return _redis_url(self.REDIS_BASE_URL, self.REDIS_DB_CELERY_RESULT)

    JWT_SECRET_KEY: str
    JWT_REFRESH_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    REFRESH_GRACE_WINDOW_SECONDS: int = 30

    GOOGLE_CLIENT_ID: str | None = None

    LOGIN_RATE_LIMIT_TIMES: int = 5
    LOGIN_RATE_LIMIT_SECONDS: int = 60
    MAX_LOGIN_ATTEMPTS: int = 10
    LOGIN_LOCKOUT_SECONDS: int = 900

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.APP_ENV in ("development", "test"):
            return self

        errors: list[str] = []

        for field_name, field_val in self:
            if isinstance(field_val, str) and field_val.startswith("REPLACE_"):
                errors.append(f"{field_name} contains placeholder value {field_val!r}")

        access_bytes = self.JWT_SECRET_KEY.encode()
        refresh_bytes = self.JWT_REFRESH_SECRET_KEY.encode()
        if len(access_bytes) < 32:
            errors.append("JWT_SECRET_KEY must be at least 32 bytes")
        if len(refresh_bytes) < 32:
            errors.append("JWT_REFRESH_SECRET_KEY must be at least 32 bytes")
        if self.JWT_SECRET_KEY == self.JWT_REFRESH_SECRET_KEY:
            errors.append("JWT_SECRET_KEY and JWT_REFRESH_SECRET_KEY must differ")

        if self.ALLOWED_HOSTS == ["*"]:
            errors.append("ALLOWED_HOSTS must be restricted in production (not '*')")
        if not self.CORS_ORIGINS:
            errors.append("CORS_ORIGINS must be set in production")
        if not self.ENFORCE_HTTPS:
            errors.append("ENFORCE_HTTPS must be true in production")

        if errors:
            raise ValueError(
                "Production configuration is invalid:\n" + "\n".join(f"  • {e}" for e in errors)
            )

        if self.API_DOCS_URL is not None:
            logger.warning(
                "API_DOCS_URL=%r is enabled in production. "
                "Consider setting API_DOCS_URL=null to disable Swagger UI.",
                self.API_DOCS_URL,
            )

        return self


settings: Settings = Settings()
