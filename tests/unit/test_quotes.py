"""Daily quote generator: market cap enrichment."""

from __future__ import annotations

from fdc import quotes


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
