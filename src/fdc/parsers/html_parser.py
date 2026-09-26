"""Deterministic extraction of filing sections and rendered HTML tables.

This parser reads only local bytes and uses visible document structure.  It
does not execute scripts, fetch linked assets, or rely on issuer CSS classes.
Every emitted draft carries evidence bound to the source artifact and every
present fragment carries a SHA-256 identity.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from fdc.contracts import (
    DiagnosticSeverity,
    EvidenceDraft,
    LocalFiling,
    LocatorType,
    ParserDiagnostic,
    ParserOutput,
    ParseStatus,
    RowStatus,
    SectionDraft,
    TableDraft,
)
from fdc.parsers.disclosures import DisclosureType, classify_disclosure

PARSE_MODE_HTML = "deterministic-html"
HTML_TABLE_METHOD = "html_table"
EXCERPT_LIMIT = 500

_ITEM_PATTERN = re.compile(
    r"^\s*item\s+(?P<item>\d+[a-z]?)\s*[.\-:]?\s*(?P<title>.*)$",
    re.IGNORECASE,
)
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "p", "div"})

_TEN_K_SECTIONS = {
    "1": "business",
    "1a": "risk_factors",
    "7": "md_and_a",
    "8": "financial_statements",
    "9a": "controls",
}
_TEN_Q_SECTIONS = {
    "1": "financial_statements",
    "1a": "risk_factors",
    "2": "md_and_a",
    "4": "controls",
}

_EXPECTED_TEN_K = (
    "business",
    "risk_factors",
    "md_and_a",
    "financial_statements",
    "controls",
)
_EXPECTED_TEN_Q = (
    "financial_statements",
    "md_and_a",
    "controls",
    "risk_factors",
)


@dataclass(frozen=True, slots=True)
class HtmlDocument:
    """Parsed local HTML plus the source identity needed by extractors."""

    _soup: BeautifulSoup
    filing: LocalFiling
    path: Path
    relative_path: str
    content_sha256: str


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _fragment_hash(fragment: str) -> str:
    return hashlib.sha256(fragment.encode("utf-8")).hexdigest()


def _artifact_identity(path: Path, filing: LocalFiling, content: bytes) -> tuple[str, str]:
    try:
        resolved = path.resolve()
    except OSError:  # pragma: no cover - read has already succeeded
        resolved = path.absolute()
    artifact = next(
        (
            candidate
            for candidate in filing.artifacts
            if candidate.path.resolve() == resolved
        ),
        None,
    )
    content_sha256 = hashlib.sha256(content).hexdigest()
    if artifact is not None:
        return artifact.relative_path, content_sha256
    try:
        relative_path = path.resolve().relative_to(filing.package_dir.resolve()).as_posix()
    except ValueError:
        relative_path = path.name
    return relative_path, content_sha256


def _document(path: Path, filing: LocalFiling, content: bytes) -> HtmlDocument:
    relative_path, content_sha256 = _artifact_identity(path, filing, content)
    return HtmlDocument(
        _soup=BeautifulSoup(content, "lxml"),
        filing=filing,
        path=path,
        relative_path=relative_path,
        content_sha256=content_sha256,
    )


def _item_headings(document: HtmlDocument) -> list[tuple[Tag, str]]:
    headings: list[tuple[Tag, str]] = []
    for element in document._soup.find_all(_HEADING_TAGS):
        if element.find_parent("table") is not None:
            continue
        text = _normalize_text(element.get_text(" ", strip=True))
        if not text or len(text) > 300:
            continue
        match = _ITEM_PATTERN.match(text)
        if match is not None:
            headings.append((element, match.group("item").casefold()))
    return headings


def _section_mapping(form: str) -> tuple[dict[str, str], tuple[str, ...]]:
    normalized = form.upper().removesuffix("/A")
    if normalized == "10-K":
        return _TEN_K_SECTIONS, _EXPECTED_TEN_K
    if normalized == "10-Q":
        return _TEN_Q_SECTIONS, _EXPECTED_TEN_Q
    return {}, ()


def _is_descendant(node: Tag, ancestor: Tag) -> bool:
    return any(parent is ancestor for parent in node.parents)


def _section_text(heading: Tag, next_heading: Tag | None) -> str:
    pieces: list[str] = []
    for element in heading.next_elements:
        if next_heading is not None and element is next_heading:
            break
        if not isinstance(element, NavigableString):
            continue
        if any(parent.name in {"script", "style"} for parent in element.parents):
            continue
        if any(parent is heading for parent in element.parents):
            continue
        text = _normalize_text(element)
        if text:
            pieces.append(text)
    return _normalize_text(" ".join(pieces))


def _contains(container: Tag, target: Tag) -> bool:
    return container is target or any(descendant is target for descendant in container.descendants)


def _section_fragment(heading: Tag, next_heading: Tag | None) -> str:
    fragments = [str(heading)]
    for sibling in heading.next_siblings:
        if (
            isinstance(sibling, Tag)
            and next_heading is not None
            and _contains(sibling, next_heading)
        ):
            break
        if sibling is next_heading:
            break
        rendered = str(sibling).strip()
        if rendered:
            fragments.append(rendered)
    return "\n".join(fragments)


def _section_evidence(
    document: HtmlDocument,
    heading: Tag | None,
    section_type: str,
    excerpt: str | None,
) -> EvidenceDraft:
    html_id = _normalize_text(heading.get("id")) if heading is not None else ""
    if html_id:
        locator_type = LocatorType.HTML_ID
        locator_value = html_id
    elif heading is not None:
        locator_type = LocatorType.HEADING
        locator_value = _normalize_text(heading.get_text(" ", strip=True))
    else:
        locator_type = LocatorType.HEADING
        locator_value = f"missing:{section_type}"
    return EvidenceDraft(
        locator_type=locator_type,
        locator_value=locator_value,
        relative_path=document.relative_path,
        content_sha256=document.content_sha256,
        excerpt=excerpt[:EXCERPT_LIMIT] if excerpt else None,
    )


def extract_sections(document: HtmlDocument) -> list[SectionDraft]:
    """Extract standard 10-K/10-Q item sections in document order."""

    mapping, expected = _section_mapping(document.filing.form)
    headings = _item_headings(document)
    sections: list[SectionDraft] = []
    seen_types: set[str] = set()

    for index, (heading, item) in enumerate(headings):
        section_type = mapping.get(item)
        if section_type is None:
            continue
        next_heading = headings[index + 1][0] if index + 1 < len(headings) else None
        text = _section_text(heading, next_heading)
        fragment = _section_fragment(heading, next_heading)
        sections.append(
            SectionDraft(
                section_type=section_type,
                order_index=len(sections) + 1,
                heading=_normalize_text(heading.get_text(" ", strip=True)),
                text=text or None,
                status=RowStatus.PARSED,
                raw_fragment=fragment,
                raw_fragment_hash=_fragment_hash(fragment),
                evidence=_section_evidence(document, heading, section_type, text),
            )
        )
        seen_types.add(section_type)

    for section_type in expected:
        if section_type in seen_types:
            continue
        diagnostic = ParserDiagnostic(
            code="HTML_SECTION_UNAVAILABLE",
            detail=f"{section_type} heading was not found in the local HTML document",
            scope=section_type,
            relative_path=document.relative_path,
            severity=DiagnosticSeverity.WARNING,
        )
        sections.append(
            SectionDraft(
                section_type=section_type,
                order_index=len(sections) + 1,
                status=RowStatus.UNAVAILABLE,
                diagnostics=(diagnostic,),
                evidence=_section_evidence(document, None, section_type, None),
            )
        )
    return sections


def _nearby_context(table: Tag) -> tuple[str | None, str | None]:
    caption_element = table.find("caption")
    caption = (
        _normalize_text(caption_element.get_text(" ", strip=True))
        if caption_element is not None
        else None
    )
    heading_element = table.find_previous(tuple(f"h{level}" for level in range(1, 7)))
    nearby_heading = (
        _normalize_text(heading_element.get_text(" ", strip=True))
        if heading_element is not None
        else None
    )
    if caption is None:
        paragraph = table.find_previous("p")
        if paragraph is not None:
            caption = _normalize_text(paragraph.get_text(" ", strip=True)) or None
    return caption, nearby_heading


def _expanded_cells(row: Tag) -> list[str]:
    values: list[str] = []
    for cell in row.find_all(("th", "td"), recursive=False):
        value = _normalize_text(cell.get_text(" ", strip=True))
        try:
            colspan = max(1, int(cell.get("colspan", 1)))
        except (TypeError, ValueError):
            colspan = 1
        values.extend([value] * colspan)
    return values


def _column_name(label: str, index: int) -> str:
    lowered = _normalize_text(label).casefold()
    if lowered in {"year", "period", "maturity", "maturity year", "payments due"}:
        return "period"
    if any(term in lowered for term in ("principal", "amount", "total payment", "payments")):
        return "amount"
    normalized = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return normalized or f"column_{index + 1}"


def _unique_columns(labels: list[str]) -> tuple[str, ...]:
    columns: list[str] = []
    counts: dict[str, int] = {}
    for index, label in enumerate(labels):
        base = _column_name(label, index)
        counts[base] = counts.get(base, 0) + 1
        columns.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return tuple(columns)


def _unit_hint(context: str) -> str | None:
    match = re.search(r"\bin\s+(thousands|millions|billions)\b", context, re.IGNORECASE)
    return match.group(1).casefold() if match else None


def _table_evidence(
    document: HtmlDocument,
    table: Tag,
    order_index: int,
    excerpt: str,
) -> EvidenceDraft:
    html_id = _normalize_text(table.get("id"))
    return EvidenceDraft(
        locator_type=LocatorType.HTML_ID if html_id else LocatorType.TABLE_CELL,
        locator_value=html_id or f"table:{order_index}",
        relative_path=document.relative_path,
        content_sha256=document.content_sha256,
        excerpt=excerpt[:EXCERPT_LIMIT] or None,
    )


def _confidence(disclosure_type: DisclosureType) -> float:
    return 0.5 if disclosure_type is DisclosureType.GENERIC else 0.95


def extract_tables(document: HtmlDocument) -> list[TableDraft]:
    """Extract all tables, retaining failed tables with scoped diagnostics."""

    drafts: list[TableDraft] = []
    for order_index, table in enumerate(document._soup.find_all("table"), start=1):
        fragment = str(table)
        caption, nearby_heading = _nearby_context(table)
        row_elements = table.find_all("tr")
        matrix = [_expanded_cells(row) for row in row_elements]
        matrix = [row for row in matrix if row]
        diagnostics: list[ParserDiagnostic] = []

        if not matrix:
            original_columns: list[str] = []
            columns: tuple[str, ...] = ()
            normalized_rows: tuple[dict[str, Any], ...] = ()
            diagnostics.append(
                ParserDiagnostic(
                    code="MALFORMED_HTML_TABLE",
                    detail="table has no rows with th/td cells",
                    scope=f"table:{order_index}",
                    relative_path=document.relative_path,
                    severity=DiagnosticSeverity.ERROR,
                )
            )
        else:
            original_columns = matrix[0]
            columns = _unique_columns(original_columns)
            expected_width = len(columns)
            normalized: list[dict[str, Any]] = []
            for source_row_index, row in enumerate(matrix[1:], start=2):
                if len(row) != expected_width:
                    diagnostics.append(
                        ParserDiagnostic(
                            code="MALFORMED_HTML_TABLE",
                            detail=(
                                f"row {source_row_index} has {len(row)} cells; "
                                f"expected {expected_width}"
                            ),
                            scope=f"table:{order_index}",
                            relative_path=document.relative_path,
                            severity=DiagnosticSeverity.ERROR,
                        )
                    )
                padded = (row + [""] * expected_width)[:expected_width]
                normalized.append(dict(zip(columns, padded, strict=True)))
            normalized_rows = tuple(normalized)

        context = " ".join(
            part
            for part in (
                caption,
                nearby_heading,
                _normalize_text(table.find_previous("p").get_text(" ", strip=True))
                if table.find_previous("p") is not None
                else None,
            )
            if part
        )
        hints: dict[str, Any] = {}
        if nearby_heading:
            hints["nearby_heading"] = nearby_heading
        hints["original_columns"] = original_columns
        periods = [
            str(row["period"])
            for row in normalized_rows
            if re.fullmatch(r"(?:19|20)\d{2}", str(row.get("period", "")))
        ]
        if periods:
            hints["periods"] = periods
        unit = _unit_hint(context)
        if unit:
            hints["unit"] = unit

        status = RowStatus.FAILED if diagnostics else RowStatus.PARSED
        excerpt = _normalize_text(table.get_text(" ", strip=True))
        generic = TableDraft(
            table_type=DisclosureType.GENERIC,
            order_index=order_index,
            caption=caption,
            columns=columns,
            rows=normalized_rows,
            period_hints=hints,
            extraction_method=HTML_TABLE_METHOD,
            confidence=None,
            status=status,
            raw_fragment=fragment,
            raw_fragment_hash=_fragment_hash(fragment),
            diagnostics=tuple(diagnostics),
            evidence=_table_evidence(document, table, order_index, excerpt),
        )
        disclosure_type = classify_disclosure(generic)
        drafts.append(
            replace(
                generic,
                table_type=disclosure_type,
                confidence=_confidence(disclosure_type),
            )
        )
    return drafts


def parse_html_document(
    path: Path,
    filing: LocalFiling,
    parser_version: str,
) -> ParserOutput:
    """Parse one local HTML document into narrative and table contracts."""

    try:
        content = path.read_bytes()
    except OSError as error:
        return ParserOutput(
            status=ParseStatus.FAILED,
            parser_version=parser_version,
            parse_mode=PARSE_MODE_HTML,
            diagnostics=[
                ParserDiagnostic(
                    code="UNREADABLE_ARTIFACT",
                    detail=f"could not read local HTML artifact: {error}",
                    scope="html_document",
                    relative_path=str(path),
                    severity=DiagnosticSeverity.ERROR,
                )
            ],
        )

    document = _document(path, filing, content)
    sections = extract_sections(document)
    tables = extract_tables(document)
    diagnostics = [
        diagnostic
        for draft in [*sections, *tables]
        for diagnostic in draft.diagnostics
    ]
    has_unavailable_section = any(section.status is RowStatus.UNAVAILABLE for section in sections)
    has_failed_table = any(table.status is RowStatus.FAILED for table in tables)
    status = (
        ParseStatus.PARTIAL
        if has_unavailable_section or has_failed_table
        else ParseStatus.SUCCESS
    )
    evidence = [
        draft.evidence
        for draft in [*sections, *tables]
        if draft.evidence is not None
    ]
    return ParserOutput(
        status=status,
        parser_version=parser_version,
        parse_mode=PARSE_MODE_HTML,
        sections=sections,
        tables=tables,
        evidence=evidence,
        diagnostics=diagnostics,
    )
