"""
Application configuration loaded from environment variables.

All sensitive values (credentials, tokens) come exclusively from .env.
No secrets are hardcoded anywhere in this file.

Environment variables expected (see .env.example):
  ST_CLIENT_ID        — ServiceTitan OAuth client ID
  ST_CLIENT_SECRET    — ServiceTitan OAuth client secret
  ST_APP_KEY          — ServiceTitan application key (sent as ST-App-Key header)
  ST_TENANT_ID        — ServiceTitan tenant ID
  ST_AUTH_URL         — OAuth token endpoint (default: https://auth.servicetitan.io/connect/token)
  ST_API_BASE         — API base URL (default: https://api.servicetitan.io)
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Loaded once at startup; never mutated at runtime."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Silently ignore unrecognised env vars
        case_sensitive=False,
    )

    # -------------------------------------------------------------------------
    # ServiceTitan OAuth credentials (all required — startup fails if missing)
    # -------------------------------------------------------------------------
    st_client_id: str = Field(..., min_length=1, description="OAuth client ID")
    st_client_secret: SecretStr = Field(..., description="OAuth client secret")
    st_app_key: SecretStr = Field(..., description="ST-App-Key header value")
    st_tenant_id: str = Field(..., min_length=1, description="ServiceTitan tenant ID")

    # -------------------------------------------------------------------------
    # API endpoints
    # -------------------------------------------------------------------------
    st_auth_url: str = Field(
        default="https://auth.servicetitan.io/connect/token",
        description="OAuth token endpoint",
    )
    st_api_base: str = Field(
        default="https://api.servicetitan.io",
        description="ServiceTitan REST API base URL (no trailing slash)",
    )

    # -------------------------------------------------------------------------
    # HTTP timeouts (seconds)
    # -------------------------------------------------------------------------
    http_connect_timeout: float = Field(default=5.0, ge=1.0, le=30.0)
    http_read_timeout: float = Field(default=10.0, ge=1.0, le=60.0)
    http_total_timeout: float = Field(default=30.0, ge=5.0, le=120.0)

    # -------------------------------------------------------------------------
    # Retry
    # -------------------------------------------------------------------------
    http_max_retries: int = Field(default=3, ge=0, le=5)

    # -------------------------------------------------------------------------
    # Token refresh: refresh this many seconds before the token actually expires
    # -------------------------------------------------------------------------
    token_refresh_buffer_seconds: int = Field(default=60, ge=10, le=300)

    # -------------------------------------------------------------------------
    # Rate limiting (our MCP server limits, independent of ServiceTitan's own)
    # -------------------------------------------------------------------------
    max_queries_per_minute: int = Field(default=10, ge=1, le=100)
    max_queries_per_hour: int = Field(default=100, ge=1, le=1000)

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/mcp_server.log")

    # -------------------------------------------------------------------------
    # Optional Redis caching
    # -------------------------------------------------------------------------
    redis_url: str | None = Field(default=None)
    cache_ttl: int = Field(default=300, ge=30, le=3600)

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper

    @field_validator("st_auth_url", "st_api_base")
    @classmethod
    def _require_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("All API URLs must use HTTPS")
        return v.rstrip("/")

    @field_validator("st_tenant_id")
    @classmethod
    def _validate_tenant_id(cls, v: str) -> str:
        # Tenant IDs are numeric strings in ServiceTitan
        if not v.strip().isdigit():
            raise ValueError("st_tenant_id must be a numeric string")
        return v.strip()

    # -------------------------------------------------------------------------
    # Computed properties (no secrets returned)
    # -------------------------------------------------------------------------

    def api_v2_tenant_base(self, module: str) -> str:
        """
        Full base path for a v2 tenant-scoped API call.

        ServiceTitan URL structure:
          {api_base}/{module}/v2/tenant/{tenant_id}/{resource}

        Args:
            module: API module name, e.g. "jpm", "crm", "reporting".

        Example:
            settings.api_v2_tenant_base("jpm") + "/technicians"
            → https://api.servicetitan.io/jpm/v2/tenant/1234567/technicians
        """
        return f"{self.st_api_base}/{module}/v2/tenant/{self.st_tenant_id}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the singleton Settings instance.

    Cached after first call. Raises ValidationError if any required env var
    is missing or invalid — fail fast at startup, not mid-request.
    """
    return Settings()
