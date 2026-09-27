"""Versioned SQLAlchemy models for the SEC filing parsing platform.

Only the CLI/worker write path produces these rows; readers resolve the
``current`` parse result per filing.  Every extracted value keeps its filing,
parse run, parser version and evidence locator, so no derived number is ever
detached from the artifact it came from.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: Allowed ``parse_run.status`` values.
RUN_STATUSES = ("queued", "running", "completed", "partial", "failed", "cancelled")

#: Allowed ``filing_parse.status`` values.
PARSE_STATUSES = ("success", "partial", "failed")

#: Allowed ``artifact.role`` values.
ARTIFACT_ROLES = ("primary", "xbrl", "exhibit", "image", "text", "unknown")

#: Allowed ``evidence_locator.locator_type`` values.
LOCATOR_TYPES = (
    "html_id",
    "heading",
    "line_range",
    "xbrl_fact",
    "table_cell",
    "snippet",
)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC timestamp that also round-trips on SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware UTC values")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class ExactNumeric(TypeDecorator[Decimal]):
    """Exact decimal storage: PostgreSQL NUMERIC and text-backed SQLite."""

    impl = Numeric(100, 30)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(132))
        return dialect.type_descriptor(Numeric(100, 30))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        return format(decimal_value, "f") if dialect.name == "sqlite" else decimal_value

    def process_result_value(self, value, dialect) -> Decimal | None:
        if value is None:
            return None
        return value if isinstance(value, Decimal) else Decimal(str(value))

def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base with stable constraint names for migrations."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Creation/update timestamps shared by every parser row."""

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=_now, onupdate=_now, nullable=False
    )


class Issuer(TimestampMixin, Base):
    """One SEC reporting issuer per normalized CIK."""

    __tablename__ = "issuer"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ticker_hint: Mapped[str | None] = mapped_column(String(16))
    sic: Mapped[str | None] = mapped_column(String(8))
    exchange_hint: Mapped[str | None] = mapped_column(String(32))
    source_metadata: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("cik", name="uq_issuer_cik"),
        Index("ix_issuer_ticker_hint", "ticker_hint"),
    )


class Filing(TimestampMixin, Base):
    """One logical SEC submission per ``(issuer_id, accession_number)``."""

    __tablename__ = "filing"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    issuer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("issuer.id", ondelete="CASCADE"), nullable=False
    )
    accession_number: Mapped[str] = mapped_column(String(32), nullable=False)
    form: Mapped[str] = mapped_column(String(16), nullable=False)
    is_amended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    filing_date: Mapped[date | None] = mapped_column(Date)
    report_date: Mapped[date | None] = mapped_column(Date)
    accepted_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_period: Mapped[str | None] = mapped_column(String(8))
    primary_document: Mapped[str | None] = mapped_column(String(255))
    package_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sec_url: Mapped[str | None] = mapped_column(String(512))
    index_metadata: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("issuer_id", "accession_number", name="uq_filing_issuer_accession"),
        Index("ix_filing_accession_number", "accession_number"),
        Index("ix_filing_issuer_id_filing_date_form", "issuer_id", "filing_date", "form"),
    )


class Artifact(TimestampMixin, Base):
    """One file in a filing package, identified by path and content hash."""

    __tablename__ = "artifact"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filing.id", ondelete="CASCADE"), nullable=False
    )
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_uri: Mapped[str | None] = mapped_column(String(1024))
    content_type: Mapped[str | None] = mapped_column(String(128))
    byte_size: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    classification_status: Mapped[str | None] = mapped_column(String(32))
    diagnostics: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("id", "filing_id", name="uq_artifact_id_filing"),
        UniqueConstraint("filing_id", "relative_path", "sha256", name="uq_artifact_filing_path"),
        CheckConstraint(
            "role IN ('primary', 'xbrl', 'exhibit', 'image', 'text', 'unknown')",
            name="role",
        ),
        Index("ix_artifact_sha256", "sha256"),
    )


