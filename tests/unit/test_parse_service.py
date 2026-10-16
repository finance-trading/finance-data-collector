"""Unit coverage for atomic filing parse persistence."""

from __future__ import annotations

import signal
from dataclasses import replace

import pytest
from sqlalchemy import func, select

from fdc.archive import scan_ticker_archive
from fdc.config import Settings
from fdc.contracts import (
    EvidenceDraft,
    FactDraft,
    LocatorType,
    ParserOutput,
    ParseStatus,
    RowStatus,
    SectionDraft,
)
from fdc.models import EvidenceLocator, Filing, FilingParse, FilingSection, Issuer, XbrlFact
from fdc.parsers.service import ParseAttemptFailed, parse_one_filing, parser_modules_manifest

FIXTURE_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures" / "filings"
PARSER_VERSION = "filing-parser-v1"


def _settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        sec_user_agent="Collector test@example.com",
        parser_version=PARSER_VERSION,
    )


def _outputs(local_filing):
    source = local_filing.primary_artifact
    assert source is not None
    evidence = EvidenceDraft(
        locator_type=LocatorType.XBRL_FACT,
        locator_value="us-gaap:Revenue|context=c-1",
        relative_path=source.relative_path,
        content_sha256=source.sha256,
        excerpt="100",
    )
    xbrl = ParserOutput(
        status=ParseStatus.SUCCESS,
        parser_version=PARSER_VERSION,
        parse_mode="fixture-xbrl",
        facts=[
            FactDraft(
                concept="Revenue",
                value_numeric=100.0,
                unit="USD",
                evidence=evidence,
            )
        ],
    )
    section_evidence = EvidenceDraft(
        locator_type=LocatorType.HEADING,
        locator_value="Item 7",
        relative_path=source.relative_path,
        content_sha256=source.sha256,
        excerpt="Liquidity remained strong.",
    )
    html = ParserOutput(
        status=ParseStatus.SUCCESS,
        parser_version=PARSER_VERSION,
        parse_mode="fixture-html",
        sections=[
            SectionDraft(
                section_type="md_and_a",
                order_index=1,
                text="Liquidity remained strong.",
                status=RowStatus.PARSED,
                evidence=section_evidence,
            )
        ],
    )
    return xbrl, html


def test_parse_one_filing_persists_every_row_with_run_artifact_and_evidence(
    engine, session_factory, database_url, monkeypatch
):
    local_filing = scan_ticker_archive(FIXTURE_ROOT, "MSFT").filings[0]
    xbrl, html = _outputs(local_filing)
    monkeypatch.setattr(
        "fdc.parsers.service.EdgarToolsAdapter.parse", lambda _self, _filing: xbrl
    )
    monkeypatch.setattr(
        "fdc.parsers.service.parse_html_document",
        lambda _path, _filing, _version: html,
    )

    with session_factory() as session:
        result = parse_one_filing(session, local_filing, _settings(database_url))

    with session_factory() as session:
        stored = session.get(FilingParse, result.id)
        fact = session.scalar(select(XbrlFact))
        section = session.scalar(select(FilingSection))
        assert stored is not None
        assert stored.status == "success"
        assert stored.is_current is True
        assert fact is not None and section is not None
        assert fact.parse_run_id == stored.parse_run_id
        assert section.parse_run_id == stored.parse_run_id
        assert fact.source_filing_id == stored.filing_id
        assert section.source_filing_id == stored.filing_id
        assert fact.parser_version == PARSER_VERSION
        assert section.parser_version == PARSER_VERSION
        assert fact.evidence_locator_id != section.evidence_locator_id
        assert session.scalar(select(func.count(EvidenceLocator.id))) == 2
        for evidence_id in (fact.evidence_locator_id, section.evidence_locator_id):
            evidence = session.get(EvidenceLocator, evidence_id)
            assert evidence is not None
            assert evidence.artifact_id is not None
            assert evidence.filing_id == stored.filing_id


def test_parse_uses_index_cik_when_accession_filer_differs(
    engine, session_factory, database_url, monkeypatch
):
    local_filing = scan_ticker_archive(FIXTURE_ROOT, "MSFT").filings[0]
    local_filing = replace(
        local_filing,
        accession="0000950170-25-100235",
        index_record={"cik": "0000789019", "company_name": "Microsoft Corporation"},
    )
    xbrl, html = _outputs(local_filing)
    monkeypatch.setattr("fdc.parsers.service.EdgarToolsAdapter.parse", lambda *_: xbrl)
    monkeypatch.setattr("fdc.parsers.service.parse_html_document", lambda *_: html)

    with session_factory() as session:
        result = parse_one_filing(session, local_filing, _settings(database_url))

    with session_factory() as session:
        filing = session.get(Filing, result.filing_id)
        issuer = session.get(Issuer, filing.issuer_id)
        assert issuer.cik == "0000789019"
        assert issuer.ticker_hint == "MSFT"


