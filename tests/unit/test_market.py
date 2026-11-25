from sqlalchemy.orm import sessionmaker

from fdc.db import get_engine
from fdc.market import CATEGORIES, INDICES, read_market, refresh
from fdc.models import MarketQuote, create_all_for_tests

#: Every configured index must belong to a known category.
assert len(INDICES) == 25


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


def test_indices_are_categorized_and_unit_typed():
    categories = dict(CATEGORIES)
    assert [cid for cid, _ in CATEGORIES] == [
        "us", "sector", "macro", "commodity", "crypto", "global",
    ]
    for symbol, spec in INDICES.items():
        assert spec.symbol == symbol
        assert spec.category in categories, symbol
        assert spec.unit in ("index", "pct", "usd"), symbol


def test_read_market_orders_and_filters_configured_symbols(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'market-ordered.db'}")
    create_all_for_tests(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    metrics = {"close": 1.0, "change": None, "change_pct": None, "change_1w": None,
               "change_1m": None, "high_1m": 1.0, "low_1m": 1.0, "spark": [1.0]}
    with factory() as session, session.begin():
        for symbol, spec in INDICES.items():
            session.add(MarketQuote(symbol=symbol, label=spec.label, metrics=metrics))
        session.add(MarketQuote(symbol="^OLD", label="Removed index", metrics=metrics))

    view = read_market(session_factory=factory)
    assert [item["symbol"] for item in view["indices"]] == list(INDICES)
    assert view["categories"] == [{"id": cid, "label": label} for cid, label in CATEGORIES]
    first = view["indices"][0]
    assert first["symbol"] == "^GSPC"
    assert first["category"] == "us"
    assert first["unit"] == "index"


def test_refresh_stores_latest_spark_and_enriched_metrics(tmp_path, monkeypatch):
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
    assert first["change"] == 2.0
    assert first["change_pct"] == 2.0
    assert first["high_1m"] == 102.0
    assert first["low_1m"] == 100.0
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
