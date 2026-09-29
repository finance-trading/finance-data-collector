"""Atomic persistence boundary for one locally archived SEC filing."""

from __future__ import annotations

import hashlib
import json
import signal
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from fdc.config import Settings
from fdc.contracts import EvidenceDraft, LocalFiling, ParserDiagnostic, ParserOutput
from fdc.models import (
    Artifact,
    EvidenceLocator,
    ExtractedTable,
    Filing,
    FilingParse,
    FilingSection,
    Issuer,
    ParseRun,
    StatementLine,
    XbrlFact,
)
from fdc.parsers.edgartools_adapter import EdgarToolsAdapter, installed_edgartools_version
from fdc.parsers.html_parser import parse_html_document

_MODULE_FILES = (
    "edgartools_adapter.py",
    "html_parser.py",
    "disclosures.py",
)
_RUN_INFO_KEY = "fdc_parse_run_id"


class ParseAttemptFailed(RuntimeError):
    """A parse attempt failed without changing an existing immutable result."""

    def __init__(
        self,
        status: str,
        diagnostics: dict[str, Any],
        *,
        disposition_recorded: bool = False,
    ) -> None:
        super().__init__(diagnostics.get("detail") or f"parse attempt ended {status}")
        self.status = status
        self.diagnostics = diagnostics
        self.disposition_recorded = disposition_recorded


class FilingParseTimeout(TimeoutError):
    """One filing exceeded the configured local parse deadline."""

    def __init__(self, seconds: float) -> None:
        super().__init__(f"filing parse exceeded {seconds:g} seconds")
        self.seconds = seconds


