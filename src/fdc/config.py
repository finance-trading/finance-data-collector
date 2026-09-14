"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the local collector.

    All environment-backed options use the ``FDC_`` prefix.  SEC identity is
    intentionally required so live requests cannot run without attribution.
    """

    model_config = SettingsConfigDict(env_prefix="FDC_", case_sensitive=False)

    database_url: str = "postgresql+psycopg://fdc:fdc@localhost:5432/fdc"
    raw_root: str = "./data/raw"
    sec_user_agent: str | None = None
    sec_timeout_seconds: float = 30.0
    retry_max_attempts: int = 3
    retry_base_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 30.0

    @field_validator("sec_user_agent")
    @classmethod
    def require_sec_user_agent(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("FDC_SEC_USER_AGENT must be explicitly configured")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings, cached for consistent runtime behavior."""

    return Settings()
