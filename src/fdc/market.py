"""Fetch and serve short history for broad-market indices."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import yfinance as yf
from sqlalchemy import select

from fdc.db import SessionLocal
from fdc.models import MarketQuote
from fdc.quotes import apply_proxy

logger = logging.getLogger(__name__)
INDICES = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq Composite", "^VIX": "VIX"}


def _numeric(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None


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
                prev = values[-2] if len(values) > 1 else values[-1]
                change = round(((values[-1] / prev) - 1) * 100, 4) if prev else None
                rows.append((symbol, label, {"close": values[-1], "change_pct": change, "spark": values}))
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
        rows = session.scalars(select(MarketQuote).order_by(MarketQuote.symbol)).all()
    return {"as_of": datetime.now(UTC).date().isoformat(), "indices": [
        {"symbol": row.symbol, "label": row.label, **row.metrics} for row in rows
    ]}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"Updated {refresh()} indices")
