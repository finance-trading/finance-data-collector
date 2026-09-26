"""Unit tests for the versioned filing parser schema.

The schema is the contract between the parser write path and every reader: a
value without filing, parse identity, parser version and evidence is not a
valid row, and re-parsing must never destroy a previous result.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from fdc.models import (
    Artifact,
    Base,
    EvidenceLocator,
    ExtractedTable,
    Filing,
    FilingParse,
    FilingSection,
    Issuer,
    ParseRun,
    StatementLine,
    XbrlFact,
    create_all_for_tests,
)

ACCESSION = "0000320193-24-000001"
PARSER_VERSION = "filing-parser-v1"


def add_issuer(session, cik="0000320193", name="Apple Inc."):
    issuer = Issuer(cik=cik, name=name, ticker_hint="AAPL")
    session.add(issuer)
    session.flush()
    return issuer


def add_filing(session, issuer, accession=ACCESSION, form="10-K"):
    filing = Filing(
        issuer_id=issuer.id,
        accession_number=accession,
        form=form,
        filing_date=date(2024, 11, 1),
        report_date=date(2024, 9, 28),
        fiscal_year=2024,
        fiscal_period="FY",
        primary_document="aapl-20240928.htm",
        package_path=f"10-K/{accession}",
        index_metadata={"source": "filings_index.json"},
    )
    session.add(filing)
    session.flush()
    return filing


def add_evidence(session, filing, locator_type="heading", locator_value="Item 8"):
    evidence = EvidenceLocator(
        filing_id=filing.id,
        relative_path=filing.primary_document,
        locator_type=locator_type,
        locator_value=locator_value,
        content_sha256="a" * 64,
        excerpt="Revenue 391,035",
    )
    session.add(evidence)
    session.flush()
    return evidence


def add_parse(
    session,
    filing,
    parser_version=PARSER_VERSION,
    is_current=True,
    status="success",
    artifact_set_hash="b" * 64,
    modules_hash="c" * 64,
):
    run = ParseRun(
        scope_type="filing",
        scope_value=filing.accession_number,
        parser_version=parser_version,
        status="completed",
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    parse = FilingParse(
        filing_id=filing.id,
        parse_run_id=run.id,
        artifact_set_hash=artifact_set_hash,
        parser_version=parser_version,
        parser_modules_hash=modules_hash,
        parser_modules={"edgartools": "5.58.0", "html_parser": parser_version},
        status=status,
        is_current=is_current,
    )
    session.add(parse)
    session.flush()
    return parse


def test_all_parser_tables_are_created(engine):
    create_all_for_tests(engine)

    assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables)


def test_issuer_cik_is_unique(session):
    session.add(Issuer(cik="0000320193", name="Apple Inc."))
    session.commit()
    session.add(Issuer(cik="0000320193", name="Apple Computer"))

    with pytest.raises(IntegrityError):
        session.commit()


def test_filing_accession_is_unique(session):
    issuer = add_issuer(session)
    add_filing(session, issuer)
    session.commit()

    session.add(Filing(issuer_id=issuer.id, accession_number=ACCESSION, form="10-K"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_artifact_identity_is_unique_per_filing(session):
    filing = add_filing(session, add_issuer(session))
    session.add(
        Artifact(
            filing_id=filing.id,
            relative_path="aapl-20240928.htm",
            storage_uri="sec/AAPL/10-K/0000320193-24-000001/aapl-20240928.htm",
            role="primary",
            byte_size=1024,
            sha256="d" * 64,
            classification_status="parsed",
        )
    )
    session.commit()

    session.add(
        Artifact(
            filing_id=filing.id,
            relative_path="aapl-20240928.htm",
            role="primary",
            sha256="d" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_parse_identity_is_unique(session):
    filing = add_filing(session, add_issuer(session))
    add_parse(session, filing)
    session.commit()

    with pytest.raises(IntegrityError):
        add_parse(session, filing, is_current=False)
        session.commit()


def test_only_one_current_parse_per_filing_and_parser_version(session):
    filing = add_filing(session, add_issuer(session))
    add_parse(session, filing)
    session.commit()

    with pytest.raises(IntegrityError):
        add_parse(session, filing, artifact_set_hash="f" * 64)

    session.rollback()
    add_parse(session, filing, artifact_set_hash="f" * 64, is_current=False)
    session.commit()
    add_parse(session, filing, parser_version="filing-parser-v2")
    session.commit()

    assert session.scalar(text("SELECT count(*) FROM filing_parse WHERE is_current")) == 2


def test_current_parse_must_be_successful(session):
    filing = add_filing(session, add_issuer(session))
    with pytest.raises(IntegrityError):
        add_parse(session, filing, status="partial", is_current=True)
        session.commit()


def test_previous_parser_version_result_is_preserved(session):
    filing = add_filing(session, add_issuer(session))
    add_parse(session, filing)
    add_parse(session, filing, parser_version="filing-parser-v2", artifact_set_hash="1" * 64)
    session.commit()

    rows = session.execute(
        text("SELECT parser_version, is_current FROM filing_parse ORDER BY parser_version")
    ).all()

    assert rows == [("filing-parser-v1", True), ("filing-parser-v2", True)]


def test_fact_has_version_and_evidence(session):
    filing = add_filing(session, add_issuer(session))
    evidence = add_evidence(session, filing)
    parse = add_parse(session, filing)
    fact = XbrlFact(
        source_filing_id=filing.id,
        parse_run_id=parse.parse_run_id,
        filing_parse_id=parse.id,
        concept="Revenue",
        parser_version=PARSER_VERSION,
        value_numeric=100.0,
        unit="USD",
        evidence_locator_id=evidence.id,
    )
    session.add(fact)
    session.commit()

    assert fact.parser_version == PARSER_VERSION
    assert fact.evidence_locator_id == evidence.id


def test_fact_rejects_cross_filing_parse_or_evidence(session):
    first = add_filing(session, add_issuer(session))
    second = add_filing(
        session,
        add_issuer(session, cik="0000789019", name="Microsoft"),
        accession="0000789019-24-000001",
    )
    first_evidence = add_evidence(session, first)
    second_parse = add_parse(session, second, artifact_set_hash="d" * 64, modules_hash="e" * 64)
    with pytest.raises(IntegrityError):
        session.add(
            XbrlFact(
                source_filing_id=first.id,
                parse_run_id=second_parse.parse_run_id,
                filing_parse_id=second_parse.id,
                evidence_locator_id=first_evidence.id,
                concept="Revenue",
                parser_version=PARSER_VERSION,
                value_numeric=1,
            )
        )
        session.commit()


def test_extracted_values_require_evidence(session):
    session.add(
        XbrlFact(
            concept="Revenue",
            parser_version=PARSER_VERSION,
            value_numeric=100.0,
            unit="USD",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_fact_period_identity_and_dimensions_round_trip(session):
    filing = add_filing(session, add_issuer(session))
    evidence = add_evidence(
        session, filing, locator_type="xbrl_fact", locator_value="us-gaap:Revenue"
    )
    parse = add_parse(session, filing)
    fact = XbrlFact(
        source_filing_id=filing.id,
        parse_run_id=parse.parse_run_id,
        filing_parse_id=parse.id,
        evidence_locator_id=evidence.id,
        parser_version=PARSER_VERSION,
        concept_namespace="us-gaap",
        concept="Revenue",
        label="Total net sales",
        value_numeric=391035000000.0,
        unit="USD",
        decimals=-6,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 9, 30),
        period_type="ytd",
        dimensions={"segment": "cloud"},
        filed_at=date(2024, 11, 1),
        form="10-K",
        accession=ACCESSION,
    )
    session.add(fact)
    session.commit()
    session.expire_all()

    stored = session.get(XbrlFact, fact.id)

    assert stored.period_type == "ytd"
    assert stored.dimensions == {"segment": "cloud"}
    assert stored.value_numeric == pytest.approx(391035000000.0)


def test_statement_section_and_table_rows_round_trip(session):
    filing = add_filing(session, add_issuer(session))
    evidence = add_evidence(session, filing)
    parse = add_parse(session, filing)

    session.add_all(
        [
            StatementLine(
                source_filing_id=filing.id,
                parse_run_id=parse.parse_run_id,
                filing_parse_id=parse.id,
                evidence_locator_id=evidence.id,
                parser_version=PARSER_VERSION,
                statement_type="income_statement",
                order_index=1,
                label="Total net sales",
                concept="us-gaap:Revenue",
                value_numeric=391035000000.0,
                unit="USD",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 9, 30),
                period_type="ytd",
                dimensions={},
            ),
            FilingSection(
                source_filing_id=filing.id,
                parse_run_id=parse.parse_run_id,
                filing_parse_id=parse.id,
                evidence_locator_id=evidence.id,
                parser_version=PARSER_VERSION,
                section_type="md_and_a",
                heading="Item 7. Management's Discussion and Analysis",
                order_index=7,
                text="Liquidity and capital resources ...",
                raw_fragment_hash="9" * 64,
                status="parsed",
            ),
            ExtractedTable(
                source_filing_id=filing.id,
                parse_run_id=parse.parse_run_id,
                filing_parse_id=parse.id,
                evidence_locator_id=evidence.id,
                parser_version=PARSER_VERSION,
                table_type="debt_maturity",
                caption="Future maturities of term debt",
                order_index=3,
                columns=["period", "amount_usd_millions"],
                rows=[{"period": "2027", "amount_usd_millions": 1200.0}],
                period_hints={"period": "2027"},
                extraction_method="html_table",
                confidence=0.9,
                status="parsed",
                raw_fragment_hash="8" * 64,
            ),
        ]
    )
    session.commit()
    session.expire_all()

    table = session.query(ExtractedTable).one()
    assert table.rows[0]["period"] == "2027"
    assert session.query(StatementLine).one().statement_type == "income_statement"
    assert session.query(FilingSection).one().status == "parsed"


def test_parse_run_status_is_constrained(session):
    session.add(
        ParseRun(
            scope_type="ticker",
            scope_value="AAPL",
            parser_version=PARSER_VERSION,
            status="finished-with-flags",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_timestamps_are_timezone_aware(session):
    issuer = add_issuer(session)
    session.commit()
    session.refresh(issuer)

    assert issuer.created_at.tzinfo is not None
    assert issuer.created_at.utcoffset() == UTC.utcoffset(None)


def test_parse_run_counts_and_checkpoint_are_stored(session):
    run = ParseRun(
        scope_type="ticker",
        scope_value="AAPL",
        parser_version=PARSER_VERSION,
        status="partial",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        input_count=34,
        success_count=33,
        failure_count=1,
        checkpoint_accession=ACCESSION,
        error_summary={"0000320193-24-000002": "missing primary document"},
        command_metadata={"command": "fdc parse filings --ticker AAPL"},
    )
    session.add(run)
    session.commit()
    session.expire_all()

    stored = session.get(ParseRun, run.id)

    assert (stored.input_count, stored.success_count, stored.failure_count) == (34, 33, 1)
    assert stored.checkpoint_accession == ACCESSION
    assert stored.error_summary["0000320193-24-000002"].startswith("missing")


def test_artifact_role_must_be_known(session):
    filing = add_filing(session, add_issuer(session))
    session.add(
        Artifact(
            filing_id=filing.id,
            relative_path="odd.bin",
            role="mystery",
            sha256="e" * 64,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_sqlite_enforces_foreign_keys_for_parser_rows(session):
    """The schema contract must hold on the SQLite test backend too."""

    session.add(
        Artifact(
            filing_id=uuid4(),
            relative_path="orphan.htm",
            role="primary",
            sha256="f" * 64,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_a_filing_cascades_to_its_parse_rows(session):
    filing = add_filing(session, add_issuer(session))
    parse = add_parse(session, filing)
    parse_id, parse_run_id = parse.id, parse.parse_run_id
    add_evidence(session, filing)
    session.add(
        Artifact(
            filing_id=filing.id,
            relative_path="aapl-20240928.htm",
            role="primary",
            sha256="d" * 64,
        )
    )
    session.commit()

    session.delete(filing)
    session.commit()
    session.expire_all()

    assert session.query(Artifact).count() == 0
    assert session.query(FilingParse).count() == 0
    assert session.get(FilingParse, parse_id) is None
    assert session.get(ParseRun, parse_run_id) is not None