class EvidenceLocator(TimestampMixin, Base):
    """A pointer from an extracted value back to its source artifact."""

    __tablename__ = "evidence_locator"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filing.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    relative_path: Mapped[str | None] = mapped_column(String(512))
    accession_url: Mapped[str | None] = mapped_column(String(512))
    locator_type: Mapped[str] = mapped_column(String(16), nullable=False)
    locator_value: Mapped[str | None] = mapped_column(String(1024))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    excerpt: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("id", "filing_id", name="uq_evidence_locator_id_filing"),
        ForeignKeyConstraint(
            ["artifact_id", "filing_id"],
            ["artifact.id", "artifact.filing_id"],
            name="fk_evidence_locator_artifact_filing",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "locator_type IN ('html_id', 'heading', 'line_range', 'xbrl_fact',"
            " 'table_cell', 'snippet')",
            name="locator_type",
        ),
        Index("ix_evidence_locator_filing_id_locator_type", "filing_id", "locator_type"),
    )


class ParseRun(TimestampMixin, Base):
    """One attempt to parse one or more filings."""

    __tablename__ = "parse_run"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_value: Mapped[str | None] = mapped_column(String(255))
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    edgartools_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    input_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checkpoint_accession: Mapped[str | None] = mapped_column(String(32))
    error_summary: Mapped[dict | None] = mapped_column(JSON)
    command_metadata: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancelled')",
            name="status",
        ),
        Index("ix_parse_run_status_started_at", "status", "started_at"),
        Index("ix_parse_run_scope_type_scope_value", "scope_type", "scope_value"),
    )


class FilingParse(TimestampMixin, Base):
    """One versioned parse result state for a filing."""

    __tablename__ = "filing_parse"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filing.id", ondelete="CASCADE"), nullable=False
    )
    parse_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("parse_run.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_modules_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parser_modules: Mapped[dict | None] = mapped_column(JSON)
    edgartools_version: Mapped[str | None] = mapped_column(String(32))
    parse_mode: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    diagnostics: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        UniqueConstraint("id", "filing_id", name="uq_filing_parse_id_filing"),
        UniqueConstraint(
            "filing_id",
            "artifact_set_hash",
            "parser_version",
            "parser_modules_hash",
            "attempt_number",
            name="uq_filing_parse_identity",
        ),
        CheckConstraint(
            "status IN ('success', 'partial', 'failed')",
            name="status",
        ),
        CheckConstraint(
            "NOT is_current OR status = 'success'",
            name="current_success",
        ),
        Index(
            "uq_filing_parse_current",
            "filing_id",
            "parser_version",
            unique=True,
            sqlite_where=text("is_current AND status = 'success'"),
            postgresql_where=text("is_current AND status = 'success'"),
        ),
        Index("ix_filing_parse_status", "status"),
    )


class XbrlFact(TimestampMixin, Base):
    """One normalized XBRL fact observation emitted by the standard adapter."""

    __tablename__ = "xbrl_fact"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_filing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filing.id", ondelete="CASCADE"), nullable=False
    )
    parse_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("parse_run.id", ondelete="RESTRICT"), nullable=False
    )
    filing_parse_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_locator_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    concept_namespace: Mapped[str | None] = mapped_column(String(64))
    concept: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str | None] = mapped_column(String(512))
    value_numeric: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(32))
    decimals: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    period_type: Mapped[str | None] = mapped_column(String(16))
    dimensions: Mapped[dict | None] = mapped_column(JSON)
    filed_at: Mapped[date | None] = mapped_column(Date)
    form: Mapped[str | None] = mapped_column(String(16))
    accession: Mapped[str | None] = mapped_column(String(32))
    extraction_method: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        ForeignKeyConstraint(
            ["filing_parse_id", "source_filing_id"],
            ["filing_parse.id", "filing_parse.filing_id"],
            name="fk_xbrl_fact_parse_filing",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["evidence_locator_id", "source_filing_id"],
            ["evidence_locator.id", "evidence_locator.filing_id"],
            name="fk_xbrl_fact_evidence_filing",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "period_type IN ('instant', 'quarter', 'annual', 'ytd', 'other')",
            name="period_type",
        ),
        Index("ix_xbrl_fact_concept_namespace_concept", "concept_namespace", "concept"),
        Index("ix_xbrl_fact_concept_end_date", "concept", "end_date"),
        Index("ix_xbrl_fact_filing_parse_id", "filing_parse_id"),
    )


