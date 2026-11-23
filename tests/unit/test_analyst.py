from datetime import UTC, datetime, timedelta

import pandas as pd

from fdc.analyst import classify_rating, compute_summary, list_latest, parse_rows, upsert

NOW = datetime(2026, 11, 22, tzinfo=UTC)


def _opinion(ticker, firm, days_ago, target=None, grade="Buy", action="main"):
    del ticker  # rows are keyed under the ticker by upsert; they carry no ticker key
    return {
        "firm": firm,
        "action_at": NOW - timedelta(days=days_ago),
        "action": action,
        "from_grade": None,
        "to_grade": grade,
        "price_target_action": "Raises" if target else None,
        "price_target": target,
        "prior_price_target": None,
    }


def test_parse_rows_preserves_multiple_same_day_actions():
    history = pd.DataFrame(
        [
            {
                "Firm": "Example Bank", "ToGrade": "Buy", "FromGrade": "Hold",
                "Action": "up", "priceTargetAction": "Raises",
                "currentPriceTarget": 120, "priorPriceTarget": 100,
            },
            {
                "Firm": "Example Bank", "ToGrade": "Buy", "FromGrade": "Buy",
                "Action": "main", "priceTargetAction": "Maintains",
                "currentPriceTarget": 125, "priorPriceTarget": 120,
            },
        ],
        index=pd.to_datetime(["2026-11-20 09:00:00Z", "2026-11-20 15:00:00Z"]),
    )

    rows = parse_rows(history, now=NOW)

    assert len(rows) == 2
    assert [row["action_at"] for row in rows] == list(history.index.to_pydatetime())


def _entry(firm, when, target, grade):
    return {"firm": firm, "action_at": when, "price_target": target, "to_grade": grade}


def test_summary_uses_latest_target_and_latest_grade_per_firm():
    entries = [
        _entry("A", datetime(2026, 10, 1, tzinfo=UTC), 100, "Buy"),
        _entry("A", datetime(2026, 11, 1, tzinfo=UTC), 120, "Hold"),
        _entry("B", datetime(2026, 9, 1, tzinfo=UTC), 80, "Underperform"),
        _entry("C", datetime(2025, 10, 1, tzinfo=UTC), 999, "Buy"),
    ]

    assert compute_summary(entries, now=NOW) == {
        "analyst_target": 100.0,
        "analyst_count": 2,
        "analyst_rating": "hold",
    }


def test_upsert_is_idempotent_and_keeps_one_row_per_event(session):
    opinions = {
        "AAPL": [
            _opinion("AAPL", "Bernstein", 10, target=380, grade="Buy"),
            _opinion("AAPL", "JP Morgan", 30, target=355, grade="Overweight"),
        ]
    }
    upsert(session, opinions, now=NOW)
    upsert(session, opinions, now=NOW)  # re-collect the same events

    from sqlalchemy import func, select

    from fdc.models import AnalystOpinion

    count = session.scalars(
        select(func.count()).select_from(AnalystOpinion).where(AnalystOpinion.ticker == "AAPL")
    ).one()
    assert count == 2


def test_list_latest_returns_one_row_per_firm(session):
    upsert(
        session,
        {"AAPL": [
            _opinion("AAPL", "Bernstein", 40, target=370, grade="Buy"),
            _opinion("AAPL", "Bernstein", 5, target=380, grade="Buy"),
            _opinion("AAPL", "JP Morgan", 30, target=355, grade="Overweight"),
        ]},
        now=NOW,
    )
    session.commit()  # list_latest reads through its own session

    latest = list_latest("AAPL", now=NOW)
    assert {row.firm for row in latest} == {"Bernstein", "JP Morgan"}
    bernstein = next(row for row in latest if row.firm == "Bernstein")
    assert bernstein.price_target == 380.0
    # newest first
    assert [row.firm for row in latest] == ["Bernstein", "JP Morgan"]


def test_classify_rating_maps_freeform_grades():
    assert classify_rating("Strong Buy") == "buy"
    assert classify_rating("Overweight") == "buy"
    assert classify_rating("Outperform") == "buy"
    assert classify_rating("Buy") == "buy"
    assert classify_rating("Neutral") == "hold"
    assert classify_rating("In-Line") == "hold"
    assert classify_rating("Equal-Weight") == "hold"
    assert classify_rating("Underweight") == "sell"
    assert classify_rating("Sell") == "sell"
    assert classify_rating(None) is None
    assert classify_rating("Unknown") is None
