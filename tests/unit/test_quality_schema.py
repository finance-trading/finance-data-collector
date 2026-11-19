from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from fdc.models import CompanyQualityScore


def make_score(snapshot_id, **kwargs):
    values = dict(
        snapshot_id=snapshot_id, ticker="APD", cik="0000002969", company_name="Air Products",
        sector="Materials", rating_cutoff=date(2026, 9, 30), calculated_at=datetime.now(UTC),
        rule_version="CQ_V2", semantic_policy="CQ_EDGARTOOLS_SEMANTIC_POLICY_V2",
        quality_score=Decimal("53.977273"), score_available=False, status="NOT_QUALIFIED",
        dimension_count=4, peer_count=20, period_ends=["2025-09-30"],
        unknown_reasons=["missing_financial_strength"], v2_unknown_reasons=[],
        source_facts_sha256="a" * 64,
    )
    values.update(kwargs)
    return CompanyQualityScore(**values)


def test_quality_snapshot_roundtrip_and_history(session, engine):
    session.add_all([make_score("run-1"), make_score("run-2", quality_score=None)])
    session.commit()
    rows = session.scalars(select(CompanyQualityScore).order_by(CompanyQualityScore.snapshot_id)).all()
    assert [r.snapshot_id for r in rows] == ["run-1", "run-2"]
    assert rows[0].quality_score == Decimal("53.977273")
    assert rows[0].score_available is False
    assert rows[0].unknown_reasons == ["missing_financial_strength"]
    assert rows[0].period_ends == ["2025-09-30"]
    assert rows[1].quality_score is None
    names = {x["name"] for x in inspect(engine).get_indexes("company_quality_score")}
    assert {"ix_company_quality_score_ticker_calculated_at", "ix_company_quality_score_snapshot_id"} <= names


def test_quality_snapshot_rejects_duplicate_ticker_within_run(session):
    session.add_all([make_score("run-1"), make_score("run-1")])
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
