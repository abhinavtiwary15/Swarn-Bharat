"""Tests for Settings validation and normalization."""

from __future__ import annotations

from typing import Any

import pytest
from backend.core.config import Settings
from pydantic import ValidationError


def _base_kwargs() -> dict[str, Any]:
    return {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/test_db",
        "REDIS_BASE_URL": "redis://localhost:6379",
        "JWT_SECRET_KEY": "a" * 32,
        "JWT_REFRESH_SECRET_KEY": "b" * 32,
    }


def test_docs_url_normalization() -> None:
    base = _base_kwargs()
    for val in ("", "null", "None", "NULL", "   none   "):
        s = Settings(**base, API_DOCS_URL=val, API_REDOC_URL=val)
        assert s.API_DOCS_URL is None
        assert s.API_REDOC_URL is None

    s2 = Settings(**base, API_DOCS_URL="/custom-docs", API_REDOC_URL="/custom-redoc")
    assert s2.API_DOCS_URL == "/custom-docs"
    assert s2.API_REDOC_URL == "/custom-redoc"


def test_production_validator_rejects_replace_placeholders() -> None:
    base = _base_kwargs()
    base.update(
        {
            "APP_ENV": "production",
            "ENFORCE_HTTPS": True,
            "ALLOWED_HOSTS": ["example.com"],
            "CORS_ORIGINS": ["https://example.com"],
            "JWT_SECRET_KEY": "REPLACE_ME_WITH_A_SECRET_KEY_32BYTES",
        }
    )
    with pytest.raises(ValidationError, match="contains placeholder value"):
        Settings(**base)


def test_production_validator_valid_configuration() -> None:
    base = _base_kwargs()
    base.update(
        {
            "APP_ENV": "production",
            "ENFORCE_HTTPS": True,
            "ALLOWED_HOSTS": ["api.example.com"],
            "CORS_ORIGINS": ["https://app.example.com"],
            "JWT_SECRET_KEY": "x" * 32,
            "JWT_REFRESH_SECRET_KEY": "y" * 32,
            "API_DOCS_URL": None,
        }
    )
    s = Settings(**base)
    assert s.APP_ENV == "production"
    assert s.ENFORCE_HTTPS is True
