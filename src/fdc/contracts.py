"""Typed contracts shared by the archive scanner, parsers, and write path.

Nothing in this module imports SQLAlchemy or EdgarTools: the scanner and the
parsers exchange these dataclasses, and the persistence layer maps them onto
:mod:`fdc.models`.  Every extracted value keeps an :class:`EvidenceDraft`, so a
stored number can always be traced back to the artifact it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any


class ArtifactRole(StrEnum):
    """Allowed ``artifact.role`` values; mirrors ``fdc.models.ARTIFACT_ROLES``."""

    PRIMARY = "primary"
    XBRL = "xbrl"
    EXHIBIT = "exhibit"
    IMAGE = "image"
    TEXT = "text"
    UNKNOWN = "unknown"


class ArtifactStatus(StrEnum):
    """Allowed ``artifact.classification_status`` values."""

    INDEXED = "indexed"
    SKIPPED = "skipped"
    UNREADABLE = "unreadable"


class DiagnosticCode(StrEnum):
    """Stable diagnostic codes; missing input is never silently omitted."""

    MISSING_INDEX = "MISSING_INDEX"
    MALFORMED_INDEX = "MALFORMED_INDEX"
    INVALID_INDEX_RECORD = "INVALID_INDEX_RECORD"
    INVALID_ACCESSION = "INVALID_ACCESSION"
    UNSUPPORTED_FORM = "UNSUPPORTED_FORM"
    PACKAGE_MISSING = "PACKAGE_MISSING"
    PACKAGE_EMPTY = "PACKAGE_EMPTY"
    PRIMARY_MISSING = "PRIMARY_MISSING"
    UNREADABLE_ARTIFACT = "UNREADABLE_ARTIFACT"
    ARTIFACT_OUTSIDE_PACKAGE = "ARTIFACT_OUTSIDE_PACKAGE"
    EDGARTOOLS_UNAVAILABLE = "EDGARTOOLS_UNAVAILABLE"
    XBRL_UNAVAILABLE = "XBRL_UNAVAILABLE"
    STATEMENT_UNAVAILABLE = "STATEMENT_UNAVAILABLE"
    FACT_MALFORMED = "FACT_MALFORMED"
    RAW_XBRL_FALLBACK = "RAW_XBRL_FALLBACK"


class DiagnosticSeverity(StrEnum):
    """Severity attached to a gap or parser diagnostic."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


#: Codes that make the whole scan unusable for parsing.
FATAL_DIAGNOSTIC_CODES = frozenset({DiagnosticCode.MISSING_INDEX, DiagnosticCode.MALFORMED_INDEX})


class LocatorType(StrEnum):
    """Allowed ``evidence_locator.locator_type`` values."""

    HTML_ID = "html_id"
    HEADING = "heading"
    LINE_RANGE = "line_range"
    XBRL_FACT = "xbrl_fact"
    TABLE_CELL = "table_cell"
    SNIPPET = "snippet"


class ParseStatus(StrEnum):
    """Allowed ``filing_parse.status`` values."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class RowStatus(StrEnum):
    """Allowed ``filing_section``/``extracted_table`` status values."""

    PARSED = "parsed"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class PeriodType(StrEnum):
    """Allowed ``xbrl_fact.period_type`` values."""

    INSTANT = "instant"
    QUARTER = "quarter"
    ANNUAL = "annual"
    YTD = "ytd"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """One file inside a local filing package, with its content identity."""

    relative_path: str
    """Path relative to the ticker directory, POSIX separators."""

    path: Path
    """Absolute path on disk."""

    byte_size: int
    sha256: str | None
    """Content hash, or ``None`` when the file could not be read."""

    role: ArtifactRole
    content_type: str
    status: ArtifactStatus
    parse_eligible: bool
    diagnostics: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly view used by the scan CLI and parse runs."""

        return {
            "relative_path": self.relative_path,
            "role": str(self.role),
            "content_type": self.content_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "status": str(self.status),
            "parse_eligible": self.parse_eligible,
        }


