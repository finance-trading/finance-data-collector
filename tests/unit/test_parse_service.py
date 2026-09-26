"""Unit coverage for atomic filing parse persistence."""

from __future__ import annotations

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
from fdc.models import EvidenceLocator, FilingParse, FilingSection, XbrlFact
from fdc.parsers.service import parse_one_filing

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
        (ParseStatus.FAILED, "failed"),
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
