import pytest

from fdc.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_settings_require_explicit_sec_user_agent(monkeypatch):
    monkeypatch.delenv("FDC_SEC_USER_AGENT", raising=False)
    with pytest.raises(ValueError, match="FDC_SEC_USER_AGENT"):
        get_settings()


def test_settings_reject_blank_sec_user_agent(monkeypatch):
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "   ")
    with pytest.raises(ValueError, match="FDC_SEC_USER_AGENT"):
        get_settings()


def test_settings_defaults_and_environment_overrides(monkeypatch):
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "Research Bot research@example.com")
    monkeypatch.setenv("FDC_DATABASE_URL", "sqlite:///collector.db")
    monkeypatch.setenv("FDC_RAW_ROOT", "/tmp/raw")
    monkeypatch.setenv("FDC_SEC_TIMEOUT_SECONDS", "17")
    monkeypatch.setenv("FDC_RETRY_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("FDC_RETRY_BASE_DELAY_SECONDS", "0.25")
    monkeypatch.setenv("FDC_RETRY_MAX_DELAY_SECONDS", "9")

    settings = get_settings()

    assert settings.database_url == "sqlite:///collector.db"
    assert settings.raw_root == "/tmp/raw"
    assert settings.sec_user_agent == "Research Bot research@example.com"
    assert settings.sec_timeout_seconds == 17
    assert settings.retry_max_attempts == 5
    assert settings.retry_base_delay_seconds == 0.25
    assert settings.retry_max_delay_seconds == 9


def test_settings_use_raw_root_default(monkeypatch):
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "Research Bot research@example.com")
    for key in (
        "FDC_DATABASE_URL",
        "FDC_RAW_ROOT",
        "FDC_SEC_TIMEOUT_SECONDS",
        "FDC_RETRY_MAX_ATTEMPTS",
        "FDC_RETRY_BASE_DELAY_SECONDS",
        "FDC_RETRY_MAX_DELAY_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = get_settings()

    assert settings.raw_root == "./data/raw"