@dataclass(frozen=True, slots=True)
class ParserDiagnostic:
    """One scoped, non-fatal scanner or parser diagnostic."""

    code: DiagnosticCode | str
    detail: str
    scope: str | None = None
    relative_path: str | None = None
    severity: DiagnosticSeverity = DiagnosticSeverity.WARNING

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": str(self.code),
            "detail": self.detail,
            "severity": str(self.severity),
            "scope": self.scope,
            "relative_path": self.relative_path,
        }


@dataclass(frozen=True, slots=True)
class LocalFiling:
    """One eligible local filing package resolved from ``filings_index.json``."""

    ticker: str
    form: str
    accession: str
    is_amended: bool
    filing_date: date | None
    report_date: date | None
    fiscal_year: int | None
    fiscal_period: str | None
    package_path: str
    """Package directory relative to the ticker directory."""

    package_dir: Path
    primary_relative_path: str | None
    primary_document: Path | None
    artifacts: tuple[ArtifactRef, ...]
    artifact_set_hash: str
    index_record: dict[str, Any] = field(default_factory=dict)
    diagnostics: tuple[ParserDiagnostic, ...] = ()

    @property
    def primary_artifact(self) -> ArtifactRef | None:
        """The artifact promoted to :attr:`ArtifactRole.PRIMARY`, if any."""

        for artifact in self.artifacts:
            if artifact.role is ArtifactRole.PRIMARY:
                return artifact
        return None

    @property
    def parseable_artifacts(self) -> tuple[ArtifactRef, ...]:
        """Artifacts a parser may read; images and containers are excluded."""

        return tuple(artifact for artifact in self.artifacts if artifact.parse_eligible)

    @property
    def identity(self) -> tuple[str, str, str]:
        """``(ticker, accession, artifact_set_hash)`` for incremental planning."""

        return (self.ticker, self.accession, self.artifact_set_hash)

    def as_dict(self) -> dict[str, Any]:
        return {
            "form": self.form,
            "accession": self.accession,
            "is_amended": self.is_amended,
            "filing_date": self.filing_date.isoformat() if self.filing_date else None,
            "report_date": self.report_date.isoformat() if self.report_date else None,
            "package_path": self.package_path,
            "primary_document": self.primary_document.name if self.primary_document else None,
            "artifact_set_hash": self.artifact_set_hash,
            "artifact_count": len(self.artifacts),
            "parseable_artifact_count": len(self.parseable_artifacts),
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
        }


@dataclass(frozen=True, slots=True)
class ArchiveGap:
    """One explicit scan gap: missing input is reported, never skipped quietly."""

    code: DiagnosticCode
    detail: str
    ticker: str | None = None
    form: str | None = None
    accession: str | None = None
    path: str | None = None
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR

    @property
    def fatal(self) -> bool:
        """Whether this gap makes the whole scan unusable."""

        return self.code in FATAL_DIAGNOSTIC_CODES

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": str(self.code),
            "detail": self.detail,
            "severity": str(self.severity),
            "ticker": self.ticker,
            "form": self.form,
            "accession": self.accession,
            "path": self.path,
        }


@dataclass(slots=True)
class ArchiveScan:
    """Result of scanning one ticker archive; the unit of parsing work."""

    ticker: str
    sec_root: Path
    ticker_dir: Path
    index_path: Path
    forms: tuple[str, ...]
    filings: list[LocalFiling] = field(default_factory=list)
    gaps: list[ArchiveGap] = field(default_factory=list)
    skipped: list[ArchiveGap] = field(default_factory=list)
    index_metadata: dict[str, Any] = field(default_factory=dict)
    index_record_count: int = 0
    eligible_count: int = 0
    """Eligible filings found before ``limit`` was applied."""

    scanned_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def accessions(self) -> list[str]:
        """Accessions of eligible filings, in scan order."""

        return [filing.accession for filing in self.filings]

    @property
    def ok(self) -> bool:
        """False when a fatal gap (missing or malformed index) was recorded."""

        return not any(gap.fatal for gap in self.gaps)

    def summary(self) -> dict[str, Any]:
        """Serializable scan summary used by the CLI and parse runs."""

        return {
            "ticker": self.ticker,
            "sec_root": str(self.sec_root),
            "index_path": str(self.index_path),
            "forms": list(self.forms),
            "index_records": self.index_record_count,
            "filings_scanned": self.eligible_count,
            "artifact_count": sum(len(filing.artifacts) for filing in self.filings),
            "parseable_artifact_count": sum(
                len(filing.parseable_artifacts) for filing in self.filings
            ),
            "ok": self.ok,
            "scanned_at": self.scanned_at.isoformat(),
            "filings": [filing.as_dict() for filing in self.filings],
            "gaps": [gap.as_dict() for gap in self.gaps],
            "skipped": [gap.as_dict() for gap in self.skipped],
        }


