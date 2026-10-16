"""Daily quote generator: market cap enrichment and cache safety."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pandas as pd
import pytest
from yfinance.config import YfConfig

from fdc import quotes


def _write_cache(path, payload: dict) -> None:
    path.write_text(json.dumps(payload))


class _FakeFastInfo(dict):
    def __getitem__(self, key):
        if key not in self:
            raise KeyError(key)
        return super().__getitem__(key)


class _FakeTicker:
    def __init__(self, ticker: str, caps: dict[str, object]) -> None:
        self._ticker = ticker
        self._caps = caps

    @property
    def fast_info(self) -> _FakeFastInfo:
        return _FakeFastInfo({"marketCap": self._caps.get(self._ticker)})


class _FakeYFinance:
    def __init__(self, caps: dict[str, object], fail: set[str] = frozenset()) -> None:
        self._caps = caps
        self._fail = fail
        self.seen: list[str] = []

    def Ticker(self, ticker: str) -> _FakeTicker:
        if ticker in self._fail:
            raise RuntimeError(f"boom {ticker}")
        self.seen.append(ticker)
        return _FakeTicker(ticker, self._caps)


def test_market_caps_rounds_to_integers_and_drops_missing(monkeypatch):
    caps = {"NVDA": 5649190576309.2, "VRT": 97086314647.4, "AMD": 0, "GOOG": None}
    fake = _FakeYFinance(caps)
    monkeypatch.setattr(quotes.yf, "Ticker", fake.Ticker)

    result = quotes._market_caps(["NVDA", "VRT", "AMD", "GOOG"])

    assert result == {"NVDA": 5649190576309, "VRT": 97086314647}
    # Zero and None are not real market caps and must not be published.
    assert "AMD" not in result
    assert "GOOG" not in result


def test_market_caps_survives_fetch_failures(monkeypatch):
    caps = {"NVDA": 5649190576309.0, "MSFT": 3842942775502.0}
    fake = _FakeYFinance(caps, fail={"MSFT"})
    monkeypatch.setattr(quotes.yf, "Ticker", fake.Ticker)

    result = quotes._market_caps(["NVDA", "MSFT", "NONE"])

    assert result == {"NVDA": 5649190576309}


def test_market_caps_handles_no_tickers(monkeypatch):
    fake = _FakeYFinance({})
    monkeypatch.setattr(quotes.yf, "Ticker", fake.Ticker)

    assert quotes._market_caps([]) == {}
    assert fake.seen == []


def test_write_quotes_keeps_existing_cache_when_fetch_is_empty(monkeypatch, tmp_path):
    cache = tmp_path / "quotes.json"
    cached = {
        "generated_at": "2026-10-14T00:00:00+00:00",
        "source": "yfinance",
        "quotes": {"MSFT": {"price": 500.0, "market_cap": 1}},
    }
    _write_cache(cache, cached)
    monkeypatch.setattr(quotes, "QUOTES_PATH", cache)
    monkeypatch.setattr(
        quotes, "fetch_quotes", lambda: {"generated_at": "x", "quotes": {}}
    )

    with pytest.raises(RuntimeError):
        quotes.write_quotes(force=True)

    assert json.loads(cache.read_text()) == cached


def test_write_quotes_writes_empty_file_when_no_cache_exists(monkeypatch, tmp_path):
    cache = tmp_path / "quotes.json"
    monkeypatch.setattr(quotes, "QUOTES_PATH", cache)
    empty = {"generated_at": "x", "source": "yfinance", "quotes": {}}
    monkeypatch.setattr(quotes, "fetch_quotes", lambda: empty)

    result = quotes.write_quotes(force=True)

    assert result == str(cache)
    assert json.loads(cache.read_text()) == empty


def _daily_frame(index, closes_by_ticker: dict[str, list[float]]):
    """Build the MultiIndex (ticker, field) frame `yf.download` returns."""

    return pd.concat(
        {
            ticker: pd.DataFrame({"Close": series}, index=index)
            for ticker, series in closes_by_ticker.items()
        },
        axis=1,
    )


def test_fetch_quotes_derives_week_and_52_week_changes(monkeypatch, tmp_path):
    # Two calendar years minus one session, so the 52-week target (2025-10-17)
    # has no trading day of its own and the nearest prior close must stand in.
    calendar = pd.bdate_range(end="2026-10-16", periods=504)
    index = calendar[calendar != pd.Timestamp("2025-10-17")]
    # A regime change 52 weeks back makes the yearly baseline unmistakable;
    # any fixed row offset would land on the wrong day.
    closes = [200 + i if i <= 242 else 900 + (i - 243) for i in range(len(index))]
    frame = _daily_frame(index, {"NVDA": closes})
    requested: dict[str, str] = {}

    def fake_download(tickers, **kwargs):
        requested.update(kwargs)
        return frame

    monkeypatch.setattr(quotes, "_load_tickers", lambda: ["NVDA"])
    monkeypatch.setattr(quotes, "_market_caps", lambda tickers, **kw: {"NVDA": 1})
    monkeypatch.setattr(quotes.yf, "download", fake_download)

    payload = quotes.fetch_quotes()

    assert requested["period"] == "2y"
    assert payload["quotes"]["NVDA"] == {
        "price": 1159.0,
        "previous_close": 1158.0,
        "change_pct": 0.09,
        "week_change_pct": 0.43,
        "change_52w_pct": 162.22,
        "market_cap": 1,
    }


def test_fetch_quotes_omits_trailing_changes_without_enough_history(monkeypatch):
    index = pd.bdate_range(end="2026-10-16", periods=3)
    frame = _daily_frame(index, {"VRT": [10.0, 11.0, 12.0]})

    monkeypatch.setattr(quotes, "_load_tickers", lambda: ["VRT"])
    monkeypatch.setattr(quotes, "_market_caps", lambda tickers, **kw: {})
    monkeypatch.setattr(quotes.yf, "download", lambda tickers, **kw: frame)

    quote = quotes.fetch_quotes()["quotes"]["VRT"]

    assert quote["change_pct"] == 9.09
    assert quote["week_change_pct"] is None
    assert quote["change_52w_pct"] is None


def test_close_before_returns_none_when_history_is_shorter_than_the_window():
    index = pd.bdate_range(end="2026-10-16", periods=30)
    closes = pd.Series(range(30, 60), index=index, dtype=float)

    assert quotes._close_before(closes, 52) is None


def test_apply_proxy_uses_configured_proxy_and_hides_credentials(
    monkeypatch, caplog
):
    monkeypatch.setattr(YfConfig.network, "proxy", None, raising=False)
    monkeypatch.setattr(
        quotes,
        "get_settings",
        lambda: SimpleNamespace(resolved_quotes_proxy="socks5://user:secret@proxy.example:1080"),
    )

    with caplog.at_level(logging.INFO):
        assert quotes.apply_proxy() == "socks5://user:secret@proxy.example:1080"

    assert YfConfig.network.proxy == "socks5://user:secret@proxy.example:1080"
    assert "secret" not in caplog.text
    assert "socks5://proxy.example:1080" in caplog.text


def test_apply_proxy_clears_the_proxy_when_unset(monkeypatch):
    monkeypatch.setattr(YfConfig.network, "proxy", "http://stale:1", raising=False)
    monkeypatch.setattr(
        quotes,
        "get_settings",
        lambda: SimpleNamespace(resolved_quotes_proxy=None),
    )

    assert quotes.apply_proxy() is None
    assert YfConfig.network.proxy is None


def test_fetch_quotes_applies_the_proxy_before_downloading(monkeypatch):
    seen: dict[str, object] = {}
    monkeypatch.setattr(YfConfig.network, "proxy", None, raising=False)
    monkeypatch.setattr(
        quotes, "get_settings", lambda: SimpleNamespace(resolved_quotes_proxy="http://p:1")
    )
    monkeypatch.setattr(quotes, "_load_tickers", lambda: [])

    def fake_download(tickers, **kwargs):
        seen["proxy"] = YfConfig.network.proxy
        return pd.DataFrame()

    monkeypatch.setattr(quotes.yf, "download", fake_download)

    quotes.fetch_quotes()

    assert seen["proxy"] == "http://p:1"


def test_check_connection_reports_a_blocked_route(monkeypatch, capsys):
    monkeypatch.setattr(
        quotes, "get_settings", lambda: SimpleNamespace(resolved_quotes_proxy=None)
    )
    monkeypatch.setattr(quotes.yf, "download", lambda *a, **kw: pd.DataFrame())

    assert quotes.check_connection() is False
    assert "FAIL" in capsys.readouterr().out


def test_check_connection_accepts_a_working_route(monkeypatch, capsys):
    monkeypatch.setattr(
        quotes, "get_settings", lambda: SimpleNamespace(resolved_quotes_proxy=None)
    )
    index = pd.bdate_range(end="2026-10-16", periods=2)
    frame = pd.DataFrame({"Close": [10.0, 11.0]}, index=index)

    monkeypatch.setattr(quotes.yf, "download", lambda *a, **kw: frame)

    assert quotes.check_connection() is True
    assert "OK AAPL: 2 rows" in capsys.readouterr().out


def test_write_quotes_persists_successful_fetch(monkeypatch, tmp_path):
    cache = tmp_path / "quotes.json"
    monkeypatch.setattr(quotes, "QUOTES_PATH", cache)
    fresh = {
        "generated_at": "x",
        "source": "yfinance",
        "quotes": {"MSFT": {"price": 500.0, "market_cap": 1}},
    }
    monkeypatch.setattr(quotes, "fetch_quotes", lambda: fresh)

    assert quotes.write_quotes(force=True) == str(cache)
    assert json.loads(cache.read_text()) == fresh