class _filing_parse_deadline:
    """Bound CPU-heavy local parsing without stopping the ticker loop."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._previous_handler = None

    def __enter__(self):
        if self.seconds <= 0:
            return self

        def timeout(_signum, _frame):
            raise FilingParseTimeout(self.seconds)

        self._previous_handler = signal.signal(signal.SIGALRM, timeout)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)
        return self

    def __exit__(self, _error_type, _error, _traceback):
        if self.seconds > 0:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._previous_handler)
        return False


def parser_modules_manifest() -> dict[str, str]:
    """Return stable content identities for every required parser module."""

    directory = Path(__file__).parent
    manifest = {
        name.removesuffix(".py"): hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in _MODULE_FILES
    }
    manifest["edgartools"] = installed_edgartools_version() or "unavailable"
    return manifest


def parser_modules_hash() -> str:
    """Return the exact module-set identity used by incremental selection."""

    encoded = json.dumps(
        parser_modules_manifest(), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _as_string(value: object | None) -> str | None:
    return None if value is None else str(value)


def _diagnostics(values: list[ParserDiagnostic] | tuple[ParserDiagnostic, ...]) -> list[dict]:
    return [value.as_dict() for value in values]


def _edgar_archive_base(cik: str, accession: str) -> str:
    normalized_cik = cik.lstrip("0") or "0"
    normalized_accession = accession.replace("-", "")
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{normalized_cik}/{normalized_accession}/"
    )


def _edgar_artifact_url(cik: str, accession: str, relative_path: str) -> str:
    name = PurePosixPath(relative_path).name
    return _edgar_archive_base(cik, accession) + quote(name)


def _run_for_filing(
    session: Session, local_filing: LocalFiling, settings: Settings
) -> tuple[ParseRun, bool]:
    run_id = session.info.get(_RUN_INFO_KEY)
    if run_id is not None:
        run = session.get(ParseRun, run_id)
        if run is None:
            raise RuntimeError(f"active parse run {run_id} does not exist")
        return run, False

    run = ParseRun(
        scope_type="filing",
        scope_value=local_filing.accession,
        parser_version=settings.parser_version,
        edgartools_version=settings.edgartools_version or installed_edgartools_version(),
        status="running",
        input_count=1,
        command_metadata={"force": False},
    )
    session.add(run)
    session.flush()
    return run, True


def _upsert_filing_metadata(
    session: Session, local_filing: LocalFiling
) -> tuple[Filing, dict[tuple[str, str], Artifact]]:
    cik = local_filing.accession[:10]
    issuer = session.scalar(select(Issuer).where(Issuer.cik == cik))
    if issuer is None:
        issuer = Issuer(
            cik=cik,
            name=str(
                local_filing.index_record.get("company_name")
                or local_filing.index_record.get("name")
                or local_filing.ticker
            ),
            ticker_hint=local_filing.ticker,
            source_metadata={"source": "filings_index.json"},
        )
        session.add(issuer)
        session.flush()
    elif issuer.ticker_hint is None:
        issuer.ticker_hint = local_filing.ticker

    filing = session.scalar(
        select(Filing).where(
            Filing.issuer_id == issuer.id,
            Filing.accession_number == local_filing.accession,
        )
    )
    primary_name = (
        local_filing.primary_document.name
        if local_filing.primary_document is not None
        else None
    )
    if filing is None:
        filing = Filing(
            issuer_id=issuer.id,
            accession_number=local_filing.accession,
            form=local_filing.form,
            is_amended=local_filing.is_amended,
            filing_date=local_filing.filing_date,
            report_date=local_filing.report_date,
            fiscal_year=local_filing.fiscal_year,
            fiscal_period=local_filing.fiscal_period,
            primary_document=primary_name,
            package_path=local_filing.package_path,
            sec_url=(
                _edgar_artifact_url(cik, local_filing.accession, primary_name)
                if primary_name is not None
                else _edgar_archive_base(cik, local_filing.accession)
            ),
            index_metadata=dict(local_filing.index_record),
        )
        session.add(filing)
        session.flush()
    elif filing.sec_url is None:
        filing.primary_document = filing.primary_document or primary_name
        filing.sec_url = (
            _edgar_artifact_url(cik, local_filing.accession, primary_name)
            if primary_name is not None
            else _edgar_archive_base(cik, local_filing.accession)
        )

    artifacts: dict[tuple[str, str], Artifact] = {}
    for source in local_filing.artifacts:
        sha256 = source.sha256 or "0" * 64
        artifact = session.scalar(
            select(Artifact).where(
                Artifact.filing_id == filing.id,
                Artifact.relative_path == source.relative_path,
                Artifact.sha256 == sha256,
            )
        )
        if artifact is None:
            artifact = Artifact(
                filing_id=filing.id,
                relative_path=source.relative_path,
                storage_uri=str(source.path),
                content_type=source.content_type,
                byte_size=source.byte_size,
                sha256=sha256,
                role=str(source.role),
                classification_status=str(source.status),
                diagnostics=(
                    {"sha256_unavailable": True} if source.sha256 is None else None
                ),
            )
            session.add(artifact)
            session.flush()
        artifacts[(source.relative_path, sha256)] = artifact
    return filing, artifacts


def _artifact_for_evidence(
    evidence: EvidenceDraft,
    artifacts: dict[tuple[str, str], Artifact],
) -> Artifact:
    if evidence.relative_path is not None and evidence.content_sha256 is not None:
        artifact = artifacts.get((evidence.relative_path, evidence.content_sha256))
        if artifact is not None:
            return artifact
    matches = [
        artifact
        for (relative_path, sha256), artifact in artifacts.items()
        if (evidence.relative_path is None or relative_path == evidence.relative_path)
        and (evidence.content_sha256 is None or sha256 == evidence.content_sha256)
    ]
    if len(matches) != 1:
        raise ValueError(
            "evidence does not resolve to exactly one persisted artifact: "
            f"path={evidence.relative_path!r} sha256={evidence.content_sha256!r}"
        )
    return matches[0]


def _persist_evidence(
    session: Session,
    filing: Filing,
    evidence: EvidenceDraft | None,
    artifacts: dict[tuple[str, str], Artifact],
) -> EvidenceLocator:
    if evidence is None:
        raise ValueError("every extracted row requires evidence")
    ambiguous = (
        evidence.relative_path is None
        and evidence.content_sha256 is None
        and (evidence.locator_value or "").endswith(";source=ambiguous")
    )
    artifact = None if ambiguous else _artifact_for_evidence(evidence, artifacts)
    locator = EvidenceLocator(
        filing_id=filing.id,
        artifact_id=artifact.id if artifact is not None else None,
        relative_path=evidence.relative_path,
        accession_url=(
            evidence.accession_url
            or (
                _edgar_artifact_url(
                    filing.accession_number[:10],
                    filing.accession_number,
                    artifact.relative_path,
                )
                if artifact is not None
                else None
            )
        ),
        locator_type=str(evidence.locator_type),
        locator_value=evidence.locator_value,
        content_sha256=evidence.content_sha256,
        excerpt=evidence.excerpt,
    )
    session.add(locator)
    session.flush()
    return locator


def _row_context(
    filing: Filing,
    run: ParseRun,
    result: FilingParse,
    evidence: EvidenceLocator,
    parser_version: str,
) -> dict[str, Any]:
    return {
        "source_filing_id": filing.id,
        "parse_run_id": run.id,
        "filing_parse_id": result.id,
        "evidence_locator_id": evidence.id,
        "parser_version": parser_version,
    }


def _persist_output(
    session: Session,
    output: ParserOutput,
    filing: Filing,
    run: ParseRun,
    result: FilingParse,
    artifacts: dict[tuple[str, str], Artifact],
    parser_version: str,
) -> None:
    for draft in output.facts:
        evidence = _persist_evidence(session, filing, draft.evidence, artifacts)
        session.add(
            XbrlFact(
                **_row_context(filing, run, result, evidence, parser_version),
                concept_namespace=draft.concept_namespace,
                concept=draft.concept,
                label=draft.label,
                value_numeric=draft.value_numeric,
                value_text=draft.value_text,
                unit=draft.unit,
                decimals=draft.decimals,
                start_date=draft.start_date,
                end_date=draft.end_date,
                period_type=_as_string(draft.period_type),
                dimensions=draft.dimensions,
                filed_at=filing.filing_date,
                form=filing.form,
                accession=filing.accession_number,
                extraction_method=draft.extraction_method,
            )
        )
    for draft in output.statements:
        evidence = _persist_evidence(session, filing, draft.evidence, artifacts)
        session.add(
            StatementLine(
                **_row_context(filing, run, result, evidence, parser_version),
                statement_type=draft.statement_type,
                section=draft.section,
                order_index=draft.order_index,
                depth=draft.depth,
                label=draft.label,
                concept=draft.concept,
                value_numeric=draft.value_numeric,
                value_text=draft.value_text,
                unit=draft.unit,
                start_date=draft.start_date,
                end_date=draft.end_date,
                period_type=_as_string(draft.period_type),
                dimensions=draft.dimensions,
            )
        )
    for draft in output.sections:
        evidence = _persist_evidence(session, filing, draft.evidence, artifacts)
        session.add(
            FilingSection(
                **_row_context(filing, run, result, evidence, parser_version),
                section_type=draft.section_type,
                heading=draft.heading,
                order_index=draft.order_index,
                text=draft.text,
                raw_fragment=draft.raw_fragment,
                raw_fragment_hash=draft.raw_fragment_hash,
                status=str(draft.status),
                diagnostics=_diagnostics(draft.diagnostics),
            )
        )
    for draft in output.tables:
        evidence = _persist_evidence(session, filing, draft.evidence, artifacts)
        session.add(
            ExtractedTable(
                **_row_context(filing, run, result, evidence, parser_version),
                table_type=str(draft.table_type),
                caption=draft.caption,
                order_index=draft.order_index,
                columns=list(draft.columns),
                rows=list(draft.rows),
                period_hints=draft.period_hints,
                raw_fragment=draft.raw_fragment,
                raw_fragment_hash=draft.raw_fragment_hash,
                extraction_method=draft.extraction_method,
                confidence=draft.confidence,
                status=str(draft.status),
                diagnostics=_diagnostics(draft.diagnostics),
            )
        )


def _overall_status(xbrl_output: ParserOutput, html_output: ParserOutput) -> str:
    statuses = {str(xbrl_output.status), str(html_output.status)}
    if statuses == {"success"}:
        return "success"
    if not xbrl_output.is_empty or not html_output.is_empty:
        return "partial"
    return "failed"


def _result_diagnostics(
    xbrl_output: ParserOutput, html_output: ParserOutput
) -> dict[str, Any]:
    return {
        "modules": {
            "edgartools_adapter": _diagnostics(xbrl_output.diagnostics),
            "html_parser": _diagnostics(html_output.diagnostics),
        },
        "counts": {
            "edgartools_adapter": xbrl_output.counts(),
            "html_parser": html_output.counts(),
        },
    }


def _activate_result(session: Session, result: FilingParse) -> None:
    session.execute(
        update(FilingParse)
        .where(
            FilingParse.filing_id == result.filing_id,
            FilingParse.parser_version == result.parser_version,
            FilingParse.id != result.id,
            FilingParse.is_current.is_(True),
        )
        .values(is_current=False)
    )
    result.is_current = True
    session.flush()


def _finish_owned_run(
    run: ParseRun, local_filing: LocalFiling, status: str, diagnostics: dict | None = None
) -> None:
    successful = status == "success"
    run.success_count = 1 if successful else 0
    run.failure_count = 0 if successful else 1
    run.status = "completed" if successful else "failed"
    run.checkpoint_accession = local_filing.accession
    run.error_summary = None if successful else {"errors": [diagnostics or {}]}
    run.finished_at = datetime.now(UTC)


def _record_parent_run_failure(
    run: ParseRun,
    local_filing: LocalFiling,
    status: str,
    diagnostics: dict[str, Any],
) -> None:
    """Durably account for a failed child attempt in its still-running parent."""

    summary = dict(run.error_summary or {})
    errors = list(summary.get("errors", []))
    errors.append(
        {
            "accession": local_filing.accession,
            "status": status,
            "diagnostics": diagnostics,
        }
    )
    run.failure_count += 1
    run.error_summary = {**summary, "errors": errors}
    run.checkpoint_accession = local_filing.accession


def _record_parent_run_success(run: ParseRun, local_filing: LocalFiling) -> None:
    """Atomically account for a committed filing result in its parent run."""

    run.success_count += 1
    run.checkpoint_accession = local_filing.accession


def _record_run_disposition(
    run: ParseRun,
    owns_run: bool,
    local_filing: LocalFiling,
    status: str,
    diagnostics: dict[str, Any] | None,
) -> None:
    if owns_run:
        _finish_owned_run(run, local_filing, status, diagnostics)
    elif status == "success":
        _record_parent_run_success(run, local_filing)
    else:
        _record_parent_run_failure(run, local_filing, status, diagnostics or {})


def _next_attempt_number(
    session: Session,
    filing: Filing,
    local_filing: LocalFiling,
    parser_version: str,
    modules_hash: str,
) -> int:
    latest = session.scalar(
        select(func.max(FilingParse.attempt_number)).where(
            FilingParse.filing_id == filing.id,
            FilingParse.artifact_set_hash == local_filing.artifact_set_hash,
            FilingParse.parser_version == parser_version,
            FilingParse.parser_modules_hash == modules_hash,
        )
    )
    return (latest or 0) + 1


def parse_one_filing(
    session: Session,
    local_filing: LocalFiling,
    settings: Settings,
    force: bool = False,
) -> FilingParse:
    """Parse and commit one filing, or atomically persist its failed attempt."""

    filing, artifacts = _upsert_filing_metadata(session, local_filing)
    modules = parser_modules_manifest()
    modules_hash = parser_modules_hash()
    identity = (
        FilingParse.filing_id == filing.id,
        FilingParse.artifact_set_hash == local_filing.artifact_set_hash,
        FilingParse.parser_version == settings.parser_version,
        FilingParse.parser_modules_hash == modules_hash,
    )
    successful = session.scalar(
        select(FilingParse)
        .where(*identity, FilingParse.status == "success")
        .order_by(FilingParse.attempt_number.desc())
        .limit(1)
    )
    if successful is not None and not force:
        run, owns_run = _run_for_filing(session, local_filing, settings)
        if not successful.is_current:
            _activate_result(session, successful)
        _record_run_disposition(run, owns_run, local_filing, "success", None)
        session.commit()
        return successful

    run, owns_run = _run_for_filing(session, local_filing, settings)
    run.command_metadata = {**(run.command_metadata or {}), "force": force}
    attempt_number = _next_attempt_number(
        session,
        filing,
        local_filing,
        settings.parser_version,
        modules_hash,
    )

    def new_result(status: str, diagnostics: dict[str, Any]) -> FilingParse:
        result = FilingParse(
            filing_id=filing.id,
            parse_run_id=run.id,
            artifact_set_hash=local_filing.artifact_set_hash,
            parser_version=settings.parser_version,
            parser_modules_hash=modules_hash,
            attempt_number=attempt_number,
            parser_modules=modules,
            edgartools_version=settings.edgartools_version or installed_edgartools_version(),
            status=status,
            is_current=False,
            diagnostics=diagnostics,
        )
        session.add(result)
        session.flush()
        return result

    try:
        with _filing_parse_deadline(settings.parse_timeout_seconds):
            xbrl_output = EdgarToolsAdapter(parser_version=settings.parser_version).parse(
                local_filing
            )
            if local_filing.primary_document is None:
                raise ValueError("filing has no primary document for HTML parsing")
            html_output = parse_html_document(
                local_filing.primary_document,
                local_filing,
                settings.parser_version,
            )
    except Exception as error:
        diagnostics = {
            "error_type": type(error).__name__,
            "detail": str(error),
            "retryable": True,
        }
        if isinstance(error, FilingParseTimeout):
            diagnostics["timeout_seconds"] = error.seconds
        if successful is not None:
            diagnostics["preserved_filing_parse_id"] = str(successful.id)
        result = new_result("failed", diagnostics)
        _record_run_disposition(
            run, owns_run, local_filing, result.status, result.diagnostics
        )
        session.commit()
        if isinstance(error, FilingParseTimeout) or (
            successful is not None and not owns_run
        ):
            raise ParseAttemptFailed(
                "failed",
                diagnostics,
                disposition_recorded=True,
            ) from error
        return result

    overall_status = _overall_status(xbrl_output, html_output)
    diagnostics = _result_diagnostics(xbrl_output, html_output)

    try:
        with session.begin_nested():
            result = FilingParse(
                filing_id=filing.id,
                parse_run_id=run.id,
                artifact_set_hash=local_filing.artifact_set_hash,
                parser_version=settings.parser_version,
                parser_modules_hash=modules_hash,
                attempt_number=attempt_number,
            )
            session.add(result)
            result.parser_modules = {
                **modules,
                "statuses": {
                    "edgartools_adapter": str(xbrl_output.status),
                    "html_parser": str(html_output.status),
                },
            }
            result.edgartools_version = (
                xbrl_output.edgartools_version
                or settings.edgartools_version
                or installed_edgartools_version()
            )
            result.parse_mode = "+".join(
                mode for mode in (xbrl_output.parse_mode, html_output.parse_mode) if mode
            )
            result.status = overall_status
            result.is_current = False
            result.diagnostics = diagnostics
            session.flush()
            _persist_output(
                session,
                xbrl_output,
                filing,
                run,
                result,
                artifacts,
                settings.parser_version,
            )
            _persist_output(
                session,
                html_output,
                filing,
                run,
                result,
                artifacts,
                settings.parser_version,
            )
            session.flush()
            if result.status == "success":
                _activate_result(session, result)
    except Exception as error:
        diagnostics = {
            "error_type": type(error).__name__,
            "detail": str(error),
            "retryable": True,
        }
        if successful is not None:
            diagnostics["preserved_filing_parse_id"] = str(successful.id)
        result = new_result("failed", diagnostics)

    _record_run_disposition(run, owns_run, local_filing, result.status, result.diagnostics)
    session.commit()
    if result.status != "success" and successful is not None and not owns_run:
        raise ParseAttemptFailed(
            result.status,
            result.diagnostics or {},
            disposition_recorded=True,
        )
    return result
