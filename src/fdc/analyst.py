"""Per-firm analyst target-price history from Yahoo Finance."""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from fdc.db import session_scope
from fdc.models import AnalystOpinion

RETENTION = timedelta(days=730)
SUMMARY_WINDOW = timedelta(days=365)
SOURCE = "yahoo_upgrade_downgrade"


def _text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _timestamp(value: Any) -> datetime | None:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC").to_pydatetime()


def parse_rows(history: Any, *, now: datetime) -> list[dict[str, Any]]:
    cutoff = now - RETENTION
    rows = {}
    for stamp, row in history.iterrows():
        action_at = _timestamp(stamp)
        firm = _text(row.get("Firm"))
        grade = _text(row.get("ToGrade"))
        target = _number(row.get("currentPriceTarget"))
        if not action_at or action_at < cutoff or not firm or (grade is None and target is None):
            continue
        rows[(firm, action_at)] = {
            "firm": firm, "action_at": action_at,
            "action": _text(row.get("Action")),
            "from_grade": _text(row.get("FromGrade")), "to_grade": grade,
            "price_target_action": _text(row.get("priceTargetAction")),
            "price_target": target,
            "prior_price_target": _number(row.get("priorPriceTarget")),
        }
    return list(rows.values())


def classify_rating(grade: str | None) -> str | None:
    if not grade:
        return None
    text = grade.lower()
    sell = ("sell", "underweight", "underperform", "under-perform", "avoid", "negative")
    buy = ("buy", "overweight", "outperform", "out-perform", "accumulate", "positive")
    hold = ("hold", "neutral", "in-line", "inline", "equal-weight",
            "market-weight", "sector-weight", "peer", "conform")
    if any(word in text for word in sell):
        return "sell"
    if any(word in text for word in buy):
        return "buy"
    if any(word in text for word in hold):
        return "hold"
    return None


def compute_summary(entries: Iterable[Any], *, now: datetime) -> dict[str, Any]:
    cutoff = now - SUMMARY_WINDOW
    latest_target: dict[str, tuple[datetime, float]] = {}
    latest_grade: dict[str, tuple[datetime, str]] = {}
    for row in entries:
        firm = row["firm"] if isinstance(row, dict) else row.firm
        action_at = row["action_at"] if isinstance(row, dict) else row.action_at
        grade = row.get("to_grade") if isinstance(row, dict) else row.to_grade
        target = row.get("price_target") if isinstance(row, dict) else row.price_target
        if not firm or not action_at or action_at < cutoff:
            continue
        if target is not None and (firm not in latest_target or action_at > latest_target[firm][0]):
            latest_target[firm] = (action_at, float(target))
        if grade and (firm not in latest_grade or action_at > latest_grade[firm][0]):
            latest_grade[firm] = (action_at, grade)
    votes = Counter(
        classify_rating(grade) for _, grade in latest_grade.values()
        if classify_rating(grade)
    )
    rating = max(
        ("hold", "buy", "sell"),
        key=lambda item: (votes[item], item == "hold"),
    ) if votes else None
    targets = [target for _, target in latest_target.values()]
    return {
        "analyst_target": round(sum(targets) / len(targets), 2) if targets else None,
        "analyst_count": len(targets),
        "analyst_rating": rating,
    }


def upsert(session: Session, opinions: dict[str, list[dict]], *, now: datetime) -> None:
    for ticker, rows in opinions.items():
        existing = session.scalars(
            select(AnalystOpinion).where(AnalystOpinion.ticker == ticker)
        ).all()
        current = {(row.firm, row.action_at): row for row in existing}
        for data in rows:
            obj = current.get((data["firm"], data["action_at"]))
            if obj is None:
                session.add(AnalystOpinion(ticker=ticker, source=SOURCE, fetched_at=now, **data))
            else:
                for key, value in data.items():
                    setattr(obj, key, value)
                obj.fetched_at = now
    session.execute(delete(AnalystOpinion).where(AnalystOpinion.action_at < now - RETENTION))


def refresh(
    tickers: Iterable[str],
    *,
    workers: int = 8,
    now: datetime | None = None,
) -> dict[str, dict]:
    """Collect firm-level opinions, persist them, and return per-ticker summaries."""

    from concurrent.futures import ThreadPoolExecutor

    import yfinance as yf

    now = now or datetime.now(timezone.utc)
    ticker_list = sorted({ticker.upper() for ticker in tickers})
    if not ticker_list:
        return {}
    from fdc.quotes import apply_proxy

    apply_proxy()

    def fetch(ticker: str) -> tuple[str, list[dict]]:
        try:
            history = yf.Ticker(ticker).upgrades_downgrades
            if history is None or history.empty:
                return ticker, []
            return ticker, parse_rows(history, now=now)
        except Exception:
            return ticker, []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        opinions = {ticker: rows for ticker, rows in pool.map(fetch, ticker_list) if rows}
    with session_scope() as session:
        upsert(session, opinions, now=now)
        rows = session.scalars(select(AnalystOpinion).where(
            AnalystOpinion.ticker.in_(ticker_list), AnalystOpinion.action_at >= now - SUMMARY_WINDOW
        )).all()
        by_ticker: dict[str, list[AnalystOpinion]] = {}
        for row in rows:
            by_ticker.setdefault(row.ticker, []).append(row)
        return {ticker: compute_summary(items, now=now) for ticker, items in by_ticker.items()}


def summary_for_ticker(ticker: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Consensus from every action in the 12-month window, not only latest rows."""

    now = now or datetime.now(timezone.utc)
    with session_scope() as session:
        rows = session.scalars(
            select(AnalystOpinion).where(
                AnalystOpinion.ticker == ticker.upper(),
                AnalystOpinion.action_at >= now - SUMMARY_WINDOW,
            )
        ).all()
    return compute_summary(rows, now=now)


def list_latest(ticker: str, *, now: datetime | None = None) -> list[AnalystOpinion]:
    """Latest opinion per firm within the retention window, newest first."""

    now = now or datetime.now(timezone.utc)
    cutoff = now - RETENTION
    with session_scope() as session:
        rows = session.scalars(select(AnalystOpinion).where(
            AnalystOpinion.ticker == ticker.upper(), AnalystOpinion.action_at >= cutoff
        )).all()
        latest = {}
        for row in rows:
            if row.firm not in latest or row.action_at > latest[row.firm].action_at:
                latest[row.firm] = row
        return sorted(latest.values(), key=lambda item: item.action_at, reverse=True)
