"""Fetch and serve short history for broad-market indices."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import yfinance as yf
from sqlalchemy import select

from fdc.db import SessionLocal
from fdc.models import MarketQuote
from fdc.quotes import apply_proxy

logger = logging.getLogger(__name__)

#: Display order matters: broad market first, then size/sector gauges, then VIX.
INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq Composite",
    "^NDX": "Nasdaq 100",
    "^DJI": "Dow Jones",
    "^RUT": "Russell 2000",
    "^SOX": "PHLX Semiconductor",
    "^VIX": "VIX",
    "^TNX": "10Y Treasury Yield",
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
    """Close plus 1D/1W/1M percentage change from the daily close series."""
    close = values[-1]
    return {
        "close": close,
        "change_pct": _pct(close, values[-2]) if len(values) > 1 else None,
        "change_1w": _pct(close, values[-6]) if len(values) > 5 else None,
        "change_1m": _pct(close, values[0]) if len(values) > 1 else None,
        "spark": values,
    }


def refresh(session_factory=SessionLocal, downloader=None) -> int:
    """Fetch 30 daily closes and replace cached index snapshots."""
    apply_proxy()
    downloader = downloader or yf.download
    rows = []
    for symbol, label in INDICES.items():
        try:
            history = downloader(symbol, period="1mo", interval="1d", progress=False, auto_adjust=True, threads=False)
            close = history["Close"]
            if hasattr(close, "columns"):
                close = close[symbol] if symbol in close.columns else close.iloc[:, 0]
            closes = close.dropna().tail(30).tolist()
            values = [_numeric(value) for value in closes]
            values = [value for value in values if value is not None]
            if values:
                rows.append((symbol, label, _metrics(values)))
        except Exception:
            logger.warning("Market index fetch failed: %s", symbol, exc_info=True)
    with session_factory() as session, session.begin():
        for symbol, label, metrics in rows:
            row = session.get(MarketQuote, symbol)
            if row is None:
                session.add(MarketQuote(symbol=symbol, label=label, metrics=metrics))
            else:
                row.label = label
                row.metrics = metrics
    return len(rows)


def read_market(session_factory=SessionLocal) -> dict[str, Any]:
    with session_factory() as session:
        rows = session.scalars(select(MarketQuote)).all()
    order = {symbol: position for position, symbol in enumerate(INDICES)}
    rows = sorted(rows, key=lambda row: order.get(row.symbol, len(order)))
    return {"as_of": datetime.now(UTC).date().isoformat(), "indices": [
        {"symbol": row.symbol, "label": row.label, **row.metrics} for row in rows
    ]}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"Updated {refresh()} indices")
