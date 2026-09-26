"""Offline integration tests for incremental, checkpointed parsing."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from fdc.config import get_settings
from fdc.models import FilingParse
from fdc.parsers import service as parse_service
from fdc.sync import parse_ticker, select_pending_filings

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "filings"


@pytest.fixture
def fixture_root() -> Path:
    return FIXTURE_ROOT


def test_second_parse_skips_same_identity(engine, session_factory, fixture_root):
    first = parse_ticker(session_factory, "MSFT", fixture_root)
    second = parse_ticker(session_factory, "MSFT", fixture_root)

    assert first.success_count == 2
    assert second.input_count == 0
    assert second.success_count == 0
    assert second.status == "completed"


def test_parser_version_creates_new_result_without_deleting_old(
    engine, session_factory, fixture_root, monkeypatch
):
    parse_ticker(session_factory, "MSFT", fixture_root)
    monkeypatch.setenv("FDC_PARSER_VERSION", "filing-parser-v2")
    get_settings.cache_clear()

    run = parse_ticker(session_factory, "MSFT", fixture_root)

    assert run.success_count == 2
    with session_factory() as session:
        assert session.scalar(select(func.count(FilingParse.id))) == 4


def test_module_hash_change_reparses_and_switches_current_pointer(
    engine, session_factory, fixture_root, monkeypatch
):
    parse_ticker(session_factory, "MSFT", fixture_root)
    monkeypatch.setattr(parse_service, "parser_modules_hash", lambda: "f" * 64)

    run = parse_ticker(session_factory, "MSFT", fixture_root)

    assert run.success_count == 2
    with session_factory() as session:
        parses = session.scalars(select(FilingParse)).all()
        assert len(parses) == 4
        assert sum(result.is_current for result in parses) == 2
        assert {result.parser_modules_hash for result in parses} == {
            "f" * 64,
            next(
                result.parser_modules_hash
                for result in parses
                if result.parser_modules_hash != "f" * 64
            ),
        }


def test_one_failed_filing_is_partial_checkpointed_and_retryable(
    engine, session_factory, fixture_root, monkeypatch
):
    real_parse_html = parse_service.parse_html_document

    def fail_for_one_accession(path, filing, parser_version):
        if filing.accession.endswith("000002"):
            raise RuntimeError("one filing failed")
        return real_parse_html(path, filing, parser_version)

    monkeypatch.setattr(parse_service, "parse_html_document", fail_for_one_accession)
    first = parse_ticker(session_factory, "MSFT", fixture_root)

    assert first.status == "partial"
    assert first.success_count == 1
    assert first.failure_count == 1
    assert first.checkpoint_accession == "0000000000-25-000002"
    assert first.error_summary["errors"][0]["accession"] == "0000000000-25-000002"

    monkeypatch.setattr(parse_service, "parse_html_document", real_parse_html)
    retry = parse_ticker(session_factory, "MSFT", fixture_root)

    assert retry.input_count == 1
    assert retry.success_count == 1
    assert retry.failure_count == 0
    assert retry.status == "completed"


def test_force_selects_successful_exact_identity(engine, session_factory, fixture_root):
    parse_ticker(session_factory, "MSFT", fixture_root)
    from fdc.archive import scan_ticker_archive

    scan = scan_ticker_archive(fixture_root, "MSFT")
    with session_factory() as session:
        pending = select_pending_filings(
            session,
            scan,
            get_settings().parser_version,
            force=True,
        )

    assert [filing.accession for filing in pending] == scan.accessions

