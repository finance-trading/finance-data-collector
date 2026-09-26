"""Unit tests for the EdgarTools XBRL adapter.

Everything here runs offline: the adapter is exercised against a fixture double
that mimics the pinned EdgarTools ``XBRL.from_directory`` dict shapes, plus a
small checked-in XBRL instance for the raw-XBRL fallback path.  Any test that
opens a socket fails through the autouse guard below.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
from datetime import date
from pathlib import Path

import pytest

from fdc.archive import scan_ticker_archive
from fdc.contracts import (
    ArtifactRole,
    DiagnosticCode,
    DiagnosticSeverity,
    FactDraft,
    LocatorType,
    ParserOutput,
    ParseStatus,
    StatementDraft,
)
from fdc.parsers.edgartools_adapter import (
    DEFAULT_PARSER_VERSION,
    DEFAULT_STATEMENT_TYPES,
    EdgarToolsAdapter,
    default_parser_version,
    installed_edgartools_version,
    normalize_fact,
    parse_xbrl_instance,
    period_type,
)

EDGAR_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "edgar"
FILING_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "filings"
PARSER_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}
PARSER_VERSION = "filing-parser-v1"


class StatementNotFoundError(Exception):
    """Stands in for ``edgar.exceptions.StatementNotFoundError``."""


class XbrlUnavailableError(Exception):
    """Stands in for an EdgarTools failure while opening a local package."""


class FakeFactsView:
    def __init__(self, facts: list[dict]) -> None:
        self._facts = facts

    def get_facts(self) -> list[dict]:
        return [dict(fact) for fact in self._facts]


class UnavailableFactsView:
    def get_facts(self) -> list[dict]:
        raise RuntimeError("facts unavailable")


class ExplodingFact(dict):
    def get(self, key, default=None):
        if key == "concept":
            raise RuntimeError("normalization exploded")
        return super().get(key, default)


class ExplodingFactsView:
    def get_facts(self) -> list[dict]:
        return [ExplodingFact(value="1")]


class FakeXbrl:
    """Minimal double of ``edgar.xbrl.XBRL`` using the pinned dict shapes."""

    def __init__(
        self,
        facts: list[dict],
        statements: dict[str, list[dict]] | None = None,
    ) -> None:
        self.facts = FakeFactsView(facts)
        self._statements = statements or {}

    def get_statement(self, selector: str) -> list[dict]:
        rows = self._statements.get(selector)
        if not rows:
            raise StatementNotFoundError(selector)
        return [dict(row) for row in rows]

    @property
    def reporting_periods(self) -> list[dict]:
        return []


def load_facts() -> list[dict]:
    return json.loads((EDGAR_FIXTURES / "facts.json").read_text())


def load_statements() -> dict[str, list[dict]]:
    return json.loads((EDGAR_FIXTURES / "statements.json").read_text())


def write_local_filing(
    tmp_path: Path,
    files: dict[str, Path],
    ticker: str = "ACME",
    primary_document: str | None = None,
):
    """Copy instance documents into a scratch archive and scan it."""

    accession = "0000000000-24-000010"
    directory = f"10-Q/{accession}"
    package = tmp_path / ticker / directory
    package.mkdir(parents=True)
    for name, source in files.items():
        shutil.copy(source, package / name)
    (tmp_path / ticker / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "form": "10-Q",
                        "date": "2024-04-25",
                        "accession": accession,
                        "directory": directory,
                        "primary_document": primary_document,
                    }
                ]
            }
        )
    )
    return scan_ticker_archive(tmp_path, ticker, PARSER_FORMS).filings[0]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Parsing local filings must never open a socket."""

    def deny(*args, **kwargs):
        raise AssertionError("the EdgarTools adapter must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


@pytest.fixture
def local_filing():
    return scan_ticker_archive(FILING_FIXTURES, "MSFT", PARSER_FORMS).filings[0]


@pytest.fixture
def fake_edgartools(monkeypatch):
    """Patch the adapter's local opener with the fixture double."""

    facts = load_facts()
    statements = load_statements()
    monkeypatch.setattr(
        "fdc.parsers.edgartools_adapter.xbrl_from_directory",
        lambda directory: FakeXbrl(facts, statements),
    )
    return facts


@pytest.fixture
def fake_edgartools_without_statements(monkeypatch):
    facts = load_facts()
    monkeypatch.setattr(
        "fdc.parsers.edgartools_adapter.xbrl_from_directory",
        lambda directory: FakeXbrl(facts),
    )
    return facts


@pytest.fixture
def fake_edgartools_unavailable(monkeypatch):
    def unavailable(directory):
        raise XbrlUnavailableError(f"cannot open {directory}")

    monkeypatch.setattr("fdc.parsers.edgartools_adapter.xbrl_from_directory", unavailable)


@pytest.fixture
def instance_filing(tmp_path):
    """Filing whose only parseable artifact is a classic XBRL instance."""

    return write_local_filing(
        tmp_path,
        {"acme-20240331.xml": EDGAR_FIXTURES / "instance_sample.xml"},
    )


@pytest.fixture
def inline_filing(tmp_path):
    """Filing whose only parseable artifact is an inline XBRL document."""

    return write_local_filing(
        tmp_path, {"acme-20240331_htm.xml": EDGAR_FIXTURES / "inline_sample.xml"}
    )


def test_adapter_preserves_period_identity_and_dimensions(fake_edgartools, local_filing):
    output = EdgarToolsAdapter().parse(local_filing)
    revenue = next(fact for fact in output.facts if fact.concept == "Revenue")

    assert revenue.start_date == date(2024, 1, 1)
    assert revenue.end_date == date(2024, 3, 31)
    assert revenue.period_type == "quarter"
    assert revenue.dimensions == {"segment": "cloud"}


def test_ytd_is_not_classified_as_quarter():
    assert period_type(date(2024, 1, 1), date(2024, 9, 30)) == "ytd"


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (None, None, "other"),
        (None, date(2024, 3, 31), "instant"),
        (date(2024, 1, 1), date(2024, 3, 31), "quarter"),
        (date(2024, 3, 1), date(2024, 3, 15), "other"),
        (date(2024, 1, 1), date(2024, 6, 30), "ytd"),
        (date(2024, 1, 1), date(2024, 10, 31), "ytd"),
        (date(2024, 1, 1), date(2024, 12, 31), "annual"),
        (date(2023, 7, 1), date(2024, 6, 30), "annual"),
        (date(2023, 1, 1), date(2024, 6, 30), "other"),
    ],
)
def test_period_type_classification(start, end, expected):
    assert period_type(start, end) == expected