class StatementLine(TimestampMixin, Base):
    """A normalized presentation row from a primary financial statement."""

    __tablename__ = "statement_line"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_filing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filing.id", ondelete="CASCADE"), nullable=False
    )
    parse_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("parse_run.id", ondelete="RESTRICT"), nullable=False
    )
    filing_parse_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_locator_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    statement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    section: Mapped[str | None] = mapped_column(String(255))
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    label: Mapped[str | None] = mapped_column(String(512))
    concept: Mapped[str | None] = mapped_column(String(255))
    value_numeric: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(32))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    period_type: Mapped[str | None] = mapped_column(String(16))
    dimensions: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        ForeignKeyConstraint(
            ["filing_parse_id", "source_filing_id"],
            ["filing_parse.id", "filing_parse.filing_id"],
            name="fk_statement_line_parse_filing",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["evidence_locator_id", "source_filing_id"],
            ["evidence_locator.id", "evidence_locator.filing_id"],
            name="fk_statement_line_evidence_filing",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_statement_line_filing_type_order",
            "source_filing_id",
            "statement_type",
            "order_index",
        ),
    )


class FilingSection(TimestampMixin, Base):
    """An extracted narrative section of a filing."""

    __tablename__ = "filing_section"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_filing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filing.id", ondelete="CASCADE"), nullable=False
    )
    parse_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("parse_run.id", ondelete="RESTRICT"), nullable=False
    )
    filing_parse_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_locator_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    section_type: Mapped[str] = mapped_column(String(32), nullable=False)
    heading: Mapped[str | None] = mapped_column(String(512))
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    raw_fragment: Mapped[str | None] = mapped_column(Text)
    raw_fragment_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    diagnostics: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        ForeignKeyConstraint(
            ["filing_parse_id", "source_filing_id"],
            ["filing_parse.id", "filing_parse.filing_id"],
            name="fk_filing_section_parse_filing",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["evidence_locator_id", "source_filing_id"],
            ["evidence_locator.id", "evidence_locator.filing_id"],
            name="fk_filing_section_evidence_filing",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('parsed', 'unsupported', 'unavailable', 'failed')",
            name="status",
        ),
        UniqueConstraint(
            "source_filing_id",
            "filing_parse_id",
            "section_type",
            name="uq_filing_section_filing_type",
        ),
        Index(
            "ix_filing_section_filing_id_section_type",
            "source_filing_id",
            "section_type",
        ),
    )


class ExtractedTable(TimestampMixin, Base):
    """One detected table or disclosure block."""

    __tablename__ = "extracted_table"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_filing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("filing.id", ondelete="CASCADE"), nullable=False
    )
    parse_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("parse_run.id", ondelete="RESTRICT"), nullable=False
    )
    filing_parse_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_locator_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    table_type: Mapped[str] = mapped_column(String(32), nullable=False)
    caption: Mapped[str | None] = mapped_column(String(512))
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    columns: Mapped[list | None] = mapped_column(JSON)
    rows: Mapped[list | None] = mapped_column(JSON)
    period_hints: Mapped[dict | None] = mapped_column(JSON)
    raw_fragment: Mapped[str | None] = mapped_column(Text)
    raw_fragment_hash: Mapped[str | None] = mapped_column(String(64))
    extraction_method: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    diagnostics: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (
        ForeignKeyConstraint(
            ["filing_parse_id", "source_filing_id"],
            ["filing_parse.id", "filing_parse.filing_id"],
            name="fk_extracted_table_parse_filing",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["evidence_locator_id", "source_filing_id"],
            ["evidence_locator.id", "evidence_locator.filing_id"],
            name="fk_extracted_table_evidence_filing",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('parsed', 'unsupported', 'unavailable', 'failed')",
            name="status",
        ),
        Index(
            "ix_extracted_table_filing_id_table_type",
            "source_filing_id",
            "table_type",
        ),
        Index("ix_extracted_table_filing_parse_id", "filing_parse_id"),
    )


def create_all_for_tests(engine) -> None:
    """Create the schema directly from metadata for SQLite test databases.

    Production databases are created by Alembic; this helper exists so unit
    tests do not depend on migration state.
    """

    Base.metadata.create_all(engine)
