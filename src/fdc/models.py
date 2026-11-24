"""Versioned SQLAlchemy models for the SEC filing parsing platform.

Parser rows are written by the CLI/worker; research annotations are written by
the local API. Readers resolve the ``current`` parse result per filing. Every
extracted value keeps its filing, parse run, parser version and evidence locator,
so no derived number is ever detached from its source artifact.
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


class NewsItem(Base):
    """One deduplicated item collected from a public news feed."""

    __tablename__ = "news_item"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    collected_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        Index("ix_news_item_published_at", "published_at"),
    )


class MarketQuote(Base):
    """Latest close and short history for one broad-market index."""

    __tablename__ = "market_quote"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)


class LatestQuote(Base):
    __tablename__ = "latest_quote"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)


class QuoteMetadata(Base):
    __tablename__ = "quote_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class CompanyQualitySnapshot(Base):
    """Unique reservation for one atomic scoring run."""

    __tablename__ = "company_quality_snapshot"

    snapshot_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)


class CompanyQualityScore(Base):
    """One immutable result for a company in a quality scoring run."""

    __tablename__ = "company_quality_score"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    cik: Mapped[str | None] = mapped_column(String(10))
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(128))
    rating_cutoff: Mapped[date] = mapped_column(Date, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_policy: Mapped[str] = mapped_column(String(128), nullable=False)
    source_facts_sha256: Mapped[str | None] = mapped_column(String(64))
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    score_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    dimension_count: Mapped[int | None] = mapped_column(Integer)
    peer_count: Mapped[int | None] = mapped_column(Integer)
    period_ends: Mapped[list | None] = mapped_column(JSON)
    revenue_growth_dimension: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    operating_margin_dimension: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    cash_conversion_dimension: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    capital_efficiency_dimension: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    financial_strength_dimension: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    unknown_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    v2_hard_status: Mapped[str | None] = mapped_column(String(32))
    v2_unknown_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    v2_hard_gate_count: Mapped[int | None] = mapped_column(Integer)
    v2_hard_gate_total: Mapped[int | None] = mapped_column(Integer)
    v2_net_debt_ebitda: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    v2_interest_coverage: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    v2_cumulative_net_income: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    v2_cumulative_cfo: Mapped[Decimal | None] = mapped_column(Numeric(30, 6))
    v2_positive_operating_income_years: Mapped[int | None] = mapped_column(Integer)
    v2_positive_cfo_years: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("snapshot_id", "ticker", name="uq_company_quality_score_snapshot_id_ticker"),
        Index("ix_company_quality_score_ticker_calculated_at", "ticker", "calculated_at"),
        Index("ix_company_quality_score_snapshot_id", "snapshot_id"),
    )


class AnalystOpinion(Base):
    """Latest per-firm sell-side analyst actions for a ticker."""

    __tablename__ = "analyst_opinion"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    firm: Mapped[str] = mapped_column(String(128), nullable=False)
    action_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    action: Mapped[str | None] = mapped_column(String(16))
    from_grade: Mapped[str | None] = mapped_column(String(32))
    to_grade: Mapped[str | None] = mapped_column(String(32))
    price_target_action: Mapped[str | None] = mapped_column(String(32))
    price_target: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    prior_price_target: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="yahoo_upgrade_downgrade")
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("ticker", "firm", "action_at", name="uq_analyst_opinion_ticker_firm_action_at"),
        Index("ix_analyst_opinion_ticker_action_at", "ticker", "action_at"),
    )


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
    locator_value: Mapped[str | None] = mapped_column(Text)
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
        Index("ix_filing_parse_parse_run_id", "parse_run_id"),
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
    unit: Mapped[str | None] = mapped_column(Text)
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
        Index("ix_xbrl_fact_evidence_filing", "evidence_locator_id", "source_filing_id"),
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
    unit: Mapped[str | None] = mapped_column(Text)
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
        Index("ix_statement_line_filing_parse_id", "filing_parse_id"),
        Index("ix_statement_line_parse_run_id", "parse_run_id"),
        Index("ix_statement_line_evidence_filing", "evidence_locator_id", "source_filing_id"),
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
        Index("ix_filing_section_parse_run_id", "parse_run_id"),
        Index("ix_filing_section_evidence_filing", "evidence_locator_id", "source_filing_id"),
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
    caption: Mapped[str | None] = mapped_column(Text)
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
        Index("ix_extracted_table_evidence_filing", "evidence_locator_id", "source_filing_id"),
    )


def create_all_for_tests(engine) -> None:
    """Create the schema directly from metadata for SQLite test databases.

    Production databases are created by Alembic; this helper exists so unit
    tests do not depend on migration state.
    """

    Base.metadata.create_all(engine)


class ResearchAnnotation(TimestampMixin, Base):
    """One company's editable research annotations, written only by the local
    read/write API — never by the parser.

    Holds the per-company price-action bands (observe / entry / add / reduce,
    each a low–high range) and the ongoing watch items the reader wants to keep
    in front of them.  A row is created on first edit; until then the directory
    falls back to tier-derived default watch items and blank bands, so missing
    data stays explicit rather than invented.
    """

    __tablename__ = "research_annotation"

    ticker: Mapped[str] = mapped_column(String(8), primary_key=True)
    observe_low: Mapped[float | None] = mapped_column(Float)
    observe_high: Mapped[float | None] = mapped_column(Float)
    entry_low: Mapped[float | None] = mapped_column(Float)
    entry_high: Mapped[float | None] = mapped_column(Float)
    add_low: Mapped[float | None] = mapped_column(Float)
    add_high: Mapped[float | None] = mapped_column(Float)
    reduce_low: Mapped[float | None] = mapped_column(Float)
    reduce_high: Mapped[float | None] = mapped_column(Float)
    #: Model-derived forward value per share (USD); a research cross-check, not a
    #: confirmed price.  Null when the company has no valuation batch yet.
    intrinsic_value: Mapped[float | None] = mapped_column(Float)
    #: Three-scenario forward prices per share (Bear/Base/Bull, USD); null when
    #: no valuation batch has been saved for the company.
    scen_bear: Mapped[float | None] = mapped_column(Float)
    scen_base: Mapped[float | None] = mapped_column(Float)
    scen_bull: Mapped[float | None] = mapped_column(Float)
    #: ``[{"text": ..., "priority": 1..3}, ...]``; color is derived from priority.
    watch_items: Mapped[list] = mapped_column(JSON, default=list, nullable=False)


class AiLayer(Base):
    """One value-chain layer of the curated AI company catalog.

    Migrated from ``data/ai_companies.json`` (``layers``); the file remains the
    import source and rollback baseline, the table is the runtime source of
    truth once populated.
    """

    __tablename__ = "ai_layer"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    name_en: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class AiSegment(Base):
    """One named segment declared by a layer."""

    __tablename__ = "ai_segment"

    layer_id: Mapped[str] = mapped_column(
        ForeignKey("ai_layer.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class AiCompany(Base):
    """One curated AI company; ``layer_id`` + ``segment`` must reference a
    declared segment of that layer (composite FK to ``ai_segment``)."""

    __tablename__ = "ai_company"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector: Mapped[str] = mapped_column(String(128), nullable=False)
    industry: Mapped[str] = mapped_column(String(128), nullable=False)
    layer_id: Mapped[str] = mapped_column(
        ForeignKey("ai_layer.id", ondelete="RESTRICT"), nullable=False
    )
    segment: Mapped[str] = mapped_column(String(128), nullable=False)
    also_in: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["layer_id", "segment"],
            ["ai_segment.layer_id", "ai_segment.name"],
            name="fk_ai_company_layer_id_segment_ai_segment",
        ),
        Index("ix_ai_company_layer_id", "layer_id"),
    )


class FunnelOverride(Base):
    """One manual funnel-tier override, migrated from
    ``config/funnel_overrides.json``.  ``tier`` 1 = core, 2 = key, 3 = watch."""

    __tablename__ = "funnel_override"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    __table_args__ = (
        CheckConstraint("tier in (1, 2, 3)", name="ck_funnel_override_tier_in_1_2_3"),
    )


class QualityInputBatch(Base):
    """Provenance row for one imported quality-scoring input file.

    ``id`` is stable per (kind, source file) so re-imports of the same source
    replace the batch wholesale instead of accumulating duplicates.
    """

    __tablename__ = "quality_input_batch"

    id: Mapped[str] = mapped_column(String(512), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rating_cutoff: Mapped[date | None] = mapped_column(Date)
    rule_version: Mapped[str | None] = mapped_column(String(64))
    semantic_policy: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint("kind", "source", "sha256", name="uq_quality_input_batch_kind_source_sha256"),
    )


class QualityAnnualFact(Base):
    """One annual XBRL fact row (migrated from the checked-in edgartools
    annual-facts CSV), referenced by its import batch."""

    __tablename__ = "quality_annual_fact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("quality_input_batch.id", ondelete="CASCADE"), nullable=False
    )
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    concept: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str | None] = mapped_column(String(512))
    value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    numeric_value: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    unit: Mapped[str | None] = mapped_column(String(32))
    period_type: Mapped[str | None] = mapped_column(String(16))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_period: Mapped[str | None] = mapped_column(String(16))
    accession: Mapped[str | None] = mapped_column(String(32))
    filing_date: Mapped[date | None] = mapped_column(Date)
    form_type: Mapped[str | None] = mapped_column(String(16))
    statement_type: Mapped[str | None] = mapped_column(String(32))
    taxonomy: Mapped[str | None] = mapped_column(String(32))
    scale: Mapped[str | None] = mapped_column(String(32))
    data_quality: Mapped[str | None] = mapped_column(String(32))
    is_audited: Mapped[bool | None] = mapped_column(Boolean)
    confidence_score: Mapped[Decimal | None] = mapped_column(ExactNumeric())
    period_days: Mapped[int | None] = mapped_column(Integer)
    period_shape: Mapped[str | None] = mapped_column(String(16))
    metric: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index(
            "ix_quality_annual_fact_batch_cik_metric_end",
            "batch_id", "cik", "metric", "period_end",
        ),
    )


class QualityPeer(Base):
    """One peer-universe row (migrated from the checked-in peer CSV),
    referenced by its import batch."""

    __tablename__ = "quality_peer"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("quality_input_batch.id", ondelete="CASCADE"), nullable=False
    )
    source_symbol: Mapped[str | None] = mapped_column(String(32))
    canonical_symbol: Mapped[str | None] = mapped_column(String(32))
    company_name: Mapped[str | None] = mapped_column(String(255))
    gics_sector: Mapped[str | None] = mapped_column(String(64))
    gics_sub_industry: Mapped[str | None] = mapped_column(String(128))
    cik: Mapped[str | None] = mapped_column(String(10))
    date_added: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        Index("ix_quality_peer_batch_id", "batch_id"),
    )
