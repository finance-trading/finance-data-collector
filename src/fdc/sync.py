"""Incremental archive synchronization and checkpointed parse runs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from fdc.archive import INDEX_FILENAME, PARSER_FORMS, normalize_form, scan_ticker_archive
from fdc.config import get_settings
from fdc.contracts import ArchiveScan, LocalFiling
from fdc.models import Filing, FilingParse, Issuer, ParseRun
from fdc.parsers import service as parser_service
from fdc.parsers.edgartools_adapter import installed_edgartools_version


def select_pending_filings(
    session: Session,
    scan: ArchiveScan,
    parser_version: str,
    force: bool = False,
) -> list[LocalFiling]:
    """Select filings without an exact current successful parse identity."""

    if force:
        return list(scan.filings)
    modules_hash = parser_service.parser_modules_hash()
    successful = set(
        session.execute(
            select(Filing.accession_number, FilingParse.artifact_set_hash).join(
                FilingParse, FilingParse.filing_id == Filing.id
            ).join(Issuer, Issuer.id == Filing.issuer_id).where(
                Issuer.ticker_hint == scan.ticker,
                FilingParse.parser_version == parser_version,
                FilingParse.parser_modules_hash == modules_hash,
                FilingParse.status == "success",
                FilingParse.is_current.is_(True),
            )
        ).all()
    )
    return [
        filing
        for filing in scan.filings
        if (filing.accession, filing.artifact_set_hash) not in successful
    ]


def _validated_forms(forms: set[str] | None) -> set[str] | None:
    if forms is None:
        return None
    normalized = {value for item in forms if (value := normalize_form(item)) is not None}
    unsupported = normalized.difference(PARSER_FORMS)
    if unsupported:
        raise ValueError(
            f"unsupported forms: {', '.join(sorted(unsupported))}; "
            f"supported forms: {', '.join(PARSER_FORMS)}"
        )
    if not normalized:
        raise ValueError("forms must contain at least one supported SEC form")
    return normalized


def parse_ticker(
    session_factory: sessionmaker[Session],
    ticker: str,
    sec_root: Path,
    force: bool = False,
    forms: set[str] | None = None,
    parser_version: str | None = None,
    accessions: set[str] | None = None,
    scope_type: str = "ticker",
    scope_value: str | None = None,
) -> ParseRun:
    """Incrementally parse one ticker and commit a checkpoint per filing."""

    selected_forms = _validated_forms(forms)
    settings = get_settings()
    if parser_version is not None:
        settings = settings.model_copy(update={"parser_version": parser_version})
    scan = scan_ticker_archive(Path(sec_root), ticker, forms=selected_forms)
    if accessions is not None:
        scan.filings = [
            filing for filing in scan.filings if filing.accession in accessions
        ]
        scan.eligible_count = len(scan.filings)
    with session_factory() as session:
        pending = select_pending_filings(
            session, scan, settings.parser_version, force=force
        )
        run = ParseRun(
            scope_type=scope_type,
            scope_value=scope_value if scope_value is not None else scan.ticker,
            parser_version=settings.parser_version,
            edgartools_version=settings.edgartools_version or installed_edgartools_version(),
            status="running",
            input_count=len(pending),
            error_summary={"errors": []},
            command_metadata={
                "force": force,
                "forms": sorted(selected_forms) if selected_forms is not None else None,
                "accessions": sorted(accessions) if accessions is not None else None,
                "sec_root": str(sec_root),
                "scan": scan.summary(),
                "parser_modules_hash": parser_service.parser_modules_hash(),
            },
        )
        session.add(run)
        if not scan.ok:
            run.status = "failed"
            run.failure_count = len(scan.gaps) or 1
            run.error_summary = {"errors": [gap.as_dict() for gap in scan.gaps]}
            run.finished_at = datetime.now(UTC)
        session.commit()
        run_id = run.id

    if not scan.ok:
        return run

    for local_filing in pending:
        with session_factory() as session:
            session.info[parser_service._RUN_INFO_KEY] = run_id
            try:
                parser_service.parse_one_filing(
                    session, local_filing, settings, force=force
                )
            except parser_service.ParseAttemptFailed:
                # The service atomically committed the attempt and parent-run
                # disposition before signalling that processing may continue.
                continue

    with session_factory() as session:
        stored_run = session.get(ParseRun, run_id)
        if stored_run is None:  # pragma: no cover - referential integrity guard
            raise RuntimeError(f"parse run {run_id} disappeared")
        if stored_run.failure_count and stored_run.success_count:
            stored_run.status = "partial"
        elif stored_run.failure_count:
            stored_run.status = "failed"
        else:
            stored_run.status = "completed"
        stored_run.finished_at = datetime.now(UTC)
        session.commit()
        return stored_run


def parse_all(
    session_factory: sessionmaker[Session],
    sec_root: Path,
    force: bool = False,
    forms: set[str] | None = None,
    parser_version: str | None = None,
) -> list[ParseRun]:
    """Parse every indexed ticker directory in deterministic name order."""

    selected_forms = _validated_forms(forms)
    root = Path(sec_root)
    tickers = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / INDEX_FILENAME).is_file()
    )
    return [
        parse_ticker(
            session_factory,
            ticker,
            root,
            force=force,
            forms=selected_forms,
            parser_version=parser_version,
        )
        for ticker in tickers
    ]
