from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import delete, select

from fdc.db import session_scope
from fdc.models import LatestQuote, QuoteMetadata


def load_payload() -> dict:
    with session_scope() as session:
        metadata = session.get(QuoteMetadata, 1)
        rows = session.scalars(select(LatestQuote)).all()
        if metadata is None and not rows:
            return {}
        return {
            **(metadata.payload if metadata else {}),
            "quotes": {r.ticker: r.metrics for r in rows},
        }


def save_payload(payload: dict) -> None:
    quotes = payload.get("quotes", {})
    with session_scope() as session:
        session.execute(delete(LatestQuote))
        session.add_all(
            LatestQuote(ticker=ticker.upper(), metrics=metrics)
            for ticker, metrics in quotes.items()
        )
        metadata = session.get(QuoteMetadata, 1)
        values = {key: value for key, value in payload.items() if key != "quotes"}
        if metadata is None:
            session.add(QuoteMetadata(id=1, payload=values))
        else:
            metadata.payload = values


def import_json(path: Path) -> None:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or not isinstance(payload.get("quotes"), dict):
        raise ValueError("invalid quote payload")
    if load_payload():
        raise RuntimeError("database already contains quotes")
    save_payload(payload)
