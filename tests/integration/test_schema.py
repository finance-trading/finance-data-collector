"""Integration tests for the versioned schema migration.

The migration is exercised on SQLite so the suite stays offline; PostgreSQL is
covered when ``FDC_TEST_POSTGRES_URL`` points at a reachable server.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Text, create_engine, inspect, text
from sqlalchemy.orm import Session

from alembic import command
from fdc.models import Base, Filing, FilingParse, Issuer, ParseRun

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_INDEXES = {
    "ix_artifact_sha256",
    "ix_evidence_locator_filing_id_locator_type",
    "ix_filing_accession_number",
    "ix_filing_issuer_id_filing_date_form",
    "ix_filing_parse_status",
    "ix_parse_run_scope_type_scope_value",
    "ix_parse_run_status_started_at",
    "ix_statement_line_filing_type_order",
    "ix_xbrl_fact_concept_end_date",
    "ix_xbrl_fact_concept_namespace_concept",
    "uq_filing_parse_current",
    "ix_extracted_table_filing_id_table_type",
    "ix_filing_section_filing_id_section_type",
}


def alembic_config(database_url: str) -> Config:
    """Return an alembic config that migrates the given database URL."""

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def sqlite_url(tmp_path: Path, name: str = "migrated.db") -> str:
    return f"sqlite:///{tmp_path / name}"


@pytest.fixture
def migrated_url(tmp_path: Path) -> str:
    url = sqlite_url(tmp_path)
    command.upgrade(alembic_config(url), "head")
    return url


def test_upgrade_creates_every_model_table(migrated_url):
    inspector = inspect(create_engine(migrated_url))

    migrated = set(inspector.get_table_names()) - {"alembic_version"}

    assert migrated == set(Base.metadata.tables)


def test_migrated_columns_match_model_metadata(migrated_url):
    inspector = inspect(create_engine(migrated_url))

    for name, table in Base.metadata.tables.items():
        columns = {column["name"] for column in inspector.get_columns(name)}
        assert columns == {column.name for column in table.columns}, name


@pytest.mark.parametrize(
    ("table_name", "column_name"),
    [
        ("evidence_locator", "locator_value"),
        ("extracted_table", "caption"),
        ("xbrl_fact", "unit"),
        ("statement_line", "unit"),
    ],
)
def test_unbounded_parser_payload_columns_are_text(
    migrated_url, table_name, column_name
):
    inspector = inspect(create_engine(migrated_url))
    column = next(
        item for item in inspector.get_columns(table_name) if item["name"] == column_name
    )

    assert isinstance(column["type"], Text)


def test_migrated_indexes_and_constraints_exist(migrated_url):
    engine = create_engine(migrated_url)
    with engine.connect() as connection:
        indexes = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'index'")
            )
        }

    assert EXPECTED_INDEXES <= indexes


def test_upgrade_is_idempotent(migrated_url):
    command.upgrade(alembic_config(migrated_url), "head")

    inspector = inspect(create_engine(migrated_url))

    assert set(inspector.get_table_names()) - {"alembic_version"} == set(Base.metadata.tables)


def test_downgrade_to_base_removes_parser_tables(tmp_path):
    url = sqlite_url(tmp_path, "downgrade.db")
    config = alembic_config(url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    remaining = set(inspect(create_engine(url)).get_table_names())

    assert remaining <= {"alembic_version"}


@pytest.mark.skipif(
    not os.environ.get("FDC_TEST_POSTGRES_URL"),
    reason="FDC_TEST_POSTGRES_URL is not configured",
)
def test_postgres_upgrade_matches_models():
    url = os.environ["FDC_TEST_POSTGRES_URL"]
    command.upgrade(alembic_config(url), "head")

    inspector = inspect(create_engine(url))

    assert set(inspector.get_table_names()) - {"alembic_version"} == set(Base.metadata.tables)


@pytest.mark.skipif(
    not os.environ.get("FDC_TEST_POSTGRES_URL"),
    reason="FDC_TEST_POSTGRES_URL is not configured",
)
def test_postgres_persists_composed_parse_mode():
    url = os.environ["FDC_TEST_POSTGRES_URL"]
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    issuer_id = uuid4()
    filing_id = uuid4()
    run_id = uuid4()
    parse_id = uuid4()
    composed_mode = "edgartools-local+deterministic-html"

    with Session(engine) as session:
        session.add(
            Issuer(id=issuer_id, cik="9999999999", name="Schema Test", ticker_hint="TEST")
        )
        session.flush()
        session.add_all(
            [
                Filing(
                    id=filing_id,
                    issuer_id=issuer_id,
                    accession_number="9999999999-26-000001",
                    form="10-K",
                    package_path="10-K/9999999999-26-000001",
                ),
                ParseRun(
                    id=run_id,
                    scope_type="filing",
                    scope_value="9999999999-26-000001",
                    parser_version="filing-parser-v1",
                    status="completed",
                    started_at=datetime.now(UTC),
                ),
            ]
        )
        session.flush()
        session.add(
            FilingParse(
                id=parse_id,
                filing_id=filing_id,
                parse_run_id=run_id,
                artifact_set_hash="a" * 64,
                parser_version="filing-parser-v1",
                parser_modules_hash="b" * 64,
                parse_mode=composed_mode,
                status="success",
                is_current=True,
            )
        )

        session.flush()

        assert session.get(FilingParse, parse_id).parse_mode == composed_mode
