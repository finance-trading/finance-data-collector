import pytest

from fdc.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_offline_settings_do_not_require_sec_user_agent(monkeypatch):
    monkeypatch.delenv("FDC_SEC_USER_AGENT", raising=False)

    settings = get_settings()

    assert settings.sec_user_agent is None


def test_live_sec_identity_rejects_blank_sec_user_agent(monkeypatch):
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "   ")

    settings = get_settings()

    with pytest.raises(ValueError, match="FDC_SEC_USER_AGENT"):
        settings.require_sec_user_agent()


def test_settings_defaults_and_environment_overrides(monkeypatch):
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "Research Bot research@example.com")
    monkeypatch.setenv("FDC_DATABASE_URL", "sqlite:///collector.db")
    monkeypatch.setenv("FDC_RAW_ROOT", "/tmp/raw")
    monkeypatch.setenv("FDC_SEC_TIMEOUT_SECONDS", "17")
    monkeypatch.setenv("FDC_PARSE_TIMEOUT_SECONDS", "23")
    monkeypatch.setenv("FDC_RETRY_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("FDC_RETRY_BASE_DELAY_SECONDS", "0.25")
    monkeypatch.setenv("FDC_RETRY_MAX_DELAY_SECONDS", "9")

    settings = get_settings()

    assert settings.database_url == "sqlite:///collector.db"
    assert settings.raw_root == "/tmp/raw"
    assert settings.sec_user_agent == "Research Bot research@example.com"
    assert settings.sec_timeout_seconds == 17
    assert settings.parse_timeout_seconds == 23
    assert settings.retry_max_attempts == 5
    assert settings.retry_base_delay_seconds == 0.25
    assert settings.retry_max_delay_seconds == 9


def test_settings_use_raw_root_default(monkeypatch):
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "Research Bot research@example.com")
    for key in (
        "FDC_DATABASE_URL",
        "FDC_RAW_ROOT",
        "FDC_SEC_TIMEOUT_SECONDS",
        "FDC_PARSE_TIMEOUT_SECONDS",
        "FDC_RETRY_MAX_ATTEMPTS",
        "FDC_RETRY_BASE_DELAY_SECONDS",
        "FDC_RETRY_MAX_DELAY_SECONDS",
        "FDC_QUOTES_PROXY",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = get_settings()

    assert settings.raw_root == "./data/raw"
    assert settings.parse_timeout_seconds == 300


def _clear_proxy_env(monkeypatch):
    for key in ("FDC_QUOTES_PROXY", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(key, raising=False)


def test_quotes_proxy_defaults_to_the_standard_https_proxy(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")

    assert get_settings().resolved_quotes_proxy == "http://127.0.0.1:7890"


def test_explicit_quotes_proxy_wins_over_https_proxy(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://general:1080")
    monkeypatch.setenv("FDC_QUOTES_PROXY", "socks5://yahoo-only:1080")

    assert get_settings().resolved_quotes_proxy == "socks5://yahoo-only:1080"


def test_blank_quotes_proxy_falls_back_to_https_proxy(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("FDC_QUOTES_PROXY", "   ")

    assert get_settings().resolved_quotes_proxy == "http://127.0.0.1:7890"


def test_no_proxy_anywhere_resolves_to_none(monkeypatch):
    _clear_proxy_env(monkeypatch)

    assert get_settings().resolved_quotes_proxy is None