def test_adapter_parses_facts_with_filing_and_parser_identity(fake_edgartools, local_filing):
    output = EdgarToolsAdapter(parser_version=PARSER_VERSION).parse(local_filing)
    assets = next(fact for fact in output.facts if fact.concept == "us-gaap:Assets")

    assert output.status is ParseStatus.SUCCESS
    assert output.parse_mode == "edgartools-local"
    assert output.parser_version == PARSER_VERSION
    assert assets.concept_namespace == "us-gaap"
    assert assets.value_numeric == 484275000000.0
    assert assets.unit == "USD"
    assert assets.decimals == -6
    assert assets.start_date is None
    assert assets.end_date == date(2024, 3, 31)
    assert assets.period_type == "instant"
    assert assets.extraction_method == "edgartools_fact"


def test_ytd_fact_is_marked_as_ytd(fake_edgartools, local_filing):
    output = EdgarToolsAdapter().parse(local_filing)
    ytd = next(
        fact
        for fact in output.facts
        if fact.concept == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
        and fact.start_date == date(2023, 7, 1)
    )

    assert ytd.period_type == "ytd"
    assert ytd.end_date == date(2024, 3, 31)


def test_every_fact_carries_source_and_fact_identity_evidence(fake_edgartools, local_filing):
    output = EdgarToolsAdapter().parse(local_filing)
    source = next(
        artifact
        for artifact in local_filing.artifacts
        if artifact.role is ArtifactRole.XBRL and artifact.path.suffix == ".xml"
    )

    assert output.facts
    for fact in output.facts:
        assert fact.evidence is not None
        assert fact.evidence.locator_type is LocatorType.XBRL_FACT
        assert fact.evidence.locator_value.startswith(f"concept={fact.concept};context=")
        assert ";period=" in fact.evidence.locator_value
        assert ";dimensions=" in fact.evidence.locator_value
        assert fact.evidence.relative_path == source.relative_path
        assert fact.evidence.content_sha256 == source.sha256


