"""Daily quote generator: market cap enrichment and cache safety."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pandas as pd
import pytest
from yfinance.config import YfConfig

from fdc import catalog, quotes


def test_partial_refresh_preserves_dropped_ticker_prices(engine, monkeypatch):
    from fdc.quote_store import load_payload, save_payload

    save_payload({"generated_at": "old", "valuation_refreshed_at": "valuation", "quotes": {
        "AAPL": {"price": 1, "pe": 10}, "MSFT": {"price": 2, "pe": 20},
    }})
    monkeypatch.setattr(quotes, "fetch_quotes", lambda: {
        "generated_at": "new", "quotes": {"AAPL": {"price": 3, "pe": None,
                                                    "eps_ttm": None,
                                                    "forward_pe": None,
                                                    "forward_eps": None}},
    })

    quotes.write_quotes(force=True)

    result = load_payload()
    # Dropped tickers keep their cached price but valuation fields are live
    # values only — a stale P/E must never resurface as current data.
    assert result["quotes"] == {
        "AAPL": {"price": 3, "pe": None, "eps_ttm": None,
                 "forward_pe": None, "forward_eps": None},
        "MSFT": {"price": 2, "pe": None, "eps_ttm": None,
                 "forward_pe": None, "forward_eps": None},
    }


def test_database_quote_storage_import_and_replace(engine, tmp_path):
    from fdc.quote_store import import_json, load_payload, save_payload

    path = tmp_path / "quotes.json"
    path.write_text(json.dumps({
        "generated_at": "2026-01-01T00:00:00+00:00",
        "source": "yfinance",
        "quotes": {"abc": {"price": 12, "pe": 5}},
    }))
    import_json(path)
    assert load_payload()["quotes"] == {"ABC": {"price": 12, "pe": 5}}
    save_payload({"generated_at": "new", "quotes": {"ABC": {"price": 13}}})
    assert load_payload()["quotes"] == {"ABC": {"price": 13}}


@pytest.fixture(autouse=True)
def quote_database(engine):
    return engine


def _write_cache(path, payload: dict) -> None:
    quotes.quote_store.save_payload(payload)


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
    monkeypatch.setattr(
        quotes, "fetch_quotes", lambda: {"generated_at": "x", "quotes": {}}
    )

    with pytest.raises(RuntimeError):
        quotes.write_quotes(force=True)

    assert quotes.quote_store.load_payload() == cached


def test_write_quotes_writes_empty_file_when_no_cache_exists(monkeypatch, tmp_path):
    empty = {"generated_at": "x", "source": "yfinance", "quotes": {}}
    monkeypatch.setattr(quotes, "fetch_quotes", lambda: empty)

    result = quotes.write_quotes(force=True)

    assert result == "0 quotes (database)"
    assert quotes.quote_store.load_payload() == empty


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
    # A regime change 52 weeks back makes the yearly high unmistakable;
    # any fixed row offset would land on the wrong day.
    closes = [200 + i if i <= 242 else 900 + (i - 243) for i in range(len(index))]
    closes[-2:] = [1001.0, 1000.0]
    frame = _daily_frame(index, {"NVDA": closes})
    requested: dict[str, str] = {}

    def fake_download(tickers, **kwargs):
        requested.update(kwargs)
        return frame

    monkeypatch.setattr(quotes, "_load_tickers", lambda: ["NVDA"])
    monkeypatch.setattr(quotes, "_market_caps", lambda tickers, **kw: {"NVDA": 1})
    monkeypatch.setattr(
        quotes, "_valuation", lambda tickers: {"NVDA": {"pe": 27.6}}
    )
    monkeypatch.setattr(quotes.yf, "download", fake_download)

    payload = quotes.fetch_quotes()

    assert requested["period"] == "2y"
    assert payload["quotes"]["NVDA"] == {
        "price": 1000.0,
        "previous_close": 1001.0,
        "change_pct": -0.1,
        "week_change_pct": -13.57,
        "week_rise_pct": 0.0,
        "month_change_pct": -13.57,
        "month_rise_pct": 0.0,
        "change_52w_pct": -13.57,
        "rise_52w_pct": 11.11,
        "market_cap": 1,
        "pe": 27.6,
        "eps_ttm": None,
        "forward_pe": None,
        "forward_eps": None,
    }


def test_fetch_quotes_omits_trailing_changes_without_enough_history(monkeypatch):
    index = pd.bdate_range(end="2026-10-16", periods=3)
    frame = _daily_frame(index, {"VRT": [10.0, 11.0, 12.0]})

    monkeypatch.setattr(quotes, "_load_tickers", lambda: ["VRT"])
    monkeypatch.setattr(quotes, "_market_caps", lambda tickers, **kw: {})
    monkeypatch.setattr(quotes, "_valuation", lambda tickers: {})
    monkeypatch.setattr(quotes.yf, "download", lambda tickers, **kw: frame)

    quote = quotes.fetch_quotes()["quotes"]["VRT"]

    assert quote["change_pct"] == 9.09
    assert quote["week_change_pct"] is None
    assert quote["week_rise_pct"] is None
    assert quote["month_change_pct"] is None
    assert quote["month_rise_pct"] is None
    assert quote["change_52w_pct"] is None
    assert quote["rise_52w_pct"] is None


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
        lambda: SimpleNamespace(
            resolved_quotes_proxy="socks5://user:secret@proxy.example:1080",
            resolved_finviz_api_key=None,
        ),
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
        lambda: SimpleNamespace(resolved_quotes_proxy=None, resolved_finviz_api_key=None),
    )

    assert quotes.apply_proxy() is None
    assert YfConfig.network.proxy is None


def test_fetch_quotes_applies_the_proxy_before_downloading(monkeypatch):
    seen: dict[str, object] = {}
    monkeypatch.setattr(YfConfig.network, "proxy", None, raising=False)
    monkeypatch.setattr(
        quotes,
        "get_settings",
        lambda: SimpleNamespace(
            resolved_quotes_proxy="http://p:1", resolved_finviz_api_key=None
        ),
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
    fresh = {
        "generated_at": "x",
        "source": "yfinance",
        "quotes": {"MSFT": {"price": 500.0, "market_cap": 1}},
    }
    monkeypatch.setattr(quotes, "fetch_quotes", lambda: fresh)

    assert quotes.write_quotes(force=True) == "1 quotes (database)"
    assert quotes.quote_store.load_payload() == fresh


def test_write_quotes_does_not_carry_cached_valuations(monkeypatch, tmp_path):
    cache = tmp_path / "quotes.json"
    _write_cache(cache, {
        "generated_at": "2026-10-31T16:02:44+00:00",
        "quotes": {
            "AAPL": {"price": 344.63, "pe": 39.51, "eps_ttm": 8.72,
                     "forward_pe": 36.07, "forward_eps": 9.56},
            "MSFT": {"price": 521.91, "pe": 27.26, "eps_ttm": 19.15,
                     "forward_pe": 21.72, "forward_eps": 24.03},
            "TSLA": {"price": 250.0, "pe": 55.5, "eps_ttm": 4.5,
                     "forward_pe": 50.0, "forward_eps": 5.0},
        },
    })
    monkeypatch.setattr(quotes, "fetch_quotes", lambda: {
        "generated_at": "2026-11-05T23:30:08+00:00",
        "quotes": {
            "AAPL": {"price": 344.17, "pe": None, "eps_ttm": None,
                     "forward_pe": None, "forward_eps": None},
            "MSFT": {"price": 535.93, "pe": 28.0, "eps_ttm": None,
                     "forward_pe": None, "forward_eps": None},
        },
    })

    quotes.write_quotes(force=True)
    result = quotes.quote_store.load_payload()

    # P/E and EPS are live-only: a fresh fetch with no value stays None.
    assert result["quotes"]["AAPL"] == {
        "price": 344.17, "pe": None, "eps_ttm": None,
        "forward_pe": None, "forward_eps": None,
    }
    assert result["quotes"]["MSFT"] == {
        "price": 535.93, "pe": 28.0, "eps_ttm": None,
        "forward_pe": None, "forward_eps": None,
    }
    # A ticker dropped by the fetch keeps its cached price but loses its
    # cached valuations.
    assert result["quotes"]["TSLA"] == {
        "price": 250.0, "pe": None, "eps_ttm": None,
        "forward_pe": None, "forward_eps": None,
    }
    assert "valuation_cache_as_of" not in result


def test_throttle_spaces_request_starts_by_interval():
    """Every request start except the first waits at least `interval`."""

    now = {"t": 100.0}
    sleeps: list[float] = []

    def clock():
        return now["t"]

    def sleeper(delay):
        sleeps.append(now["t"])
        now["t"] += delay

    throttle = quotes._Throttle(interval=1.0, clock=clock, sleeper=sleeper)
    for _ in range(5):
        throttle.wait()

    # First start is immediate; the rest are spaced at exactly the interval.
    assert sleeps == [100.0, 101.0, 102.0, 103.0]
    gaps = [later - earlier for earlier, later in zip(sleeps, sleeps[1:])]
    assert all(gap >= 1.0 for gap in gaps)


def test_throttle_skips_the_sleep_when_interval_already_elapsed():
    now = {"t": 100.0}
    sleeps: list[float] = []

    def clock():
        return now["t"]

    def sleeper(delay):
        sleeps.append(now["t"])
        now["t"] += delay

    throttle = quotes._Throttle(interval=1.0, clock=clock, sleeper=sleeper)
    throttle.wait()
    now["t"] += 10.0  # plenty of time passed between requests
    throttle.wait()

    assert sleeps == []


def test_throttle_jitter_keeps_delays_within_the_interval_window():
    now = {"t": 0.0}
    sleeps: list[float] = []

    def clock():
        return now["t"]

    def sleeper(delay):
        sleeps.append(now["t"])
        now["t"] += delay

    throttle = quotes._Throttle(
        interval=1.0, jitter=0.5, clock=clock, sleeper=sleeper
    )
    for _ in range(30):
        throttle.wait()

    gaps = [later - earlier for earlier, later in zip(sleeps, sleeps[1:])]
    assert all(1.0 <= gap <= 1.5 for gap in gaps)
    # Jitter must vary; a fixed delay means the randomization is inert.
    assert len(set(round(gap, 4) for gap in gaps)) > 1


class _FakeFinvizResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass


class _FakeFinvizSession:
    requests: list[float] = []

    def get(self, url, headers=None, timeout=None):
        _FakeFinvizSession.requests.append(finviz_clock["t"])
        return _FakeFinvizResponse(FINVIZ_SNIPPET)

    def close(self) -> None:
        pass


FINVIZ_SNIPPET = (
    '<table class="snapshot-table2">'
    "<tr><td>P/E</td><td>27.26</td></tr>"
    "<tr><td>EPS (ttm)</td><td>19.15</td></tr>"
    "</table>"
)

finviz_clock = {"t": 0.0}


def test_finviz_metrics_paces_request_starts(monkeypatch):
    """Rate limiter holds out a full interval between every request start."""

    finviz_clock["t"] = 0.0

    def clock():
        return finviz_clock["t"]

    def sleeper(delay):
        finviz_clock["t"] += delay

    monkeypatch.setattr(quotes, "Session", _FakeFinvizSession)
    _FakeFinvizSession.requests.clear()

    metrics = quotes._finviz_metrics(
        ["AAPL", "MSFT", "NVDA"],
        workers=1,
        retries=0,
        min_interval=5.0,
        jitter=0.0,
        clock=clock,
        sleeper=sleeper,
    )

    assert metrics == {
        "AAPL": {"pe": 27.26, "eps_ttm": 19.15},
        "MSFT": {"pe": 27.26, "eps_ttm": 19.15},
        "NVDA": {"pe": 27.26, "eps_ttm": 19.15},
    }
    starts = list(_FakeFinvizSession.requests)
    assert len(starts) == 3
    assert all(later - earlier >= 5.0 for earlier, later in zip(starts, starts[1:]))


def test_read_quotes_exposes_cached_valuation_date(monkeypatch, tmp_path):
    cache = tmp_path / "quotes.json"
    _write_cache(cache, {
        "generated_at": "2026-11-05T23:30:08+00:00",
        "valuation_cache_as_of": "2026-10-31T16:02:44+00:00",
        "quotes": {"AAPL": {"price": 344.17, "pe": 39.51}},
    })

    assert catalog.read_quotes().valuation_cache_as_of == "2026-10-31T16:02:44+00:00"


FINVIZ_API_CSV = (
    "No.,Ticker,Company,Market Cap,P/E,Forward P/E,EPS (ttm),EPS next Y\r\n"
    "1,AAPL,Apple,3000B,39.51,28.10,7.46,-\r\n"
    "2,MSFT,Microsoft,3100B,34.14,-12.5%,10.01,13.11\r\n"
    "3,,,missing row,,,,\r\n"
)


def test_parse_finviz_api_metrics_maps_headers_and_drops_dashes():
    metrics = quotes._parse_finviz_api_metrics(FINVIZ_API_CSV)

    assert metrics == {
        "AAPL": {"pe": 39.51, "forward_pe": 28.1, "eps_ttm": 7.46},
        "MSFT": {"pe": 34.14, "forward_pe": -12.5, "eps_ttm": 10.01, "forward_eps": 13.11},
    }


def test_parse_finviz_api_metrics_rejects_unknown_headers():
    assert quotes._parse_finviz_api_metrics("No.,Ticker,Company\r\n1,AAPL,Apple\r\n") == {}


def test_valuation_chain_yahoo_then_api_then_html(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(
        quotes, "_yahoo_valuation", lambda tickers, **kw: {"AAPL": {"pe": 1.0}}
    )
    monkeypatch.setattr(
        quotes,
        "get_settings",
        lambda: SimpleNamespace(resolved_finviz_api_key="token"),
    )

    def fake_api(tickers, token, **kw):
        calls.append("api")
        assert token == "token"
        assert tickers == ["MSFT", "NVDA"]
        return {"MSFT": {"pe": 2.0, "eps_ttm": 9.0}}

    monkeypatch.setattr(quotes, "_finviz_api_metrics", fake_api)

    def fake_html(tickers, **kw):
        calls.append("html")
        assert tickers == ["NVDA"]
        return {"NVDA": {"pe": 3.0}}

    monkeypatch.setattr(quotes, "_finviz_metrics", fake_html)

    valuation = quotes._valuation(["AAPL", "MSFT", "NVDA"])

    assert calls == ["api", "html"]
    assert valuation == {
        "AAPL": {"pe": 1.0},
        "MSFT": {"pe": 2.0, "eps_ttm": 9.0},
        "NVDA": {"pe": 3.0},
    }


def test_valuation_chain_skips_api_without_token(monkeypatch):
    monkeypatch.setattr(quotes, "_yahoo_valuation", lambda tickers, **kw: {})
    monkeypatch.setattr(
        quotes, "get_settings", lambda: SimpleNamespace(resolved_finviz_api_key=None)
    )

    def fail_api(tickers, token, **kw):
        raise AssertionError("api should not be called without a token")

    monkeypatch.setattr(quotes, "_finviz_api_metrics", fail_api)
    monkeypatch.setattr(quotes, "_finviz_metrics", lambda tickers, **kw: {})

    assert quotes._valuation(["AAPL"]) == {}
