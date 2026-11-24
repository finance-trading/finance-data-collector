"""Schema tests for the migrated business master data and quality inputs.

Covers the new tables added by migration 0014: the AI company catalog
(``ai_layer`` / ``ai_segment`` / ``ai_company``), manual funnel tier
overrides (``funnel_override``), and the quality-scoring input batches
(``quality_input_batch`` / ``quality_annual_fact`` / ``quality_peer``).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from fdc.models import (
    AiCompany,
    AiLayer,
    AiSegment,
    FunnelOverride,
    QualityAnnualFact,
    QualityInputBatch,
    QualityPeer,
    create_all_for_tests,
)

TABLES = (
    "ai_layer",
    "ai_segment",
    "ai_company",
    "funnel_override",
    "quality_input_batch",
    "quality_annual_fact",
    "quality_peer",
)


@pytest.fixture
def session(engine):
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        yield session


def test_all_migrated_tables_exist(session):
    names = set(inspect(session.get_bind()).get_table_names())
    assert set(TABLES) <= names


def test_catalog_insert_and_composite_segment_fk(session):
    layer = AiLayer(id="infra", name="算力基础设施与云", name_en="Compute Infrastructure & Cloud",
                    summary="...", position=2)
    segment = AiSegment(layer_id="infra", name="云与超大规模", position=0)
    session.add_all([layer, segment])
    session.flush()
    company = AiCompany(
        ticker="SPCX", name="Space Exploration Technologies", sector="Technology",
        industry="System Software", layer_id="infra", segment="云与超大规模",
        also_in=[], description="云厂商，组合中归入云与超大规模观察组。", position=235,
    )
    session.add(company)
    session.flush()
    bad = AiCompany(
        ticker="ANT", name="Anthropic", sector="Technology", industry="Application Svc",
        layer_id="infra", segment="不存在的细分", also_in=[], description="", position=236,
    )
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.flush()


def test_funnel_override_tier_check(session):
    session.add(FunnelOverride(ticker="SPCX", tier=1, note="T1 核心：云厂商。"))
    session.flush()
    session.add(FunnelOverride(ticker="BAD", tier=9, note=""))
    with pytest.raises(IntegrityError):
        session.flush()


def test_quality_fact_round_trip(session):
    batch = QualityInputBatch(
        id="annual_facts:edgartools_annual_facts_2026-10-05.csv.gz",
        kind="annual_facts", source="edgartools_annual_facts_2026-10-05.csv.gz",
        sha256="0" * 64,
    )
    session.add(batch)
    session.flush()
    fact = QualityAnnualFact(
        batch_id=batch.id, cik="0000001800", concept="us-gaap:Revenues",
        metric="revenue", numeric_value=Decimal("-243000000.0"),
        period_type="duration", period_days=364,
    )
    session.add(fact)
    session.flush()
    row = session.get(QualityAnnualFact, fact.id)
    assert row.numeric_value == Decimal("-243000000.0")
    assert row.period_days == 364
