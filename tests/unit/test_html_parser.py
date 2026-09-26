"""Deterministic, offline tests for narrative and HTML-table parsing."""

from __future__ import annotations

import hashlib
import socket
from datetime import date
from pathlib import Path

import pytest

from fdc.contracts import (
    ArtifactRef,
    ArtifactRole,
    ArtifactStatus,
    LocalFiling,
    LocatorType,
    ParseStatus,
    RowStatus,
)
from fdc.parsers.html_parser import parse_html_document

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "filings" / "with_debt"
PARSER_VERSION = "filing-parser-v1"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """The HTML parser must operate entirely on local artifacts."""

    def deny(*args, **kwargs):
        raise AssertionError("HTML parsing must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


def _local_filing(path: Path, form: str = "10-K") -> LocalFiling:
    content = path.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    relative_path = f"{form}/0000000000-26-000001/{path.name}"
    artifact = ArtifactRef(
        relative_path=relative_path,
        path=path,
        byte_size=len(content),
        sha256=sha256,
        role=ArtifactRole.PRIMARY,
        content_type="text/html",
        status=ArtifactStatus.INDEXED,
        parse_eligible=True,
    )
    return LocalFiling(
        ticker="ACME",
        form=form,
        accession="0000000000-26-000001",
        is_amended=False,
        filing_date=date(2026, 2, 20),
        report_date=date(2025, 12, 31),
        fiscal_year=2025,
        fiscal_period="FY",
        package_path=f"{form}/0000000000-26-000001",
        package_dir=path.parent,
        primary_relative_path=relative_path,
        primary_document=path,
        artifacts=(artifact,),
        artifact_set_hash="f" * 64,
    )


@pytest.fixture
def debt_fixture() -> Path:
    return FIXTURES / "filing.html"


@pytest.fixture
def local_filing(debt_fixture: Path) -> LocalFiling:
    return _local_filing(debt_fixture)


def test_sections_keep_heading_order_and_source_locator(debt_fixture, local_filing):
    output = parse_html_document(debt_fixture, local_filing, PARSER_VERSION)
    mdna = next(section for section in output.sections if section.section_type == "md_and_a")

    assert mdna.order_index > 0
    assert mdna.evidence is not None
    assert mdna.evidence.locator_type in {LocatorType.HEADING, LocatorType.HTML_ID}
    assert mdna.evidence.locator_value == "item-7"
    assert "liquidity" in (mdna.text or "").lower()
    assert [section.section_type for section in output.sections[:5]] == [
        "business",
        "risk_factors",
        "md_and_a",
        "financial_statements",
        "controls",
    ]


def test_every_extracted_section_and_table_has_content_bound_evidence(
    debt_fixture, local_filing
):
    output = parse_html_document(debt_fixture, local_filing, PARSER_VERSION)
    source = local_filing.primary_artifact

    assert source is not None
    assert output.sections
    assert output.tables
    for draft in [*output.sections, *output.tables]:
        assert draft.evidence is not None
        assert draft.evidence.relative_path == source.relative_path
        assert draft.evidence.content_sha256 == source.sha256
        if draft.status == RowStatus.PARSED:
            assert draft.raw_fragment
            assert draft.raw_fragment_hash == hashlib.sha256(
                draft.raw_fragment.encode("utf-8")
            ).hexdigest()
    assert output.evidence == [
        draft.evidence for draft in [*output.sections, *output.tables]
    ]


def test_debt_maturity_table_is_typed_and_keeps_source_metadata(
    debt_fixture, local_filing
):
    output = parse_html_document(debt_fixture, local_filing, PARSER_VERSION)
    table = next(table for table in output.tables if table.table_type == "debt_maturity")

    assert table.rows[0]["period"] == "2027"
    assert table.rows[0]["amount"] == "$120"
    assert table.status == "parsed"
    assert table.columns == ("period", "amount")
    assert table.period_hints == {
        "nearby_heading": "Long-Term Debt",
        "original_columns": ["Year", "Principal Payments"],
        "periods": ["2027", "2028"],
        "unit": "millions",
    }
    assert table.extraction_method == "html_table"
    assert table.confidence == 0.95
    assert table.evidence is not None
    assert table.evidence.locator_type is LocatorType.TABLE_CELL


def test_missing_expected_section_is_explicit_not_fabricated():
    path = FIXTURES / "malformed-table.html"
    filing = _local_filing(path, form="10-Q")

    output = parse_html_document(path, filing, PARSER_VERSION)
    missing = next(
        section for section in output.sections if section.section_type == "financial_statements"
    )

    assert output.status is ParseStatus.PARTIAL
    assert missing.status is RowStatus.UNAVAILABLE
    assert missing.text is None
    assert missing.raw_fragment is None
    assert missing.raw_fragment_hash is None
    assert missing.evidence is not None
    assert missing.evidence.locator_value == "missing:financial_statements"
    assert any(diagnostic.code == "HTML_SECTION_UNAVAILABLE" for diagnostic in missing.diagnostics)


def test_ten_q_part_context_suppresses_toc_wrappers_and_reused_item_numbers():
    path = FIXTURES / "ten-q-parts.html"
    filing = _local_filing(path, form="10-Q")

    output = parse_html_document(path, filing, PARSER_VERSION)
    parsed = [section for section in output.sections if section.status is RowStatus.PARSED]

    assert [section.section_type for section in parsed] == [
        "financial_statements",
        "md_and_a",
        "controls",
        "risk_factors",
    ]
    assert len({section.section_type for section in parsed}) == len(parsed)
    assert [section.evidence.locator_value for section in parsed] == [
        "financial-statements",
        "quarterly-mdna",
        "quarterly-controls",
        "quarterly-risks",
    ]
    assert "legal proceedings" not in " ".join(section.text or "" for section in parsed).lower()


def test_item_heading_in_single_cell_presentation_table_is_recognized(tmp_path):
    path = tmp_path / "presentation-heading.html"
    path.write_text(
        """<html><body><table><tr><td>
        <p id="table-item-7">Item 7. Management's Discussion and Analysis</p>
        </td></tr></table>
        <p>Liquidity from operations remained strong.</p>
        <h2>Item 8. Financial Statements and Supplementary Data</h2>
        <p>Financial statements follow.</p>
        </body></html>"""
    )
    filing = _local_filing(path, form="10-K")

    output = parse_html_document(path, filing, PARSER_VERSION)
    mdna = next(section for section in output.sections if section.section_type == "md_and_a")

    assert mdna.status is RowStatus.PARSED
    assert mdna.evidence.locator_value == "table-item-7"
    assert "liquidity" in (mdna.text or "").lower()


def test_item_like_text_in_multi_cell_data_table_is_not_a_heading(tmp_path):
    path = tmp_path / "data-table.html"
    path.write_text(
        """<html><body>
        <table><tr><td><p>Item 1. Business</p></td><td>ordinary data</td></tr></table>
        <h2>Item 7. Management's Discussion and Analysis</h2>
        <p>Liquidity remained strong.</p>
        </body></html>"""
    )
    filing = _local_filing(path, form="10-K")

    output = parse_html_document(path, filing, PARSER_VERSION)
    business = next(section for section in output.sections if section.section_type == "business")

    assert business.status is RowStatus.UNAVAILABLE


def test_headerless_table_preserves_first_row_and_is_explicitly_unsupported():
    path = FIXTURES / "headerless-table.html"
    filing = _local_filing(path, form="10-K")

    output = parse_html_document(path, filing, PARSER_VERSION)
    table = output.tables[0]

    assert table.status is RowStatus.UNSUPPORTED
    assert table.columns == ("column_1", "column_2")
    assert table.rows == (
        {"column_1": "2027", "column_2": "120"},
        {"column_1": "2028", "column_2": "80"},
    )
    assert any(diagnostic.code == "UNSUPPORTED_HTML_TABLE" for diagnostic in table.diagnostics)
    assert output.status is ParseStatus.PARTIAL


def test_unsupported_form_emits_an_explicit_status_record(debt_fixture):
    filing = _local_filing(debt_fixture, form="8-K")

    output = parse_html_document(debt_fixture, filing, PARSER_VERSION)

    assert output.status is ParseStatus.PARTIAL
    assert len(output.sections) == 1
    section = output.sections[0]
    assert section.section_type == "unsupported"
    assert section.status is RowStatus.UNSUPPORTED
    assert section.evidence is not None
    assert section.evidence.locator_value == "unsupported-form:8-K"
    assert section.diagnostics[0].code == "HTML_FORM_UNSUPPORTED"


def test_malformed_table_is_retained_with_scoped_diagnostic():
    path = FIXTURES / "malformed-table.html"
    filing = _local_filing(path, form="10-Q")

    output = parse_html_document(path, filing, PARSER_VERSION)
    table = output.tables[0]

    assert table.status is RowStatus.FAILED
    assert table.rows == ({"period": "2027", "operating_leases": "40", "debt": ""},)
    assert table.evidence is not None
    assert table.evidence.locator_type is LocatorType.HTML_ID
    assert table.evidence.locator_value == "broken-obligations"
    assert table.raw_fragment_hash == hashlib.sha256(
        table.raw_fragment.encode("utf-8")
    ).hexdigest()
    assert any(diagnostic.code == "MALFORMED_HTML_TABLE" for diagnostic in table.diagnostics)


def test_parse_is_deterministic_for_identical_local_bytes(debt_fixture, local_filing):
    first = parse_html_document(debt_fixture, local_filing, PARSER_VERSION)
    second = parse_html_document(debt_fixture, local_filing, PARSER_VERSION)

    assert first == second


def test_unreadable_path_returns_a_failed_output(tmp_path):
    path = tmp_path / "missing.html"
    filing = _local_filing(FIXTURES / "filing.html")

    output = parse_html_document(path, filing, PARSER_VERSION)

    assert output.status is ParseStatus.FAILED
    assert output.sections == []
    assert output.tables == []
    assert output.diagnostics[0].code == "UNREADABLE_ARTIFACT"