@dataclass(frozen=True, slots=True)
class EvidenceDraft:
    """A locator from an extracted value back to its source artifact."""

    locator_type: LocatorType
    locator_value: str | None = None
    relative_path: str | None = None
    accession_url: str | None = None
    content_sha256: str | None = None
    excerpt: str | None = None


@dataclass(frozen=True, slots=True)
class FactDraft:
    """One normalized XBRL fact observation."""

    concept: str
    evidence: EvidenceDraft
    value_numeric: Decimal | None = None
    value_text: str | None = None
    label: str | None = None
    concept_namespace: str | None = None
    unit: str | None = None
    decimals: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    period_type: PeriodType | str | None = None
    dimensions: dict[str, Any] = field(default_factory=dict)
    extraction_method: str | None = None

    def __post_init__(self) -> None:
        if self.evidence is None:
            raise ValueError("FactDraft evidence is required")


@dataclass(frozen=True, slots=True)
class StatementDraft:
    """One normalized row of a primary financial statement."""

    statement_type: str
    order_index: int
    evidence: EvidenceDraft
    label: str | None = None
    section: str | None = None
    depth: int = 0
    concept: str | None = None
    value_numeric: Decimal | None = None
    value_text: str | None = None
    unit: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    period_type: PeriodType | str | None = None
    dimensions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.evidence is None:
            raise ValueError("StatementDraft evidence is required")


@dataclass(frozen=True, slots=True)
class SectionDraft:
    """One extracted narrative section."""

    section_type: str
    order_index: int
    heading: str | None = None
    text: str | None = None
    status: RowStatus | str = RowStatus.PARSED
    raw_fragment: str | None = None
    raw_fragment_hash: str | None = None
    diagnostics: tuple[ParserDiagnostic, ...] = ()
    evidence: EvidenceDraft | None = None


@dataclass(frozen=True, slots=True)
class TableDraft:
    """One detected table or typed disclosure block."""

    table_type: str
    order_index: int
    caption: str | None = None
    columns: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    period_hints: dict[str, Any] = field(default_factory=dict)
    extraction_method: str | None = None
    confidence: float | None = None
    status: RowStatus | str = RowStatus.PARSED
    raw_fragment: str | None = None
    raw_fragment_hash: str | None = None
    diagnostics: tuple[ParserDiagnostic, ...] = ()
    evidence: EvidenceDraft | None = None


@dataclass(slots=True)
class ParserOutput:
    """Everything one filing parse produced, independent of storage."""

    status: ParseStatus
    parser_version: str | None = None
    parse_mode: str | None = None
    edgartools_version: str | None = None
    facts: list[FactDraft] = field(default_factory=list)
    statements: list[StatementDraft] = field(default_factory=list)
    sections: list[SectionDraft] = field(default_factory=list)
    tables: list[TableDraft] = field(default_factory=list)
    evidence: list[EvidenceDraft] = field(default_factory=list)
    diagnostics: list[ParserDiagnostic] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Row counts per contract collection, used for parse-run bookkeeping."""

        return {
            "facts": len(self.facts),
            "statements": len(self.statements),
            "sections": len(self.sections),
            "tables": len(self.tables),
            "evidence": len(self.evidence),
            "diagnostics": len(self.diagnostics),
        }

    @property
    def is_empty(self) -> bool:
        """True when the parser produced no parsed row at all."""

        return not (self.facts or self.statements or self.sections or self.tables)
