from sqlalchemy.orm import sessionmaker

from fdc.db import get_engine
from fdc.market import INDICES, read_market, refresh
from fdc.models import MarketQuote, create_all_for_tests


class Frame:
    def __init__(self, values):
        self.values = values

    def dropna(self):
        return self

    def tail(self, count):
        return Frame(self.values[-count:])

    def tolist(self):
        return self.values


class History:
    def __init__(self, values):
        self.columns = {"Close": Frame(values)}

    def __getitem__(self, key):
        return self.columns[key]


def test_refresh_stores_latest_and_spark_history(tmp_path, monkeypatch):
    engine = get_engine(f"sqlite:///{tmp_path / 'market.db'}")
    create_all_for_tests(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("fdc.market.apply_proxy", lambda: None)

    def download(symbol, **kwargs):
        return History([100.0, 102.0])

    assert refresh(session_factory=factory, downloader=download) == len(INDICES)
    view = read_market(session_factory=factory)
    assert len(view["indices"]) == len(INDICES)
    first = view["indices"][0]
    assert first["symbol"] == "^GSPC"
    assert first["close"] == 102.0
    assert first["change_pct"] == 2.0
    assert first["change_1m"] == 2.0
    assert first["change_1w"] is None  # fewer than 6 sessions available
    assert first["spark"] == [100.0, 102.0]


def test_market_refresh_keeps_usable_partial_results(tmp_path, monkeypatch):
    engine = get_engine(f"sqlite:///{tmp_path / 'market-partial.db'}")
    create_all_for_tests(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("fdc.market.apply_proxy", lambda: None)

    def download(symbol, **kwargs):
        if symbol == "^VIX":
            raise RuntimeError("unavailable")
        return History([100.0, 99.0])

    assert refresh(session_factory=factory, downloader=download) == len(INDICES) - 1
    with factory() as session:
        assert session.query(MarketQuote).count() == len(INDICES) - 1
