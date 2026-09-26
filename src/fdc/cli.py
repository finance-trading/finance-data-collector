"""Operational CLI for filing parse writes and parse-run inspection."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

import typer
from sqlalchemy.orm import Session, sessionmaker

from fdc.archive import (
    INDEX_FILENAME,
    PARSER_FORMS,
    normalize_accession,
    normalize_form,
    scan_ticker_archive,
)
from fdc.db import get_session_factory
from fdc.models import ParseRun
from fdc.sync import parse_all as _parse_all
from fdc.sync import parse_ticker as _parse_ticker

app = typer.Typer(help="Local SEC filing parser operations.", no_args_is_help=True)
parse_app = typer.Typer(help="Create filing parse runs.", no_args_is_help=True)
parse_runs_app = typer.Typer(help="Inspect parse runs.", no_args_is_help=True)
app.add_typer(parse_app, name="parse")
app.add_typer(parse_runs_app, name="parse-runs")

_DEFAULT_DATABASE_URL = "postgresql+psycopg://fdc:fdc@localhost:5432/fdc"


def parse_ticker(**kwargs) -> ParseRun:
    """CLI seam over the ticker sync service, kept patchable for operations tests."""

    return _parse_ticker(**kwargs)


def parse_all(**kwargs) -> list[ParseRun]:
    """CLI seam over the all-ticker sync service."""

    return _parse_all(**kwargs)


def parse_accession(
    *,
    session_factory: sessionmaker[Session],
    accession: str,
    sec_root: Path,
    force: bool,
    parser_version: str | None,
) -> ParseRun:
    """Resolve an accession in the local archive and parse only that filing."""

    normalized = normalize_accession(accession)
    if normalized is None:
        raise ValueError(f"invalid accession {accession!r}")
    root = Path(sec_root)
    for ticker_dir in sorted(root.iterdir() if root.is_dir() else []):
        if not ticker_dir.is_dir() or not (ticker_dir / INDEX_FILENAME).is_file():
            continue
        scan = scan_ticker_archive(root, ticker_dir.name)
        if normalized in scan.accessions:
            return _parse_ticker(
                session_factory=session_factory,
                ticker=ticker_dir.name,
                sec_root=root,
                force=force,
                parser_version=parser_version,
                accessions={normalized},
                scope_type="filing",
                scope_value=normalized,
            )
    raise LookupError(f"accession {normalized} was not found under {root}")


def load_parse_run(
    session_factory: sessionmaker[Session], run_id: str
) -> ParseRun | None:
    """Load one run without exposing a write-capable HTTP operation."""

    try:
        identifier = UUID(run_id)
    except ValueError:
        return None
    with session_factory() as session:
        return session.get(ParseRun, identifier)


def _forms(value: str | None) -> set[str] | None:
    if value is None:
        return None
    forms = {normalize_form(item) for item in value.split(",")}
    normalized = {item for item in forms if item is not None}
    if not normalized:
        raise typer.BadParameter("--forms requires at least one form")
    unsupported = normalized.difference(PARSER_FORMS)
    if unsupported:
        raise typer.BadParameter(
            f"unsupported forms: {', '.join(sorted(unsupported))}; "
            f"supported forms: {', '.join(PARSER_FORMS)}"
        )
    return normalized


def _runtime_storage() -> tuple[str, Path]:
    """Resolve storage without requiring SEC network credentials for inspection."""

    return (
        os.getenv("FDC_DATABASE_URL", _DEFAULT_DATABASE_URL),
        Path(os.getenv("FDC_SEC_ROOT", "./sec")),
    )


def _run_line(run: ParseRun) -> str:
    return (
        f"run_id={run.id} status={run.status} input={run.input_count} "
        f"success={run.success_count} failure={run.failure_count} "
        f"checkpoint={run.checkpoint_accession or '-'}"
    )


def _print_run(run: ParseRun, *, include_diagnostics: bool = True) -> None:
    typer.echo(_run_line(run))
    if include_diagnostics and run.error_summary:
        for error in run.error_summary.get("errors", []):
            accession = error.get("accession", "-")
            status = error.get("status", "failed")
            diagnostics = error.get("diagnostics", error)
            typer.echo(
                f"accession={accession} status={status} "
                f"diagnostics={json.dumps(diagnostics, sort_keys=True, default=str)}"
            )


@parse_app.command("filings")
def parse_filings_command(
    ticker: str | None = typer.Option(None, "--ticker", help="Ticker archive to parse."),
    all_: bool = typer.Option(False, "--all", help="Parse every indexed ticker archive."),
    forms: str | None = typer.Option(None, "--forms", help="Comma-separated SEC forms."),
    force: bool = typer.Option(False, "--force", help="Explicitly re-run selected filings."),
    parser_version: str | None = typer.Option(
        None, "--parser-version", help="Override the configured serving parser version."
    ),
) -> None:
    """Parse a ticker archive or every indexed ticker archive."""

    if (ticker is None) == (not all_):
        raise typer.BadParameter("choose exactly one of --ticker or --all")
    database_url, sec_root = _runtime_storage()
    factory = get_session_factory(database_url)
    selected_forms = _forms(forms)
    try:
        if all_:
            runs = parse_all(
                session_factory=factory,
                sec_root=sec_root,
                force=force,
                forms=selected_forms,
                parser_version=parser_version,
            )
        else:
            run = parse_ticker(
                session_factory=factory,
                ticker=(ticker or "").strip().upper(),
                sec_root=sec_root,
                force=force,
                forms=selected_forms,
                parser_version=parser_version,
            )
            runs = [run]
    except Exception as error:
        typer.echo(f"parse operation failed: {type(error).__name__}: {error}", err=True)
        raise typer.Exit(code=1) from error
    for run in runs:
        _print_run(run)
    if any(run.status not in {"completed"} for run in runs):
        raise typer.Exit(code=1)


@parse_app.command("filing")
def parse_filing_command(
    accession: str = typer.Option(..., "--accession", help="Canonical SEC accession."),
    force: bool = typer.Option(False, "--force", help="Explicitly re-run the filing."),
    parser_version: str | None = typer.Option(
        None, "--parser-version", help="Override the configured serving parser version."
    ),
) -> None:
    """Parse exactly one locally archived accession."""

    database_url, sec_root = _runtime_storage()
    factory = get_session_factory(database_url)
    try:
        run = parse_accession(
            session_factory=factory,
            accession=accession,
            sec_root=sec_root,
            force=force,
            parser_version=parser_version,
        )
    except Exception as error:
        typer.echo(f"parse operation failed: {type(error).__name__}: {error}", err=True)
        raise typer.Exit(code=1) from error
    _print_run(run)
    if run.status != "completed":
        raise typer.Exit(code=1)


@parse_runs_app.command("show")
def parse_runs_show_command(run_id: str) -> None:
    """Show run counts, checkpoint, and accession-scoped diagnostics."""

    database_url, _sec_root = _runtime_storage()
    factory = get_session_factory(database_url)
    run = load_parse_run(factory, run_id)
    if run is None:
        typer.echo(f"parse run not found: {run_id}", err=True)
        raise typer.Exit(code=1)
    _print_run(run)


if __name__ == "__main__":  # pragma: no cover
    app()
