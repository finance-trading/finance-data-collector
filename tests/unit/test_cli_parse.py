"""CLI contracts for filing parse operations and run inspection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from fdc.cli import app, parse_accession
from fdc.sync import parse_ticker as sync_parse_ticker

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "filings"


def _fake_run(**overrides):
    values = {
        "id": uuid4(),
        "status": "completed",
        "input_count": 2,
        "success_count": 2,
        "failure_count": 0,
        "checkpoint_accession": "0000000000-24-000001",
        "error_summary": {"errors": []},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_parse_filings_cli_passes_force_forms_and_parser_version(monkeypatch):
    """Regression: dropping any parse selector would broaden or alter the run."""

    called = {}
    monkeypatch.delenv("FDC_SEC_USER_AGENT", raising=False)
    monkeypatch.setattr("fdc.cli.get_session_factory", lambda *_args: "factory")
    monkeypatch.setattr(
        "fdc.cli.parse_ticker",
        lambda **kwargs: called.update(kwargs) or _fake_run(),
    )

    result = CliRunner().invoke(
        app,
        [
            "parse",
            "filings",
            "--ticker",
            "msft",
            "--force",
            "--forms",
            "10-K,10-Q",
            "--parser-version",
            "parser-v2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert called == {
        "session_factory": "factory",
        "ticker": "MSFT",
        "sec_root": called["sec_root"],
        "force": True,
        "forms": {"10-K", "10-Q"},
        "parser_version": "parser-v2",
    }
    assert "run_id=" in result.output
    assert "status=completed" in result.output
    assert "success=2" in result.output


def test_parse_filings_cli_all_scope_calls_parse_all(monkeypatch):
    """Regression: --all must use the all-ticker operation, not a fake ticker."""

    called = {}
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "Collector test@example.com")
    monkeypatch.setattr("fdc.cli.get_session_factory", lambda *_args: "factory")
    monkeypatch.setattr(
        "fdc.cli.parse_all",
        lambda **kwargs: called.update(kwargs)
        or [_fake_run(status="partial", success_count=1, failure_count=1)],
    )

    result = CliRunner().invoke(app, ["parse", "filings", "--all", "--force"])

    assert result.exit_code == 1
    assert called["force"] is True
    assert "status=partial" in result.output
    assert "failure=1" in result.output


def test_parse_filings_cli_rejects_unsupported_form_before_starting_run(monkeypatch):
    """Regression: unsupported forms must not become successful empty runs."""

    monkeypatch.setattr("fdc.cli.get_session_factory", lambda *_args: "factory")

    called = False

    def unexpected(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("sync was called")

    monkeypatch.setattr("fdc.cli.parse_ticker", unexpected)

    result = CliRunner().invoke(
        app, ["parse", "filings", "--ticker", "MSFT", "--forms", "8-K"]
    )

    assert result.exit_code != 0
    assert called is False
    assert "unsupported" in result.output.lower()


def test_sync_passes_validated_forms_into_archive_scan(
    engine, session_factory, monkeypatch
):
    """Regression: scanning all forms then filtering wastes work and hides bad input."""

    from fdc.archive import scan_ticker_archive

    called = {}

    def capture_scan(sec_root, ticker, forms=None):
        called["forms"] = forms
        return scan_ticker_archive(sec_root, ticker, forms=forms)

    monkeypatch.setattr("fdc.sync.scan_ticker_archive", capture_scan)
    monkeypatch.setattr("fdc.sync.select_pending_filings", lambda *_args, **_kwargs: [])

    run = sync_parse_ticker(
        session_factory,
        "MSFT",
        FIXTURE_ROOT,
        forms={"10-K"},
    )

    assert called["forms"] == {"10-K"}
    assert run.command_metadata["forms"] == ["10-K"]


def test_sync_rejects_unsupported_forms_without_scanning(
    engine, session_factory, monkeypatch
):
    """Regression: non-CLI callers must receive the same supported-form guard."""

    def unexpected(*_args, **_kwargs):
        raise AssertionError("scanner must not run for unsupported form input")

    monkeypatch.setattr("fdc.sync.scan_ticker_archive", unexpected)

    with pytest.raises(ValueError, match="unsupported"):
        sync_parse_ticker(
            session_factory,
            "MSFT",
            FIXTURE_ROOT,
            forms={"8-K"},
        )


def test_parse_accession_persists_filing_scope(
    engine, session_factory, monkeypatch
):
    """Regression: accession operations must not be recorded as ticker runs."""

    monkeypatch.setattr("fdc.sync.select_pending_filings", lambda *_args, **_kwargs: [])

    run = parse_accession(
        session_factory=session_factory,
        accession="000000000024000001",
        sec_root=FIXTURE_ROOT,
        force=False,
        parser_version=None,
    )

    assert run.scope_type == "filing"
    assert run.scope_value == "0000000000-24-000001"


def test_parse_filing_cli_passes_accession_and_prints_explicit_failure(monkeypatch):
    """Regression: failed accession diagnostics must not be hidden by exit zero."""

    called = {}
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "Collector test@example.com")
    monkeypatch.setattr("fdc.cli.get_session_factory", lambda *_args: "factory")
    monkeypatch.setattr(
        "fdc.cli.parse_accession",
        lambda **kwargs: called.update(kwargs)
        or _fake_run(
            status="failed",
            input_count=1,
            success_count=0,
            failure_count=1,
            error_summary={
                "errors": [
                    {
                        "accession": "0000000000-24-000001",
                        "diagnostics": {"detail": "fixture parse failed"},
                    }
                ]
            },
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "parse",
            "filing",
            "--accession",
            "0000000000-24-000001",
            "--force",
        ],
    )

    assert result.exit_code == 1
    assert called["accession"] == "0000000000-24-000001"
    assert called["force"] is True
    assert "fixture parse failed" in result.output


def test_parse_runs_show_prints_accession_diagnostics(monkeypatch):
    """Regression: run inspection must retain accession-level diagnostics."""

    run_id = uuid4()
    monkeypatch.setenv("FDC_SEC_USER_AGENT", "Collector test@example.com")
    monkeypatch.setattr("fdc.cli.get_session_factory", lambda *_args: "factory")
    monkeypatch.setattr(
        "fdc.cli.load_parse_run",
        lambda _factory, value: _fake_run(
            id=run_id,
            status="partial",
            success_count=1,
            failure_count=1,
            error_summary={
                "errors": [
                    {
                        "accession": "0000000000-24-000001",
                        "status": "failed",
                        "diagnostics": {"detail": "bad table"},
                    }
                ]
            },
        ),
    )

    result = CliRunner().invoke(app, ["parse-runs", "show", str(run_id)])

    assert result.exit_code == 0, result.output
    assert "0000000000-24-000001" in result.output
    assert "bad table" in result.output