def test_parse_persists_canonical_edgar_filing_and_artifact_urls(
    engine, session_factory, database_url, monkeypatch
):
    local_filing = scan_ticker_archive(FIXTURE_ROOT, "MSFT").filings[0]
    xbrl, html = _outputs(local_filing)
    monkeypatch.setattr("fdc.parsers.service.EdgarToolsAdapter.parse", lambda *_: xbrl)
    monkeypatch.setattr("fdc.parsers.service.parse_html_document", lambda *_: html)

    with session_factory() as session:
        result = parse_one_filing(session, local_filing, _settings(database_url))

    base = "https://www.sec.gov/Archives/edgar/data/0/000000000024000001/"
    with session_factory() as session:
        filing = session.get(Filing, result.filing_id)
        evidence = session.scalars(select(EvidenceLocator)).all()
        assert filing.sec_url == base + "msft-20240630.htm"
        assert {row.accession_url for row in evidence} == {base + "msft-20240630.htm"}


def test_retry_backfills_missing_canonical_filing_url(
    engine, session_factory, database_url, monkeypatch
):
    local_filing = scan_ticker_archive(FIXTURE_ROOT, "MSFT").filings[0]
    xbrl, html = _outputs(local_filing)
    monkeypatch.setattr("fdc.parsers.service.EdgarToolsAdapter.parse", lambda *_: xbrl)
    monkeypatch.setattr("fdc.parsers.service.parse_html_document", lambda *_: html)
    settings = _settings(database_url)

    with session_factory() as session:
        first = parse_one_filing(session, local_filing, settings)
    with session_factory() as session:
        filing = session.get(Filing, first.filing_id)
        filing.sec_url = None
        session.commit()
    with session_factory() as session:
        retried = parse_one_filing(session, local_filing, settings, force=True)

    with session_factory() as session:
        filing = session.get(Filing, retried.filing_id)
        assert filing.sec_url == (
            "https://www.sec.gov/Archives/edgar/data/0/"
            "000000000024000001/msft-20240630.htm"
        )


def test_parser_module_identity_includes_installed_edgartools_version():
    assert parser_modules_manifest()["edgartools"] == "5.58.0"


def test_parse_exception_rolls_back_all_extracted_rows_and_persists_failure(
    engine, session_factory, database_url, monkeypatch
):
    local_filing = scan_ticker_archive(FIXTURE_ROOT, "MSFT").filings[0]
    xbrl, _html = _outputs(local_filing)
    monkeypatch.setattr(
        "fdc.parsers.service.EdgarToolsAdapter.parse", lambda _self, _filing: xbrl
    )

    def fail_html(*_args):
        raise RuntimeError("fixture HTML failure")

    monkeypatch.setattr("fdc.parsers.service.parse_html_document", fail_html)

    with session_factory() as session:
        result = parse_one_filing(session, local_filing, _settings(database_url))

    with session_factory() as session:
        stored = session.get(FilingParse, result.id)
        assert stored is not None
        assert stored.status == "failed"
        assert stored.is_current is False
        assert stored.diagnostics["error_type"] == "RuntimeError"
        assert "fixture HTML failure" in stored.diagnostics["detail"]
        assert session.scalar(select(func.count(XbrlFact.id))) == 0
        assert session.scalar(select(func.count(FilingSection.id))) == 0
        assert session.scalar(select(func.count(EvidenceLocator.id))) == 0


def test_parse_one_skips_an_existing_success_without_calling_parsers(
    engine, session_factory, database_url, monkeypatch
):
    local_filing = scan_ticker_archive(FIXTURE_ROOT, "MSFT").filings[0]
    xbrl, html = _outputs(local_filing)
    monkeypatch.setattr(
        "fdc.parsers.service.EdgarToolsAdapter.parse", lambda _self, _filing: xbrl
    )
    monkeypatch.setattr(
        "fdc.parsers.service.parse_html_document",
        lambda _path, _filing, _version: html,
    )
    with session_factory() as session:
        first = parse_one_filing(session, local_filing, _settings(database_url))

    def unexpected(*_args, **_kwargs):
        raise AssertionError("an exact successful identity must be skipped")

    monkeypatch.setattr("fdc.parsers.service.EdgarToolsAdapter.parse", unexpected)
    monkeypatch.setattr("fdc.parsers.service.parse_html_document", unexpected)
    with session_factory() as session:
        second = parse_one_filing(session, local_filing, _settings(database_url))

    assert second.id == first.id


