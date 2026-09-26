"""Tests for deterministic, vocabulary-based disclosure classification."""

from __future__ import annotations

import pytest

from fdc.contracts import TableDraft
from fdc.parsers.disclosures import DisclosureType, classify_disclosure


@pytest.mark.parametrize(
    ("caption", "columns", "expected"),
    [
        ("Debt maturities", ("year", "principal payments"), "debt_maturity"),
        ("Lease payments due", ("period", "operating leases"), "lease_maturity"),
        (
            "Contractual obligations",
            ("period", "debt", "purchase obligations"),
            "contractual_obligation",
        ),
        ("Revenue by segment", ("segment", "2026"), "segment"),
        (
            "Disaggregation of revenue",
            ("product category", "revenue"),
            "revenue_disaggregation",
        ),
        ("Liquidity resources", ("source", "available amount"), "liquidity"),
        ("Share count", ("class", "shares"), "generic"),
    ],
)
def test_classification_uses_caption_and_column_vocabulary(caption, columns, expected):
    table = TableDraft(
        table_type="generic",
        order_index=1,
        caption=caption,
        columns=columns,
    )

    result = classify_disclosure(table)

    assert result is DisclosureType(expected)


def test_nearby_heading_context_can_classify_an_otherwise_ambiguous_table():
    table = TableDraft(
        table_type="generic",
        order_index=1,
        caption="Payments due by year",
        columns=("period", "amount"),
        period_hints={"nearby_heading": "Long-Term Debt"},
    )

    assert classify_disclosure(table) is DisclosureType.DEBT_MATURITY


def test_issuer_css_vocabulary_is_not_a_classification_input():
    table = TableDraft(
        table_type="generic",
        order_index=1,
        caption="Schedule",
        columns=("class-debt-maturity", "value"),
    )

    assert classify_disclosure(table) is DisclosureType.GENERIC
