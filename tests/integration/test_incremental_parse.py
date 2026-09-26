"""Offline integration tests for incremental, checkpointed parsing."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from fdc.config import get_settings
from fdc.contracts import (
    EvidenceDraft,
    FactDraft,
    LocatorType,
    ParserOutput,
    ParseStatus,
    RowStatus,
    SectionDraft,
)
from fdc.models import FilingParse, FilingSection, ParseRun, XbrlFact
from fdc.parsers import service as parse_service
from fdc.sync import parse_ticker, select_pending_filings

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "filings"


@pytest.fixture
def fixture_root() -> Path:
    return FIXTURE_ROOT


@pytest.fixture(autouse=True)
def successful_required_modules(monkeypatch):
    """Keep sync tests about orchestration, not fixture-level partial output."""

    def xbrl_output(_self, filing):
        source = filing.primary_artifact
        return ParserOutput(
            status=ParseStatus.SUCCESS,
            parser_version=get_settings().parser_version,
            parse_mode="fixture-xbrl",
            facts=[
                FactDraft(
                    concept="FixtureRevenue",
                    value_numeric=1.0,
                    evidence=EvidenceDraft(
                        locator_type=LocatorType.XBRL_FACT,
                        locator_value="FixtureRevenue|context=fixture",
                        relative_path=source.relative_path,
                        content_sha256=source.sha256,
                    ),
                )
            ],
        )

    def html_output(_path, filing, parser_version):
        source = filing.primary_artifact
        return ParserOutput(
            status=ParseStatus.SUCCESS,
            parser_version=parser_version,
            parse_mode="fixture-html",
            sections=[
                SectionDraft(
                    section_type="fixture_section",
                    order_index=1,
                    text="fixture",
                    status=RowStatus.PARSED,
                    evidence=EvidenceDraft(
                        locator_type=LocatorType.HEADING,
                        locator_value="Fixture",
                        relative_path=source.relative_path,
                        content_sha256=source.sha256,
                    ),
                )
            ],
        )

    monkeypatch.setattr(
        parse_service.EdgarToolsAdapter,
        "parse",
        xbrl_output,
    )
    monkeypatch.setattr(
        parse_service,
        "parse_html_document",
        html_output,
    )


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


def test_forced_success_keeps_result_provenance_and_children_immutable(
    engine, session_factory, fixture_root
):
    parse_ticker(session_factory, "MSFT", fixture_root)
    with session_factory() as session:
        before = {
            result.id: (result.parse_run_id, result.created_at)
            for result in session.scalars(select(FilingParse)).all()
        }
        fact_ids = set(session.scalars(select(XbrlFact.id)).all())
        section_ids = set(session.scalars(select(FilingSection.id)).all())

    forced = parse_ticker(session_factory, "MSFT", fixture_root, force=True)

    assert forced.input_count == 2
    assert forced.success_count == 2
    with session_factory() as session:
        after = {
            result.id: (result.parse_run_id, result.created_at)
            for result in session.scalars(select(FilingParse)).all()
        }
        assert after == before
        assert set(session.scalars(select(XbrlFact.id)).all()) == fact_ids
        assert set(session.scalars(select(FilingSection.id)).all()) == section_ids


def test_forced_failure_preserves_current_result_and_continues_run(
    engine, session_factory, fixture_root, monkeypatch
):
    parse_ticker(session_factory, "MSFT", fixture_root)
    with session_factory() as session:
        before = {
            result.id: result.parse_run_id
            for result in session.scalars(select(FilingParse)).all()
        }

    successful_html = parse_service.parse_html_document

    def fail_first(path, filing, parser_version):
        if filing.accession.endswith("000001"):
            raise RuntimeError("forced attempt failed")
        return successful_html(path, filing, parser_version)

    monkeypatch.setattr(parse_service, "parse_html_document", fail_first)
    forced = parse_ticker(session_factory, "MSFT", fixture_root, force=True)

    assert forced.status == "partial"
    assert forced.success_count == 1
    assert forced.failure_count == 1
    assert forced.checkpoint_accession == "0000000000-25-000002"
    assert forced.error_summary["errors"][0]["accession"] == "0000000000-24-000001"
    assert "forced attempt failed" in str(forced.error_summary)
    with session_factory() as session:
        current = session.scalars(
            select(FilingParse).where(FilingParse.is_current.is_(True))
        ).all()
        assert len(current) == 2
        assert {result.id: result.parse_run_id for result in current} == before


def test_forced_failure_disposition_is_durable_before_sync_continues(
    engine, session_factory, fixture_root, monkeypatch
):
    parse_ticker(session_factory, "MSFT", fixture_root)
    from fdc.archive import scan_ticker_archive

    filing = scan_ticker_archive(fixture_root, "MSFT").filings[0]
    with session_factory() as session:
        run = ParseRun(
            scope_type="ticker",
            scope_value="MSFT",
            parser_version=get_settings().parser_version,
            status="running",
            input_count=2,
            error_summary={"errors": []},
            command_metadata={"force": True},
        )
        session.add(run)
        session.commit()
        run_id = run.id

    def fail_at_service_boundary(*_args):
        raise RuntimeError("boundary crash fixture")

    monkeypatch.setattr(parse_service, "parse_html_document", fail_at_service_boundary)
    with session_factory() as session:
        session.info[parse_service._RUN_INFO_KEY] = run_id
        with pytest.raises(parse_service.ParseAttemptFailed):
            parse_service.parse_one_filing(
                session,
                filing,
                get_settings(),
                force=True,
            )

    # Simulate the process dying here: no parse_ticker continuation transaction
    # runs. The attempt disposition must already be durable on the parent run.
    with session_factory() as session:
        stored = session.get(ParseRun, run_id)
        assert stored.status == "running"
        assert stored.failure_count == 1
        assert stored.success_count == 0
        assert stored.checkpoint_accession == filing.accession
        assert stored.error_summary["errors"][0]["accession"] == filing.accession
        assert stored.error_summary["errors"][0]["status"] == "failed"
        assert "boundary crash fixture" in str(stored.error_summary)


def test_historical_exact_success_is_reactivated_without_rewrite(
    engine, session_factory, fixture_root, monkeypatch
):
    hash_a = parse_service.parser_modules_hash()
    parse_ticker(session_factory, "MSFT", fixture_root)
    with session_factory() as session:
        original_a = {
            result.filing_id: (result.id, result.parse_run_id)
            for result in session.scalars(select(FilingParse)).all()
        }

    monkeypatch.setattr(parse_service, "parser_modules_hash", lambda: "b" * 64)
    parse_ticker(session_factory, "MSFT", fixture_root)
    monkeypatch.setattr(parse_service, "parser_modules_hash", lambda: hash_a)

    reactivated = parse_ticker(session_factory, "MSFT", fixture_root)

    assert reactivated.input_count == 2
    assert reactivated.success_count == 2
    with session_factory() as session:
        results = session.scalars(select(FilingParse)).all()
        assert len(results) == 4
        current = {result.filing_id: result for result in results if result.is_current}
        assert {
            filing_id: (result.id, result.parse_run_id)
            for filing_id, result in current.items()
        } == original_a

    final = parse_ticker(session_factory, "MSFT", fixture_root)
    assert final.input_count == 0
