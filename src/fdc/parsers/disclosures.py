"""Typed classification for tables extracted from filing HTML.

Classification deliberately uses visible disclosure vocabulary only.  Issuer
CSS classes and ids are not part of :class:`~fdc.contracts.TableDraft`, so a
change in presentation markup cannot change a table's semantic type.
"""

from __future__ import annotations

import re
from enum import StrEnum

from fdc.contracts import TableDraft


class DisclosureType(StrEnum):
    """Stable disclosure categories stored by the parsing platform."""

    DEBT_MATURITY = "debt_maturity"
    LEASE_MATURITY = "lease_maturity"
    CONTRACTUAL_OBLIGATION = "contractual_obligation"
    SEGMENT = "segment"
    REVENUE_DISAGGREGATION = "revenue_disaggregation"
    LIQUIDITY = "liquidity"
    GENERIC = "generic"


def _words(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def _has_any(value: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in value for phrase in phrases)


def classify_disclosure(table: TableDraft) -> DisclosureType:
    """Classify a normalized table from caption, heading, and column terms.

    The rules are ordered from the most specific schedules to broader
    categories.  Unknown tables remain ``generic``; no type is inferred from
    an issuer-specific id or CSS class.
    """

    caption = _words(table.caption)
    nearby_heading = _words(table.period_hints.get("nearby_heading"))
    visible_context = " ".join(part for part in (caption, nearby_heading) if part)
    original_columns = table.period_hints.get("original_columns")
    if isinstance(original_columns, list | tuple):
        columns = tuple(_words(column) for column in original_columns)
    else:
        columns = tuple(_words(column) for column in table.columns)
    column_text = " ".join(columns)
    all_text = " ".join(part for part in (visible_context, column_text) if part)

    if "contractual obligation" in visible_context:
        return DisclosureType.CONTRACTUAL_OBLIGATION

    debt_anchor = _has_any(
        visible_context,
        ("debt", "borrowings", "notes payable", "senior notes"),
    ) or any(
        column in {"debt", "borrowings", "principal payments"}
        or column.endswith(" debt")
        or column.startswith("debt ")
        for column in columns
    )
    maturity_terms = _has_any(
        all_text,
        ("matur", "payments due", "due by", "principal payment", "thereafter"),
    )
    lease_anchor = "lease" in visible_context or any(
        column in {"lease", "lease payments", "operating leases", "finance leases"}
        for column in columns
    )

    if debt_anchor and maturity_terms:
        return DisclosureType.DEBT_MATURITY
    if lease_anchor and maturity_terms:
        return DisclosureType.LEASE_MATURITY

    segment_anchor = "segment" in visible_context or "segment" in columns
    if segment_anchor:
        return DisclosureType.SEGMENT

    revenue_anchor = "revenue" in all_text
    disaggregation_anchor = _has_any(
        visible_context,
        ("disaggregation", "by product", "by geography", "by category", "by customer"),
    ) or any(
        column in {"product", "product category", "geography", "category", "customer type"}
        for column in columns
    )
    if revenue_anchor and disaggregation_anchor:
        return DisclosureType.REVENUE_DISAGGREGATION

    if _has_any(
        visible_context,
        ("liquidity", "liquid resources", "sources of liquidity", "available liquidity"),
    ):
        return DisclosureType.LIQUIDITY
    return DisclosureType.GENERIC
