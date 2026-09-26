"""Read models and query shaping for current filing parse results."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fdc.config import get_settings
from fdc.db import SessionLocal
from fdc.models import (
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


class ReadServiceError(RuntimeError):
    """A stable API-facing query failure with an explicit result state."""

    def __init__(
        self,
        status_code: int,
        status: str,
        message: str,
        diagnostics: dict[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.status = status
        self.message = message
        self.diagnostics = diagnostics if diagnostics is not None else {}

    def detail(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "diagnostics": self.diagnostics,
        }


class CompanyView(BaseModel):
    ticker: str
    name: str
    cik: str
    sic: str | None
    latest_filing_date: date | None
    latest_filing_status: str
    filing_count: int


class FilingSummaryView(BaseModel):
    accession: str
    form: str
    filing_date: date | None
    report_date: date | None
    status: str
    parser_version: str | None
    diagnostics: dict[str, Any] | list[Any] | None


class FilingListView(BaseModel):
    ticker: str
    form: str | None
    limit: int
    offset: int
    total: int
    filings: list[FilingSummaryView]


class ParseView(BaseModel):
    status: str
    parser_version: str | None
    parser_modules: dict[str, Any] | None
    edgartools_version: str | None
    parse_mode: str | None
    diagnostics: dict[str, Any] | list[Any] | None


class FilingView(BaseModel):
    accession: str
    ticker: str
    cik: str
    form: str
    is_amended: bool
    filing_date: date | None
    report_date: date | None
    fiscal_year: int | None
    fiscal_period: str | None
    primary_document: str | None
    sec_url: str | None
    parse: ParseView


class EvidenceView(BaseModel):
    evidence_id: str
    accession: str
    relative_path: str | None
    accession_url: str | None
    locator_type: str
    locator_value: str | None
    content_sha256: str | None
    excerpt: str | None


class FactItemView(BaseModel):
    concept_namespace: str | None
    concept: str
    label: str | None
    value_numeric: str | None
    value_text: str | None
    unit: str | None
    decimals: int | None
    start_date: date | None
    end_date: date | None
    period_type: str | None
    dimensions: dict[str, Any] | None
    extraction_method: str | None
    parser_version: str
    evidence: EvidenceView


class FactView(BaseModel):
    accession: str
    concept: str | None
    status: str
    parser_version: str
    facts: list[FactItemView]


class StatementLineView(BaseModel):
    order_index: int
    depth: int
    section: str | None
    label: str | None
    concept: str | None
    value_numeric: str | None
    value_text: str | None
    unit: str | None
    start_date: date | None
    end_date: date | None
    period_type: str | None
    dimensions: dict[str, Any] | None
    parser_version: str
    evidence: EvidenceView


class StatementView(BaseModel):
    accession: str
    statement_type: str
    status: str
    parser_version: str
    lines: list[StatementLineView]


class SectionView(BaseModel):
    accession: str
    section_type: str
    heading: str | None
    order_index: int
    text: str | None
    raw_fragment_hash: str | None
    status: str
    diagnostics: dict[str, Any] | list[Any] | None
    parser_version: str
    evidence: EvidenceView


class TableItemView(BaseModel):
    table_id: str
    table_type: str
    caption: str | None
    order_index: int
    columns: list[Any] | None
    rows: list[Any] | None
    period_hints: dict[str, Any] | None
    extraction_method: str | None
    confidence: float | None
    raw_fragment_hash: str | None
    status: str
    diagnostics: dict[str, Any] | list[Any] | None
    parser_version: str
    evidence: EvidenceView


class TableView(BaseModel):
    accession: str
    table_type: str | None
    status: str
    parser_version: str
    tables: list[TableItemView]


class ParseRunView(BaseModel):
    run_id: str
    scope_type: str
    scope_value: str | None
    parser_version: str
    edgartools_version: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    input_count: int
    success_count: int
    failure_count: int
    checkpoint_accession: str | None
    errors: list[Any] = Field(default_factory=list)
    command_metadata: dict[str, Any] | None


@contextmanager
def _session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _issuer(session: Session, ticker: str) -> Issuer:
    normalized = ticker.strip().upper()
    issuer = session.scalar(
        select(Issuer).where(func.upper(Issuer.ticker_hint) == normalized)
    )
    if issuer is None:
        raise ReadServiceError(404, "not_found", f"unknown ticker {normalized}")
    return issuer


def _filing(session: Session, accession: str) -> tuple[Filing, Issuer]:
    row = session.execute(
        select(Filing, Issuer)
        .join(Issuer, Issuer.id == Filing.issuer_id)
        .where(Filing.accession_number == accession)
    ).one_or_none()
    if row is None:
        raise ReadServiceError(404, "not_found", f"unknown accession {accession}")
    return row[0], row[1]


def _current_parse(session: Session, filing: Filing) -> FilingParse:
    parser_version = get_settings().parser_version
    current = session.scalar(
        select(FilingParse).where(
            FilingParse.filing_id == filing.id,
            FilingParse.parser_version == parser_version,
            FilingParse.status == "success",
            FilingParse.is_current.is_(True),
        )
    )
    if current is not None:
        return current
    latest = session.scalar(
        select(FilingParse)
        .where(
            FilingParse.filing_id == filing.id,
            FilingParse.parser_version == parser_version,
        )
        .order_by(FilingParse.created_at.desc())
        .limit(1)
    )
    if latest is None:
        raise ReadServiceError(
            409,
            "unavailable",
            f"accession {filing.accession_number} has no parse output",
            {"accession": filing.accession_number},
        )
    if latest.status == "failed":
        raise ReadServiceError(
            422,
            "failed",
            f"the latest parse for {filing.accession_number} failed",
            latest.diagnostics,
        )
    raise ReadServiceError(
        409,
        "unavailable",
        f"accession {filing.accession_number} has no current successful parse",
        {"parse_status": latest.status, "parse_diagnostics": latest.diagnostics},
    )


def _latest_parse(session: Session, filing_id: UUID) -> FilingParse | None:
    parser_version = get_settings().parser_version
    current = session.scalar(
        select(FilingParse).where(
            FilingParse.filing_id == filing_id,
            FilingParse.parser_version == parser_version,
            FilingParse.status == "success",
            FilingParse.is_current.is_(True),
        )
    )
    if current is not None:
        return current
    return session.scalar(
        select(FilingParse)
        .where(
            FilingParse.filing_id == filing_id,
            FilingParse.parser_version == parser_version,
        )
        .order_by(FilingParse.created_at.desc())
        .limit(1)
    )


def _summary(session: Session, filing: Filing) -> FilingSummaryView:
    result = _latest_parse(session, filing.id)
    return FilingSummaryView(
        accession=filing.accession_number,
        form=filing.form,
        filing_date=filing.filing_date,
        report_date=filing.report_date,
        status=result.status if result is not None else "unavailable",
        parser_version=result.parser_version if result is not None else None,
        diagnostics=result.diagnostics if result is not None else {"parse_result": "missing"},
    )


def _decimal(value: Decimal | float | None) -> str | None:
    return None if value is None else format(value, "f")


def _evidence(
    session: Session, filing: Filing, evidence_id: UUID
) -> EvidenceView:
    evidence = session.get(EvidenceLocator, evidence_id)
    if evidence is None or evidence.filing_id != filing.id:
        raise ReadServiceError(
            404,
            "not_found",
            f"unknown evidence {evidence_id} for {filing.accession_number}",
        )
    return EvidenceView(
        evidence_id=str(evidence.id),
        accession=filing.accession_number,
        relative_path=evidence.relative_path,
        accession_url=evidence.accession_url,
        locator_type=evidence.locator_type,
        locator_value=evidence.locator_value,
        content_sha256=evidence.content_sha256,
        excerpt=evidence.excerpt,
    )


def _unavailable(
    filing: Filing,
    result: FilingParse,
    output: str,
    selector: str | None,
) -> ReadServiceError:
    return ReadServiceError(
        409,
        "unavailable",
        f"{output} output is unavailable for {filing.accession_number}",
        {
            "accession": filing.accession_number,
            "output": output,
            "selector": selector,
            "parser_version": result.parser_version,
            "parse_diagnostics": result.diagnostics,
        },
    )


def get_company(ticker: str) -> CompanyView:
    with _session_scope() as session:
        issuer = _issuer(session, ticker)
        filings = session.scalars(
            select(Filing)
            .where(Filing.issuer_id == issuer.id)
            .order_by(Filing.filing_date.desc(), Filing.accession_number.desc())
        ).all()
        latest = filings[0] if filings else None
        latest_parse = _latest_parse(session, latest.id) if latest is not None else None
        return CompanyView(
            ticker=(issuer.ticker_hint or ticker).upper(),
            name=issuer.name,
            cik=issuer.cik,
            sic=issuer.sic,
            latest_filing_date=latest.filing_date if latest is not None else None,
            latest_filing_status=(
                latest_parse.status if latest_parse is not None else "unavailable"
            ),
            filing_count=len(filings),
        )


def list_filings(
    ticker: str,
    form: str | None,
    limit: int,
    offset: int,
) -> FilingListView:
    with _session_scope() as session:
        issuer = _issuer(session, ticker)
        predicates = [Filing.issuer_id == issuer.id]
        normalized_form = form.strip().upper() if form else None
        if normalized_form:
            predicates.append(Filing.form == normalized_form)
        total = session.scalar(select(func.count(Filing.id)).where(*predicates)) or 0
        filings = session.scalars(
            select(Filing)
            .where(*predicates)
            .order_by(Filing.filing_date.desc(), Filing.accession_number.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return FilingListView(
            ticker=(issuer.ticker_hint or ticker).upper(),
            form=normalized_form,
            limit=limit,
            offset=offset,
            total=total,
            filings=[_summary(session, filing) for filing in filings],
        )


def get_filing(accession: str) -> FilingView:
    with _session_scope() as session:
        filing, issuer = _filing(session, accession)
        result = _latest_parse(session, filing.id)
        parse = ParseView(
            status=result.status if result is not None else "unavailable",
            parser_version=result.parser_version if result is not None else None,
            parser_modules=result.parser_modules if result is not None else None,
            edgartools_version=result.edgartools_version if result is not None else None,
            parse_mode=result.parse_mode if result is not None else None,
            diagnostics=(
                result.diagnostics if result is not None else {"parse_result": "missing"}
            ),
        )
        return FilingView(
            accession=filing.accession_number,
            ticker=(issuer.ticker_hint or "").upper(),
            cik=issuer.cik,
            form=filing.form,
            is_amended=filing.is_amended,
            filing_date=filing.filing_date,
            report_date=filing.report_date,
            fiscal_year=filing.fiscal_year,
            fiscal_period=filing.fiscal_period,
            primary_document=filing.primary_document,
            sec_url=filing.sec_url,
            parse=parse,
        )


def get_statement(accession: str, statement_type: str) -> StatementView:
    with _session_scope() as session:
        filing, _issuer_row = _filing(session, accession)
        result = _current_parse(session, filing)
        normalized_type = statement_type.strip().lower()
        rows = session.scalars(
            select(StatementLine)
            .where(
                StatementLine.filing_parse_id == result.id,
                func.lower(StatementLine.statement_type) == normalized_type,
            )
            .order_by(StatementLine.order_index, StatementLine.id)
        ).all()
        if not rows:
            raise _unavailable(filing, result, "statement", normalized_type)
        return StatementView(
            accession=filing.accession_number,
            statement_type=normalized_type,
            status="success",
            parser_version=result.parser_version,
            lines=[
                StatementLineView(
                    order_index=row.order_index,
                    depth=row.depth,
                    section=row.section,
                    label=row.label,
                    concept=row.concept,
                    value_numeric=_decimal(row.value_numeric),
                    value_text=row.value_text,
                    unit=row.unit,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    period_type=row.period_type,
                    dimensions=row.dimensions,
                    parser_version=row.parser_version,
                    evidence=_evidence(session, filing, row.evidence_locator_id),
                )
                for row in rows
            ],
        )


def get_facts(accession: str, concept: str | None) -> FactView:
    with _session_scope() as session:
        filing, _issuer_row = _filing(session, accession)
        result = _current_parse(session, filing)
        predicates = [XbrlFact.filing_parse_id == result.id]
        if concept:
            predicates.append(func.lower(XbrlFact.concept) == concept.strip().lower())
        rows = session.scalars(
            select(XbrlFact)
            .where(*predicates)
            .order_by(XbrlFact.end_date.desc(), XbrlFact.concept, XbrlFact.id)
        ).all()
        if not rows:
            raise _unavailable(filing, result, "facts", concept)
        return FactView(
            accession=filing.accession_number,
            concept=concept,
            status="success",
            parser_version=result.parser_version,
            facts=[
                FactItemView(
                    concept_namespace=row.concept_namespace,
                    concept=row.concept,
                    label=row.label,
                    value_numeric=_decimal(row.value_numeric),
                    value_text=row.value_text,
                    unit=row.unit,
                    decimals=row.decimals,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    period_type=row.period_type,
                    dimensions=row.dimensions,
                    extraction_method=row.extraction_method,
                    parser_version=row.parser_version,
                    evidence=_evidence(session, filing, row.evidence_locator_id),
                )
                for row in rows
            ],
        )


def get_section(accession: str, section_type: str) -> SectionView:
    with _session_scope() as session:
        filing, _issuer_row = _filing(session, accession)
        result = _current_parse(session, filing)
        normalized_type = section_type.strip().lower()
        row = session.scalar(
            select(FilingSection).where(
                FilingSection.filing_parse_id == result.id,
                func.lower(FilingSection.section_type) == normalized_type,
            )
        )
        if row is None:
            raise _unavailable(filing, result, "section", normalized_type)
        if row.status == "failed":
            raise ReadServiceError(422, "failed", "section extraction failed", row.diagnostics)
        if row.status != "parsed":
            raise ReadServiceError(
                409, "unavailable", f"section is {row.status}", row.diagnostics
            )
        return SectionView(
            accession=filing.accession_number,
            section_type=row.section_type,
            heading=row.heading,
            order_index=row.order_index,
            text=row.text,
            raw_fragment_hash=row.raw_fragment_hash,
            status=row.status,
            diagnostics=row.diagnostics,
            parser_version=row.parser_version,
            evidence=_evidence(session, filing, row.evidence_locator_id),
        )


def get_tables(accession: str, table_type: str | None) -> TableView:
    with _session_scope() as session:
        filing, _issuer_row = _filing(session, accession)
        result = _current_parse(session, filing)
        predicates = [ExtractedTable.filing_parse_id == result.id]
        normalized_type = table_type.strip().lower() if table_type else None
        if normalized_type:
            predicates.append(func.lower(ExtractedTable.table_type) == normalized_type)
        rows = session.scalars(
            select(ExtractedTable)
            .where(*predicates)
            .order_by(ExtractedTable.order_index, ExtractedTable.id)
        ).all()
        if not rows:
            raise _unavailable(filing, result, "tables", normalized_type)
        failures = [row for row in rows if row.status == "failed"]
        parsed = [row for row in rows if row.status == "parsed"]
        if failures and not parsed:
            raise ReadServiceError(
                422, "failed", "table extraction failed", failures[0].diagnostics
            )
        if not parsed:
            raise ReadServiceError(
                409,
                "unavailable",
                "table extraction is unavailable",
                {"rows": [row.diagnostics for row in rows]},
            )
        return TableView(
            accession=filing.accession_number,
            table_type=normalized_type,
            status="success",
            parser_version=result.parser_version,
            tables=[
                TableItemView(
                    table_id=str(row.id),
                    table_type=row.table_type,
                    caption=row.caption,
                    order_index=row.order_index,
                    columns=row.columns,
                    rows=row.rows,
                    period_hints=row.period_hints,
                    extraction_method=row.extraction_method,
                    confidence=row.confidence,
                    raw_fragment_hash=row.raw_fragment_hash,
                    status=row.status,
                    diagnostics=row.diagnostics,
                    parser_version=row.parser_version,
                    evidence=_evidence(session, filing, row.evidence_locator_id),
                )
                for row in parsed
            ],
        )


def get_evidence(accession: str, evidence_id: str) -> EvidenceView:
    with _session_scope() as session:
        filing, _issuer_row = _filing(session, accession)
        result = _current_parse(session, filing)
        try:
            identifier = UUID(evidence_id)
        except ValueError as error:
            raise ReadServiceError(404, "not_found", f"invalid evidence {evidence_id}") from error
        referenced = any(
            session.scalar(
                select(model.id).where(
                    model.filing_parse_id == result.id,
                    model.evidence_locator_id == identifier,
                )
            )
            is not None
            for model in (XbrlFact, StatementLine, FilingSection, ExtractedTable)
        )
        if not referenced:
            raise ReadServiceError(
                404,
                "not_found",
                f"evidence {evidence_id} is not part of the current parse",
            )
        return _evidence(session, filing, identifier)


def get_parse_run(run_id: str) -> ParseRunView:
    try:
        identifier = UUID(run_id)
    except ValueError as error:
        raise ReadServiceError(404, "not_found", f"invalid parse run {run_id}") from error
    with _session_scope() as session:
        run = session.get(ParseRun, identifier)
        if run is None:
            raise ReadServiceError(404, "not_found", f"unknown parse run {run_id}")
        summary = run.error_summary or {}
        return ParseRunView(
            run_id=str(run.id),
            scope_type=run.scope_type,
            scope_value=run.scope_value,
            parser_version=run.parser_version,
            edgartools_version=run.edgartools_version,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            input_count=run.input_count,
            success_count=run.success_count,
            failure_count=run.failure_count,
            checkpoint_accession=run.checkpoint_accession,
            errors=list(summary.get("errors", [])),
            command_metadata=run.command_metadata,
        )
