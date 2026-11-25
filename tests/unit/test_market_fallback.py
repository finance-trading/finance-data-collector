"""Fallback fetchers (Binance/TwelveData) and their wiring into market refresh."""
from __future__ import annotations

import json

from sqlalchemy.orm import sessionmaker

from fdc.db import get_engine
from fdc.market import refresh
from fdc.market_sources import binance_daily_closes, fallback_closes, twelvedata_daily_closes
from fdc.models import MarketQuote, create_all_for_tests

KLINE = [
    [1700000000000, "1", "2", "3", "100.0", "5", 0, 0, 0, 0],
    [1700086400000, "100", "101", "102", "102.0", "5", 0, 0, 0, 0],
]


def test_binance_daily_closes_parses_kline_closes():
    closes = binance_daily_closes("BTC-USD", fetch=lambda url: json.dumps(KLINE).encode())
    assert closes == [100.0, 102.0]


def test_binance_uses_default_usdt_alias():
    urls: list[str] = []

    def fetch(url):
        urls.append(url)
        return json.dumps(KLINE).encode()

    assert binance_daily_closes("BTC-USD", fetch=fetch) == [100.0, 102.0]
    assert "symbol=BTCUSDT" in urls[0]


def test_binance_returns_none_on_bad_payload():
    assert binance_daily_closes("BTC-USD", fetch=lambda url: b"oops") is None


def test_twelvedata_returns_none_without_key():
    assert twelvedata_daily_closes("^GSPC", fetch=lambda url: b"{}") is None


def test_twelvedata_parses_closes_with_key():
    payload = {"values": [{"close": "1"}, {"close": "2"}, {"close": "3"}]}
    closes = twelvedata_daily_closes("^GSPC", fetch=lambda url: json.dumps(payload).encode(),
                                     api_key="k")
    assert closes == [1.0, 2.0, 3.0]


def test_fallback_routes_crypto_to_binance_and_rest_to_twelvedata():
    # Crypto resolves via Binance (no key); a macro symbol needs the (absent) key.
    assert fallback_closes("BTC-USD", "crypto",
                           fetch=lambda url: json.dumps(KLINE).encode()) == [100.0, 102.0]
    assert fallback_closes("^GSPC", "us", fetch=lambda url: b"{}") is None


def test_fallback_queries_twelvedata_for_plain_tickers(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr("fdc.market_sources.get_settings",
                        lambda: SimpleNamespace(twelvedata_api_key="k"))
    urls: list[str] = []
    payload = {"values": [{"close": "190.0"}]}

    def fetch(url):
        urls.append(url)
        return json.dumps(payload).encode()

    assert fallback_closes("XLK", "sector", fetch=fetch) == [190.0]
    assert "symbol=XLK" in urls[0]


def test_fallback_routes_explicit_aliases(monkeypatch):
    """An alias, when configured, replaces the Yahoo symbol in the request."""
    from types import SimpleNamespace

    monkeypatch.setattr("fdc.market_sources.get_settings",
                        lambda: SimpleNamespace(twelvedata_api_key="k"))
    monkeypatch.setattr("fdc.market_sources._load_sources",
                        lambda: {"twelvedata_symbols": {"^GSPC": "SPY"}})
    urls: list[str] = []

    def fetch(url):
        urls.append(url)
        return json.dumps({"values": [{"close": "600.0"}]}).encode()

    assert fallback_closes("^GSPC", "us", fetch=fetch) == [600.0]
    assert "symbol=SPY" in urls[0]


def test_committed_alias_config_stays_parseable():
    from fdc.data_files import PROJECT_ROOT

    raw = json.loads((PROJECT_ROOT / "config" / "market_sources.json").read_text())
    assert isinstance(raw.get("twelvedata_symbols", {}), dict)


def test_fallback_skips_unaliased_special_symbols():
    """Unlisted Yahoo symbols must not reach TwelveData: short letter aliases
    it resolves to unrelated equities (WTI, DX are stock tickers), which would
    overwrite the card with wrong data."""
    calls: list[str] = []

    def fetch(url):
        calls.append(url)
        return json.dumps({"values": [{"close": "1"}]}).encode()

    assert fallback_closes("GC=F", "commodity", fetch=fetch) is None
    assert fallback_closes("^GSPC", "us", fetch=fetch) is None
    assert fallback_closes("^TNX", "macro", fetch=fetch) is None
    assert calls == []


def test_refresh_falls_back_for_crypto_when_yfinance_fails(tmp_path, monkeypatch):
    engine = get_engine(f"sqlite:///{tmp_path / 'fb.db'}")
    create_all_for_tests(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("fdc.market.apply_proxy", lambda: None)

    def downloader(symbol, **kwargs):
        raise RuntimeError("yahoo 429")

    monkeypatch.setattr(
        "fdc.market.fallback_closes",
        lambda symbol, category, days=30: [10.0, 11.0, 12.0] if category == "crypto" else None,
    )
    # Only crypto indices recover via the fallback; non-crypto stay skipped.
    from fdc import market
    n = refresh(session_factory=factory, downloader=downloader)
    assert n == sum(1 for s in market.INDICES.values() if s.category == "crypto")
    with factory() as session:
        stored = {row.symbol for row in session.scalars(
            __import__("sqlalchemy").select(MarketQuote)).all()}
    assert stored == {s.symbol for s in market.INDICES.values() if s.category == "crypto"}
