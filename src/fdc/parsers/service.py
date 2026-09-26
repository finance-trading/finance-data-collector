"""Atomic persistence boundary for one locally archived SEC filing."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update
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

    def __init__(self, status: str, diagnostics: dict[str, Any]) -> None:
        super().__init__(diagnostics.get("detail") or f"parse attempt ended {status}")
        self.status = status
        self.diagnostics = diagnostics


def parser_modules_manifest() -> dict[str, str]:
    """Return stable content identities for every required parser module."""

    directory = Path(__file__).parent
    return {
        name.removesuffix(".py"): hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in _MODULE_FILES
    }


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
            primary_document=(
                local_filing.primary_document.name
                if local_filing.primary_document is not None
                else None
            ),
            package_path=local_filing.package_path,
            index_metadata=dict(local_filing.index_record),
        )
        session.add(filing)
        session.flush()

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
    artifact = _artifact_for_evidence(evidence, artifacts)
    locator = EvidenceLocator(
        filing_id=filing.id,
        artifact_id=artifact.id,
        relative_path=evidence.relative_path,
        accession_url=evidence.accession_url,
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


def _delete_result_children(session: Session, result: FilingParse) -> None:
    evidence_ids: list[Any] = []
    for model in (XbrlFact, StatementLine, FilingSection, ExtractedTable):
        evidence_ids.extend(
            session.scalars(
                select(model.evidence_locator_id).where(model.filing_parse_id == result.id)
            ).all()
        )
        session.execute(delete(model).where(model.filing_parse_id == result.id))
    if evidence_ids:
        session.execute(delete(EvidenceLocator).where(EvidenceLocator.id.in_(evidence_ids)))


def _overall_status(xbrl_output: ParserOutput, html_output: ParserOutput) -> str:
    statuses = {str(xbrl_output.status), str(html_output.status)}
    if statuses == {"success"}:
        return "success"
    if "failed" in statuses:
        return "failed"
    return "partial"


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
    existing = session.scalar(select(FilingParse).where(*identity))
    if existing is not None and existing.status == "success" and not force:
        if not existing.is_current:
            _activate_result(session, existing)
        session.commit()
        return existing

    run, owns_run = _run_for_filing(session, local_filing, settings)
    run.command_metadata = {**(run.command_metadata or {}), "force": force}

    try:
        xbrl_output = EdgarToolsAdapter(parser_version=settings.parser_version).parse(local_filing)
        if local_filing.primary_document is None:
            raise ValueError("filing has no primary document for HTML parsing")
        html_output = parse_html_document(
            local_filing.primary_document,
            local_filing,
            settings.parser_version,
        )
    except Exception as error:
        if existing is not None and existing.status == "success":
            diagnostics = {
                "error_type": type(error).__name__,
                "detail": str(error),
                "retryable": True,
                "preserved_filing_parse_id": str(existing.id),
            }
            if owns_run:
                _finish_owned_run(run, local_filing, "failed", diagnostics)
            session.commit()
            raise ParseAttemptFailed("failed", diagnostics) from error

        session.rollback()
        run, owns_run = _run_for_filing(session, local_filing, settings)
        filing, _artifacts = _upsert_filing_metadata(session, local_filing)
        identity = (
            FilingParse.filing_id == filing.id,
            FilingParse.artifact_set_hash == local_filing.artifact_set_hash,
            FilingParse.parser_version == settings.parser_version,
            FilingParse.parser_modules_hash == modules_hash,
        )
        existing = session.scalar(select(FilingParse).where(*identity))
        result = existing or FilingParse(
            filing_id=filing.id,
            parse_run_id=run.id,
            artifact_set_hash=local_filing.artifact_set_hash,
            parser_version=settings.parser_version,
            parser_modules_hash=modules_hash,
        )
        result.parse_run_id = run.id
        result.parser_modules = modules
        result.edgartools_version = settings.edgartools_version or installed_edgartools_version()
        result.status = "failed"
        result.is_current = False
        result.diagnostics = {
            "error_type": type(error).__name__,
            "detail": str(error),
            "retryable": True,
        }
        session.add(result)
        if owns_run:
            _finish_owned_run(run, local_filing, result.status, result.diagnostics)
        session.commit()
        return result

    overall_status = _overall_status(xbrl_output, html_output)
    diagnostics = _result_diagnostics(xbrl_output, html_output)

    if existing is not None and existing.status == "success":
        if overall_status == "success":
            if not existing.is_current:
                _activate_result(session, existing)
            if owns_run:
                _finish_owned_run(run, local_filing, "success")
            session.commit()
            return existing

        attempt_diagnostics = {
            "detail": f"required parser modules ended {overall_status}",
            "module_statuses": {
                "edgartools_adapter": str(xbrl_output.status),
                "html_parser": str(html_output.status),
            },
            "modules": diagnostics["modules"],
            "preserved_filing_parse_id": str(existing.id),
            "retryable": True,
        }
        if owns_run:
            _finish_owned_run(run, local_filing, overall_status, attempt_diagnostics)
        session.commit()
        raise ParseAttemptFailed(overall_status, attempt_diagnostics)

    try:
        with session.begin_nested():
            if existing is not None:
                _delete_result_children(session, existing)
                result = existing
                result.parse_run_id = run.id
            else:
                result = FilingParse(
                    filing_id=filing.id,
                    parse_run_id=run.id,
                    artifact_set_hash=local_filing.artifact_set_hash,
                    parser_version=settings.parser_version,
                    parser_modules_hash=modules_hash,
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
        session.rollback()
        run, owns_run = _run_for_filing(session, local_filing, settings)
        filing, _artifacts = _upsert_filing_metadata(session, local_filing)
        existing = session.scalar(select(FilingParse).where(*identity))
        result = existing or FilingParse(
            filing_id=filing.id,
            parse_run_id=run.id,
            artifact_set_hash=local_filing.artifact_set_hash,
            parser_version=settings.parser_version,
            parser_modules_hash=modules_hash,
        )
        result.parse_run_id = run.id
        result.parser_modules = modules
        result.edgartools_version = settings.edgartools_version or installed_edgartools_version()
        result.status = "failed"
        result.is_current = False
        result.diagnostics = {
            "error_type": type(error).__name__,
            "detail": str(error),
            "retryable": True,
        }
        session.add(result)

    if owns_run:
        _finish_owned_run(run, local_filing, result.status, result.diagnostics)
    session.commit()
    return result
