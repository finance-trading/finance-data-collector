"""Application configuration loaded from environment variables."""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the local collector.

    All environment-backed options use the ``FDC_`` prefix. Offline parsing
    and reads do not need an SEC identity; network call sites validate it.
    ``quotes_proxy`` is the URL of an HTTP/SOCKS proxy for Yahoo Finance, used
    because Yahoo's edge answers datacenter egress with HTTP 429.
    """

    model_config = SettingsConfigDict(env_prefix="FDC_", case_sensitive=False)

    database_url: str = "postgresql+psycopg://fdc:fdc@localhost:5432/fdc"
    raw_root: str = "./data/raw"
    sec_root: str = "./sec"
    parser_version: str = "filing-parser-v1"
    edgartools_version: str | None = None
    sec_user_agent: str | None = None
    sec_timeout_seconds: float = 30.0
    parse_timeout_seconds: float = 300.0
    retry_max_attempts: int = 3
    retry_base_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 30.0
    quotes_proxy: str | None = None

    def require_sec_user_agent(self) -> str:
        """Return the attributed identity required by a live SEC request."""

        if self.sec_user_agent is None or not self.sec_user_agent.strip():
            raise ValueError("FDC_SEC_USER_AGENT must be explicitly configured")
        return self.sec_user_agent.strip()

    @property
    def resolved_quotes_proxy(self) -> str | None:
        """Proxy for Yahoo Finance, defaulting to the standard ``HTTPS_PROXY``.

        yfinance reaches Yahoo over curl_cffi, which does not honour the
        ``HTTPS_PROXY`` environment variable, so the value is read here and
        handed to yfinance explicitly.  ``FDC_QUOTES_PROXY`` wins when set, for
        when Yahoo should go through a different hop than everything else.
        """

        candidates = (
            self.quotes_proxy,
            os.environ.get("HTTPS_PROXY"),
            os.environ.get("https_proxy"),
        )
        for candidate in candidates:
            if candidate and candidate.strip():
                return candidate.strip()
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings, cached for consistent runtime behavior."""

    return Settings()