@pytest.mark.parametrize(
    ("module_status", "expected_status"),
    [
        (ParseStatus.PARTIAL, "partial"),
        (ParseStatus.FAILED, "partial"),
    ],
)
def test_incomplete_required_module_result_is_never_current(
    engine,
    session_factory,
    database_url,
    monkeypatch,
    module_status,
    expected_status,
):
    local_filing = scan_ticker_archive(FIXTURE_ROOT, "MSFT").filings[0]
    xbrl, html = _outputs(local_filing)
    html.status = module_status
    monkeypatch.setattr(
        "fdc.parsers.service.EdgarToolsAdapter.parse", lambda _self, _filing: xbrl
    )
    monkeypatch.setattr(
        "fdc.parsers.service.parse_html_document",
        lambda _path, _filing, _version: html,
    )

    with session_factory() as session:
        result = parse_one_filing(session, local_filing, _settings(database_url))

    assert result.status == expected_status
    assert result.is_current is False


def test_one_failed_module_with_usable_output_is_partial(
    engine, session_factory, database_url, monkeypatch
):
    local_filing = scan_ticker_archive(FIXTURE_ROOT, "MSFT").filings[0]
    xbrl, html = _outputs(local_filing)
    xbrl.status = ParseStatus.FAILED
    assert html.is_empty is False
    monkeypatch.setattr(
        "fdc.parsers.service.EdgarToolsAdapter.parse", lambda _self, _filing: xbrl
    )
    monkeypatch.setattr(
        "fdc.parsers.service.parse_html_document",
        lambda _path, _filing, _version: html,
    )

    with session_factory() as session:
        result = parse_one_filing(session, local_filing, _settings(database_url))

    assert result.status == "partial"
    assert result.is_current is False


def test_both_failed_modules_are_failed(
    engine, session_factory, database_url, monkeypatch
):
    local_filing = scan_ticker_archive(FIXTURE_ROOT, "MSFT").filings[0]
    xbrl, html = _outputs(local_filing)
    xbrl.status = ParseStatus.FAILED
    html.status = ParseStatus.FAILED
    xbrl.facts.clear()
    xbrl.statements.clear()
    html.sections.clear()
    html.tables.clear()
    monkeypatch.setattr(
        "fdc.parsers.service.EdgarToolsAdapter.parse", lambda _self, _filing: xbrl
    )
    monkeypatch.setattr(
        "fdc.parsers.service.parse_html_document",
        lambda _path, _filing, _version: html,
    )

    with session_factory() as session:
        result = parse_one_filing(session, local_filing, _settings(database_url))

    assert result.status == "failed"


def test_parse_timeout_is_persisted_and_signals_processing_may_continue(
    engine, session_factory, database_url, monkeypatch
):
    local_filing = scan_ticker_archive(FIXTURE_ROOT, "MSFT").filings[0]
    settings = _settings(database_url).model_copy(update={"parse_timeout_seconds": 7})
    alarms = []
    handlers = []

    def fake_signal(sig, handler):
        handlers.append((sig, handler))
        return signal.SIG_DFL

    def fake_setitimer(which, seconds):
        alarms.append((which, seconds))
        return (0.0, 0.0)

    def time_out(_self, _filing):
        handlers[-1][1](signal.SIGALRM, None)

    monkeypatch.setattr(signal, "signal", fake_signal)
    monkeypatch.setattr(signal, "setitimer", fake_setitimer)
    monkeypatch.setattr("fdc.parsers.service.EdgarToolsAdapter.parse", time_out)

    with session_factory() as session:
        with pytest.raises(ParseAttemptFailed) as raised:
            parse_one_filing(session, local_filing, settings)

    assert raised.value.status == "failed"
    assert raised.value.diagnostics["error_type"] == "FilingParseTimeout"
    assert raised.value.diagnostics["timeout_seconds"] == 7
    assert alarms == [(signal.ITIMER_REAL, 7), (signal.ITIMER_REAL, 0)]

    with session_factory() as session:
        stored = session.scalars(select(FilingParse)).one()
        assert stored.status == "failed"
        assert stored.diagnostics["error_type"] == "FilingParseTimeout"


def test_ambiguous_evidence_is_persisted_without_a_false_artifact_link(
    engine, session_factory, database_url, monkeypatch
):
    local_filing = scan_ticker_archive(FIXTURE_ROOT, "MSFT").filings[0]
    xbrl, html = _outputs(local_filing)
    xbrl.facts[0] = replace(
        xbrl.facts[0],
        evidence=EvidenceDraft(
            locator_type=LocatorType.XBRL_FACT,
            locator_value="concept=FixtureRevenue;source=ambiguous",
        ),
    )
    monkeypatch.setattr(
        "fdc.parsers.service.EdgarToolsAdapter.parse", lambda _self, _filing: xbrl
    )
    monkeypatch.setattr(
        "fdc.parsers.service.parse_html_document",
        lambda _path, _filing, _version: html,
    )

    with session_factory() as session:
        result = parse_one_filing(session, local_filing, _settings(database_url))

    assert result.status == "success"
    with session_factory() as session:
        evidence = session.scalars(
            select(EvidenceLocator).where(
                EvidenceLocator.locator_value == "concept=FixtureRevenue;source=ambiguous"
            )
        ).one()
        assert evidence.artifact_id is None