def test_malformed_facts_keep_text_but_never_fabricate_a_number(fake_edgartools, local_filing):
    output = EdgarToolsAdapter().parse(local_filing)
    malformed = next(
        fact for fact in output.facts if fact.concept == "us-gaap:GoodwillImpairmentLoss"
    )

    assert malformed.value_numeric is None
    assert malformed.value_text == "not-a-number"
    assert malformed.decimals is None
    assert any(
        diagnostic.code is DiagnosticCode.FACT_MALFORMED for diagnostic in output.diagnostics
    )


@pytest.mark.parametrize("raw_value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_facts_never_become_numeric_values(local_filing, raw_value):
    draft = normalize_fact(
        {
            "concept": "us-gaap:Assets",
            "value": raw_value,
            "numeric_value": raw_value,
            "unit_ref": "U_USD",
        },
        local_filing,
        PARSER_VERSION,
    )

    assert draft is not None
    assert draft.value_numeric is None
    assert draft.value_text == raw_value


def test_facts_without_a_concept_are_dropped_with_a_diagnostic(fake_edgartools, local_filing):
    output = EdgarToolsAdapter().parse(local_filing)

    assert all(fact.concept for fact in output.facts)
    assert not any(fact.value_text == "12.5" for fact in output.facts)


def test_statements_are_emitted_once_per_period_in_presentation_order(
    fake_edgartools, local_filing
):
    output = EdgarToolsAdapter().parse(local_filing)
    income = [row for row in output.statements if row.statement_type == "IncomeStatement"]

    assert isinstance(output.statements[0], StatementDraft)
    assert [row.label for row in income] == ["Revenue", "Revenue", "Operating income"]
    assert [row.order_index for row in income] == sorted(row.order_index for row in income)
    assert [row.start_date for row in income] == [
        date(2024, 1, 1),
        date(2023, 1, 1),
        date(2024, 1, 1),
    ]
    assert income[0].end_date == date(2024, 3, 31)
    assert income[0].value_numeric == 69632000000.0
    assert income[0].concept == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert income[0].unit == "USD"
    assert income[0].period_type == "quarter"
    assert income[0].depth == 2
    assert income[0].section == "us-gaap:StatementLineItems"
    # Abstract presentation rows carry no value and are not stored.
    assert all(row.value_numeric is not None for row in income)
    assert income[0].evidence.locator_value.endswith(
        ';dimensions={}'
    )
    assert ";context=" in income[0].evidence.locator_value
    assert ";period=duration_2024-01-01_2024-03-31;" in income[0].evidence.locator_value


def test_statement_rows_preserve_all_dimensions_per_period(local_filing):
    statements = load_statements()
    statements["IncomeStatement"][1]["dimension_metadata"] = [
        {
            "dimension": "us-gaap:StatementBusinessSegmentsAxis",
            "member": "acme:CloudMember",
            "member_label": "Cloud",
        },
        {
            "dimension": "srt:ProductOrServiceAxis",
            "member": "acme:SubscriptionMember",
            "member_label": "Subscription",
        },
    ]
    xbrl = FakeXbrl(load_facts(), statements)

    output = EdgarToolsAdapter(
        statement_types=("IncomeStatement",), opener=lambda directory: xbrl
    ).parse(local_filing)
    revenue_rows = [
        row
        for row in output.statements
        if row.concept == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    ]

    assert revenue_rows
    assert all(
        row.dimensions
        == {
            "us-gaap:StatementBusinessSegmentsAxis": "acme:CloudMember",
            "srt:ProductOrServiceAxis": "acme:SubscriptionMember",
        }
        for row in revenue_rows
    )
    assert '"srt:ProductOrServiceAxis":"acme:SubscriptionMember"' in (
        revenue_rows[0].evidence.locator_value
    )


def test_edgartools_evidence_resolves_each_observation_source(tmp_path):
    unique_instance = tmp_path / "unique-source.xml"
    unique_instance.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:us-gaap="http://fasb.org/us-gaap/2024"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
  <xbrli:context id="c-unique">
    <xbrli:entity><xbrli:identifier scheme="test">1</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2024-01-01</xbrli:startDate>
      <xbrli:endDate>2024-03-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>
  <xbrli:unit id="U_USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <us-gaap:OperatingExpenses contextRef="c-unique" unitRef="U_USD" decimals="-6">
    123000000
  </us-gaap:OperatingExpenses>
</xbrli:xbrl>"""
    )
    filing = write_local_filing(
        tmp_path / "archive",
        {
            "base.xml": EDGAR_FIXTURES / "instance_sample.xml",
            "unique.xml": unique_instance,
        },
    )
    facts = [
        {
            "concept": "us-gaap:OperatingExpenses",
            "context_ref": "c-unique",
            "value": "123000000",
            "numeric_value": 123000000.0,
            "unit_ref": "U_USD",
            "decimals": "-6",
            "period_start": "2024-01-01",
            "period_end": "2024-03-31",
        }
    ]
    period = "duration_2024-01-01_2024-03-31"
    statements = {
        "IncomeStatement": [
            {
                "concept": "us-gaap_OperatingExpenses",
                "label": "Operating expenses",
                "level": 1,
                "values": {period: 123000000.0},
                "units": {period: "U_USD"},
                "decimals": {period: -6},
            }
        ]
    }
    xbrl = FakeXbrl(facts, statements)

    output = EdgarToolsAdapter(
        statement_types=("IncomeStatement",), opener=lambda directory: xbrl
    ).parse(filing)
    fact = output.facts[0]
    statement = output.statements[0]

    assert fact.evidence.relative_path.endswith("unique.xml")
    assert statement.evidence.relative_path.endswith("unique.xml")
    assert ";context=c-unique;" in statement.evidence.locator_value
    assert f";period={period};dimensions={{}}" in statement.evidence.locator_value


def test_edgartools_evidence_marks_unresolvable_multi_instance_source_as_ambiguous(
    tmp_path,
):
    filing = write_local_filing(
        tmp_path,
        {
            "first.xml": EDGAR_FIXTURES / "instance_sample.xml",
            "second.xml": EDGAR_FIXTURES / "inline_sample.xml",
        },
    )
    facts = [
        {
            "concept": "us-gaap:InventoryNet",
            "context_ref": "c-missing",
            "value": "100",
            "numeric_value": 100.0,
            "unit_ref": "U_USD",
            "decimals": "0",
            "period_instant": "2024-03-31",
        }
    ]

    output = EdgarToolsAdapter(
        statement_types=(), opener=lambda directory: FakeXbrl(facts)
    ).parse(filing)
    fact = output.facts[0]

    assert fact.evidence.relative_path is None
    assert fact.evidence.content_sha256 is None
    assert fact.evidence.locator_value.endswith(";source=ambiguous")


def test_balance_sheet_rows_keep_instant_periods(fake_edgartools, local_filing):
    output = EdgarToolsAdapter().parse(local_filing)
    assets = next(row for row in output.statements if row.statement_type == "BalanceSheet")

    assert assets.start_date is None
    assert assets.end_date == date(2024, 3, 31)
    assert assets.period_type == "instant"
    assert assets.value_numeric == 484275000000.0
    assert assets.label == "Total assets"


def test_malformed_statement_values_remain_explicit_without_a_numeric_value(local_filing):
    statements = load_statements()
    period = "duration_2024-01-01_2024-03-31"
    statements["IncomeStatement"][1]["values"][period] = "not-a-number"
    xbrl = FakeXbrl(load_facts(), statements)

    output = EdgarToolsAdapter(
        statement_types=("IncomeStatement",), opener=lambda directory: xbrl
    ).parse(local_filing)
    malformed = next(
        row
        for row in output.statements
        if row.concept == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
        and row.start_date == date(2024, 1, 1)
    )

    assert malformed.value_numeric is None
    assert malformed.value_text == "not-a-number"
    assert malformed.evidence.excerpt == "not-a-number"


def test_missing_statements_are_explicit_and_partial(
    fake_edgartools_without_statements, local_filing
):
    output = EdgarToolsAdapter().parse(local_filing)

    assert output.facts
    assert output.statements == []
    assert output.status is ParseStatus.PARTIAL
    assert {diagnostic.code for diagnostic in output.diagnostics} >= {
        DiagnosticCode.STATEMENT_UNAVAILABLE
    }
    assert all(
        diagnostic.severity is DiagnosticSeverity.WARNING
        for diagnostic in output.diagnostics
        if diagnostic.code is DiagnosticCode.STATEMENT_UNAVAILABLE
    )
    assert {diagnostic.scope for diagnostic in output.diagnostics} >= set(DEFAULT_STATEMENT_TYPES)


def test_fact_collection_error_is_not_reported_as_success(local_filing):
    xbrl = FakeXbrl(load_facts(), load_statements())
    xbrl.facts = UnavailableFactsView()

    output = EdgarToolsAdapter(
        statement_types=("IncomeStatement",), opener=lambda directory: xbrl
    ).parse(local_filing)

    assert output.parse_mode == "edgartools-local"
    assert output.status is ParseStatus.PARTIAL
    assert output.statements
    assert any(
        diagnostic.code is DiagnosticCode.XBRL_UNAVAILABLE
        and diagnostic.severity is DiagnosticSeverity.ERROR
        for diagnostic in output.diagnostics
    )


def test_normalization_error_stays_in_edgartools_mode(local_filing):
    xbrl = FakeXbrl([], {})
    xbrl.facts = ExplodingFactsView()

    output = EdgarToolsAdapter(statement_types=(), opener=lambda directory: xbrl).parse(
        local_filing
    )

    assert output.parse_mode == "edgartools-local"
    assert output.status is ParseStatus.FAILED
    assert any(
        diagnostic.code is DiagnosticCode.FACT_MALFORMED
        and diagnostic.scope == "normalization"
        for diagnostic in output.diagnostics
    )
    assert not any(
        diagnostic.code is DiagnosticCode.RAW_XBRL_FALLBACK
        for diagnostic in output.diagnostics
    )


def test_adapter_falls_back_to_raw_xbrl_instances(fake_edgartools_unavailable, instance_filing):
    output = EdgarToolsAdapter().parse(instance_filing)
    revenues = [fact for fact in output.facts if fact.concept == "us-gaap:Revenues"]

    assert output.parse_mode == "raw-xbrl-fallback"
    assert output.status is ParseStatus.PARTIAL
    assert any(
        diagnostic.code is DiagnosticCode.RAW_XBRL_FALLBACK for diagnostic in output.diagnostics
    )
    assert any(
        diagnostic.code is DiagnosticCode.XBRL_UNAVAILABLE for diagnostic in output.diagnostics
    )
    assert len(revenues) == 2

    plain = next(fact for fact in revenues if fact.dimensions == {})
    assert plain.value_numeric == 69632000000.0
    assert plain.start_date == date(2024, 1, 1)
    assert plain.end_date == date(2024, 3, 31)
    assert plain.period_type == "quarter"
    assert plain.unit == "USD"
    assert plain.decimals == -6

    dimensioned = next(fact for fact in revenues if fact.dimensions)
    assert dimensioned.dimensions == {
        "us-gaap:StatementBusinessSegmentsAxis": "acme:CloudMember",
        "srt:ProductOrServiceAxis": "acme:SubscriptionMember",
    }
    assert dimensioned.value_numeric == 25100000000.0

    assets = next(fact for fact in output.facts if fact.concept == "us-gaap:Assets")
    assert assets.period_type == "instant"
    assert assets.start_date is None

    document_type = next(fact for fact in output.facts if fact.concept == "dei:DocumentType")
    assert document_type.value_numeric is None
    assert document_type.value_text == "10-Q"


def test_fallback_evidence_points_to_the_xbrl_instance(
    fake_edgartools_unavailable, tmp_path
):
    filing = write_local_filing(
        tmp_path,
        {
            "acme-20240331.htm": EDGAR_FIXTURES / "inline_sample.xml",
            "acme-20240331.xml": EDGAR_FIXTURES / "instance_sample.xml",
        },
        primary_document="acme-20240331.htm",
    )

    output = EdgarToolsAdapter().parse(filing)
    revenues = [fact for fact in output.facts if fact.concept == "us-gaap:Revenues"]
    revenue = next(fact for fact in revenues if not fact.dimensions)
    instance = next(
        artifact for artifact in filing.artifacts if artifact.path.name == "acme-20240331.xml"
    )

    assert revenue.evidence.relative_path == instance.relative_path
    assert revenue.evidence.content_sha256 == instance.sha256
    assert len(revenues) == 2


def test_fallback_sniffs_inline_xbrl_in_html(fake_edgartools_unavailable, tmp_path):
    filing = write_local_filing(
        tmp_path,
        {"acme-20240331.htm": EDGAR_FIXTURES / "inline_sample.xml"},
        primary_document="acme-20240331.htm",
    )

    output = EdgarToolsAdapter().parse(filing)

    assert output.parse_mode == "raw-xbrl-fallback"
    assert output.status is ParseStatus.PARTIAL
    assert any(fact.concept == "us-gaap:Revenues" for fact in output.facts)


def test_raw_xbrl_fallback_applies_inline_scale_and_sign(
    fake_edgartools_unavailable, inline_filing
):
    output = EdgarToolsAdapter().parse(inline_filing)
    revenues = next(fact for fact in output.facts if fact.concept == "us-gaap:Revenues")
    net_loss = next(fact for fact in output.facts if fact.concept == "us-gaap:NetIncomeLoss")

    assert output.parse_mode == "raw-xbrl-fallback"
    assert revenues.value_numeric == 69632000000.0
    assert net_loss.value_numeric == -1234000000.0
    assert revenues.end_date == date(2024, 3, 31)


def test_fallback_reports_when_no_instance_is_present(fake_edgartools_unavailable, local_filing):
    output = EdgarToolsAdapter().parse(local_filing)

    assert output.facts == []
    assert output.status is ParseStatus.FAILED
    assert any(
        diagnostic.code is DiagnosticCode.XBRL_UNAVAILABLE for diagnostic in output.diagnostics
    )


def test_parse_xbrl_instance_rejects_unparsable_documents(tmp_path):
    broken = tmp_path / "broken.xml"
    broken.write_text("<xbrli:xbrl>")

    with pytest.raises(ValueError):
        parse_xbrl_instance(broken)


def test_raw_xbrl_preserves_divisional_units(tmp_path):
    instance = tmp_path / "divisional.xml"
    instance.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:us-gaap="http://fasb.org/us-gaap/2024"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
  <xbrli:context id="c1">
    <xbrli:entity><xbrli:identifier scheme="test">1</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2024-01-01</xbrli:startDate>
      <xbrli:endDate>2024-03-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>
  <xbrli:unit id="usd-per-share">
    <xbrli:divide>
      <xbrli:unitNumerator>
        <xbrli:measure>iso4217:USD</xbrli:measure>
      </xbrli:unitNumerator>
      <xbrli:unitDenominator>
        <xbrli:measure>xbrli:shares</xbrli:measure>
      </xbrli:unitDenominator>
    </xbrli:divide>
  </xbrli:unit>
  <us-gaap:EarningsPerShareBasic
    contextRef="c1" unitRef="usd-per-share" decimals="2"
  >3.25</us-gaap:EarningsPerShareBasic>
</xbrli:xbrl>"""
    )

    facts = parse_xbrl_instance(instance)

    assert facts[0]["unit_ref"] == "USD/xbrli:shares"


