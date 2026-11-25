"""Fetch and serve short history for broad-market and global indices."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yfinance as yf
from sqlalchemy import select

from fdc.db import SessionLocal
from fdc.models import MarketQuote
from fdc.quotes import apply_proxy
from fdc.market_sources import fallback_closes

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexSpec:
    symbol: str
    label: str
    category: str
    unit: str = "index"  # index points | percent yield | USD


def _spec(symbol: str, label: str, category: str, unit: str = "index") -> IndexSpec:
    return IndexSpec(symbol, label, category, unit)


#: Categories in display order.
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("us", "US Broad Market"),
    ("sector", "Sectors & Themes"),
    ("macro", "Rates, Volatility & Dollar"),
    ("commodity", "Commodities"),
    ("crypto", "Crypto"),
    ("global", "Global Markets"),
)

#: Tracked indices, in display order.
INDICES: dict[str, IndexSpec] = {
    spec.symbol: spec
    for spec in (
        _spec("^GSPC", "S&P 500", "us"),
        _spec("^IXIC", "Nasdaq Composite", "us"),
        _spec("^NDX", "Nasdaq 100", "us"),
        _spec("^DJI", "Dow Jones", "us"),
        _spec("^RUT", "Russell 2000", "us"),
        _spec("^SOX", "PHLX Semiconductor", "sector"),
        _spec("XLK", "Technology Select", "sector", "usd"),
        _spec("XLF", "Financial Select", "sector", "usd"),
        _spec("XLE", "Energy Select", "sector", "usd"),
        _spec("^VIX", "VIX", "macro"),
        _spec("^TNX", "10Y Treasury Yield", "macro", "pct"),
        _spec("^TYX", "30Y Treasury Yield", "macro", "pct"),
        _spec("DX-Y.NYB", "Dollar Index", "macro"),
        _spec("GC=F", "Gold", "commodity", "usd"),
        _spec("CL=F", "WTI Crude Oil", "commodity", "usd"),
        _spec("HG=F", "Copper", "commodity", "usd"),
        _spec("BTC-USD", "Bitcoin", "crypto", "usd"),
        _spec("ETH-USD", "Ethereum", "crypto", "usd"),
        _spec("^N225", "Nikkei 225", "global"),
        _spec("^HSI", "Hang Seng", "global"),
        _spec("^GDAXI", "DAX", "global"),
        _spec("^FTSE", "FTSE 100", "global"),
        _spec("000001.SS", "Shanghai Composite", "global"),
        _spec("^HSTECH", "Hang Seng Tech", "global"),
        _spec("KWEB", "China Internet", "global", "usd"),
    )
}


def _numeric(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _pct(last: float, prev: float | None) -> float | None:
    return round(((last / prev) - 1) * 100, 4) if prev else None


def _metrics(values: list[float]) -> dict[str, Any]:
    """Close, 1D/1W/1M change, and 1M range from the daily close series."""
    close = values[-1]
    return {
        "close": close,
        "change": round(close - values[-2], 4) if len(values) > 1 else None,
        "change_pct": _pct(close, values[-2]) if len(values) > 1 else None,
        "change_1w": _pct(close, values[-6]) if len(values) > 5 else None,
        "change_1m": _pct(close, values[0]) if len(values) > 1 else None,
        "high_1m": max(values),
        "low_1m": min(values),
        "spark": values,
    }


def refresh(session_factory=SessionLocal, downloader=None) -> int:
    """Fetch 30 daily closes and replace cached index snapshots."""
    apply_proxy()
    downloader = downloader or yf.download
    rows = []
    for symbol, spec in INDICES.items():
        values: list[float] | None = None
        try:
            history = downloader(
                symbol, period="1mo", interval="1d", progress=False,
                auto_adjust=True, threads=False,
            )
            close = history["Close"]
            if hasattr(close, "columns"):
                close = close[symbol] if symbol in close.columns else close.iloc[:, 0]
            values = [v for v in (_numeric(c) for c in close.dropna().tail(30).tolist()) if v is not None]
        except Exception:
            logger.warning("Market index fetch failed: %s", symbol, exc_info=True)
        # Yahoo 429s return an empty frame rather than raising, so fall back
        # whenever the primary produced nothing — not only on exception.
        if not values:
            values = fallback_closes(symbol, spec.category)
        if values:
            rows.append((symbol, spec, _metrics(values)))
    with session_factory() as session, session.begin():
        for symbol, spec, metrics in rows:
            row = session.get(MarketQuote, symbol)
            if row is None:
                session.add(MarketQuote(symbol=symbol, label=spec.label, metrics=metrics))
            else:
                row.label = spec.label
                row.metrics = metrics
    return len(rows)


def read_market(session_factory=SessionLocal) -> dict[str, Any]:
    with session_factory() as session:
        rows = session.scalars(select(MarketQuote)).all()
    stored = {row.symbol: row for row in rows}
    indices = [
        {
            "symbol": symbol,
            "label": spec.label,
            "category": spec.category,
            "unit": spec.unit,
            **stored[symbol].metrics,
        }
        for symbol, spec in INDICES.items()
        if symbol in stored
    ]
    return {
        "as_of": datetime.now(UTC).date().isoformat(),
        "categories": [{"id": cid, "label": label} for cid, label in CATEGORIES],
        "indices": indices,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"Updated {refresh()} indices")