def test_raw_xbrl_preserves_typed_dimensions_with_stable_values(tmp_path):
    instance = tmp_path / "typed-dimension.xml"
    instance.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
  xmlns:us-gaap="http://fasb.org/us-gaap/2024"
  xmlns:acme="http://www.acme.example/2024"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
  <xbrli:context id="typed-context">
    <xbrli:entity>
      <xbrli:identifier scheme="test">1</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">
          acme:CloudMember
        </xbrldi:explicitMember>
        <xbrldi:typedMember dimension="acme:LegalEntityAxis">
          <acme:LegalEntityDomain>  Cloud   Subsidiary  </acme:LegalEntityDomain>
        </xbrldi:typedMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2024-03-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="U_USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <us-gaap:Assets contextRef="typed-context" unitRef="U_USD" decimals="-6">
    1000000
  </us-gaap:Assets>
</xbrli:xbrl>"""
    )

    facts = parse_xbrl_instance(instance)

    assert facts[0]["dimensions"] == {
        "us-gaap:StatementBusinessSegmentsAxis": "acme:CloudMember",
        "acme:LegalEntityAxis": (
            "{http://www.acme.example/2024}LegalEntityDomain=Cloud Subsidiary"
        ),
    }


def test_raw_fallback_marks_malformed_numeric_facts(fake_edgartools_unavailable, tmp_path):
    source = (EDGAR_FIXTURES / "instance_sample.xml").read_text()
    malformed = tmp_path / "malformed-source.xml"
    malformed.write_text(
        source.replace(
            "</xbrli:xbrl>",
            '<us-gaap:GoodwillImpairmentLoss contextRef="c-q1" '
            'unitRef="U_USD" decimals="-6">not-a-number'
            "</us-gaap:GoodwillImpairmentLoss></xbrli:xbrl>",
        )
    )
    filing = write_local_filing(tmp_path / "archive", {"malformed.xml": malformed})

    output = EdgarToolsAdapter().parse(filing)
    fact = next(
        item for item in output.facts if item.concept == "us-gaap:GoodwillImpairmentLoss"
    )

    assert fact.value_numeric is None
    assert fact.value_text == "not-a-number"
    assert any(
        diagnostic.code is DiagnosticCode.FACT_MALFORMED
        and diagnostic.relative_path == fact.evidence.relative_path
        for diagnostic in output.diagnostics
    )


def test_normalize_fact_returns_none_without_a_concept(local_filing):
    assert normalize_fact({"value": "1"}, local_filing, PARSER_VERSION) is None
    assert isinstance(
        normalize_fact({"concept": "us-gaap:Assets", "value": "1"}, local_filing, PARSER_VERSION),
        FactDraft,
    )


def test_parser_version_defaults_to_environment(monkeypatch):
    monkeypatch.delenv("FDC_PARSER_VERSION", raising=False)
    assert DEFAULT_PARSER_VERSION == "filing-parser-v1"
    assert default_parser_version() == "filing-parser-v1"

    monkeypatch.setenv("FDC_PARSER_VERSION", "filing-parser-v2")
    assert default_parser_version() == "filing-parser-v2"
    assert EdgarToolsAdapter().parser_version == "filing-parser-v2"


def test_adapter_records_the_installed_edgartools_version(fake_edgartools, local_filing):
    output = EdgarToolsAdapter().parse(local_filing)

    assert output.edgartools_version == installed_edgartools_version()
    assert output.edgartools_version is not None


def test_only_the_adapter_imports_edgartools():
    project_root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in (project_root / "src" / "fdc").rglob("*.py"):
        source = path.read_text()
        if "import edgar" in source or "from edgar" in source:
            if path.name != "edgartools_adapter.py":
                offenders.append(path.relative_to(project_root).as_posix())

    assert offenders == []


def test_real_edgartools_parses_the_checked_in_local_instance(instance_filing):
    output = EdgarToolsAdapter().parse(instance_filing)

    assert isinstance(output, ParserOutput)
    assert output.parse_mode == "edgartools-local"
    assert output.edgartools_version is not None
    assets = next(fact for fact in output.facts if fact.concept == "us-gaap:Assets")
    revenue = next(
        fact for fact in output.facts if fact.concept == "us-gaap:Revenues" and fact.dimensions
    )

    assert assets.start_date is None
    assert assets.end_date == date(2024, 3, 31)
    assert assets.period_type == "instant"
    assert revenue.dimensions == {
        "us-gaap:StatementBusinessSegmentsAxis": "acme:CloudMember",
        "srt:ProductOrServiceAxis": "acme:SubscriptionMember",
    }


REAL_PACKAGE = (
    Path(__file__).resolve().parents[2] / "sec" / "MSFT" / "10-K" / "0000950170-23-035122"
)
RUN_LOCAL_SEC_INTEGRATION = os.environ.get("FDC_RUN_LOCAL_SEC_INTEGRATION") == "1"


@pytest.mark.skipif(
    not RUN_LOCAL_SEC_INTEGRATION or not REAL_PACKAGE.is_dir(),
    reason="set FDC_RUN_LOCAL_SEC_INTEGRATION=1 with the local sec/MSFT archive available",
)
def test_real_edgartools_parses_a_repository_package(tmp_path):
    filing = write_local_filing(
        tmp_path,
        {path.name: path for path in REAL_PACKAGE.iterdir() if path.is_file()},
        ticker="MSFT",
    )
    output = EdgarToolsAdapter().parse(filing)

    assert output.status is ParseStatus.SUCCESS
    assert len(output.facts) > 500
    assert any(row.statement_type == "IncomeStatement" for row in output.statements)

    revenue = next(
        fact
        for fact in output.facts
        if fact.concept == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
        and fact.period_type == "annual"
        and fact.dimensions == {}
    )

    assert revenue.value_numeric == 211915000000.0
