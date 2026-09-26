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
_PART_PATTERN = re.compile(r"^\s*part\s+(?P<part>i{1,2})\b", re.IGNORECASE)
_HEADING_TAGS = frozenset(
    {"h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "td", "th"}
)

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


@dataclass(frozen=True, slots=True)
class _HeadingCandidate:
    element: Tag
    item: str
    title: str
    part: str | None
    source_index: int


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


def _is_visible_presentation_heading(element: Tag) -> bool:
    table = element.find_parent("table")
    if table is None:
        return True
    cell = element if element.name in {"td", "th"} else element.find_parent(("td", "th"))
    if cell is None:
        return False
    row = cell.find_parent("tr")
    if row is None:
        return False
    visible_cells = [
        candidate
        for candidate in row.find_all(("td", "th"), recursive=False)
        if _normalize_text(candidate.get_text(" ", strip=True))
    ]
    return (
        len(visible_cells) == 1
        and visible_cells[0] is cell
        and _normalize_text(cell.get_text(" ", strip=True))
        == _normalize_text(element.get_text(" ", strip=True))
    )


def _raw_item_elements(document: HtmlDocument) -> list[tuple[Tag, re.Match[str]]]:
    matches: list[tuple[Tag, re.Match[str]]] = []
    for element in document._soup.find_all(_HEADING_TAGS):
        if not _is_visible_presentation_heading(element):
            continue
        text = _normalize_text(element.get_text(" ", strip=True))
        if not text or len(text) > 300:
            continue
        match = _ITEM_PATTERN.match(text)
        if match is not None:
            matches.append((element, match))
    return matches


def _item_headings(document: HtmlDocument) -> list[_HeadingCandidate]:
    raw_matches = _raw_item_elements(document)
    raw_elements = [element for element, _ in raw_matches]
    headings: list[_HeadingCandidate] = []
    current_part: str | None = None
    source_index = 0

    for element in document._soup.find_all(_HEADING_TAGS):
        if not _is_visible_presentation_heading(element):
            continue
        text = _normalize_text(element.get_text(" ", strip=True))
        part_match = _PART_PATTERN.match(text)
        if part_match is not None:
            current_part = part_match.group("part").upper()

        match = next(
            (candidate_match for candidate, candidate_match in raw_matches if candidate is element),
            None,
        )
        if match is None:
            continue
        if any(
            candidate is not element
            and any(parent is element for parent in candidate.parents)
            and _normalize_text(candidate.get_text(" ", strip=True)) == text
            for candidate in raw_elements
        ):
            continue
        headings.append(
            _HeadingCandidate(
                element=element,
                item=match.group("item").casefold(),
                title=_normalize_text(match.group("title")).casefold(),
                part=current_part,
                source_index=source_index,
            )
        )
        source_index += 1
    return headings


def _section_boundaries(
    document: HtmlDocument,
    headings: list[_HeadingCandidate],
) -> list[Tag]:
    """Return Item and Part headings in source order as hard text boundaries."""

    item_elements = {id(heading.element) for heading in headings}
    boundaries: list[Tag] = []
    for element in document._soup.find_all(_HEADING_TAGS):
        if not _is_visible_presentation_heading(element):
            continue
        text = _normalize_text(element.get_text(" ", strip=True))
        if id(element) in item_elements or (
            text and len(text) <= 300 and _PART_PATTERN.match(text) is not None
        ):
            boundaries.append(element)
    return boundaries


def _section_mapping(form: str) -> tuple[dict[str, str], tuple[str, ...]]:
    normalized = form.upper().removesuffix("/A")
    if normalized == "10-K":
        return _TEN_K_SECTIONS, _EXPECTED_TEN_K
    if normalized == "10-Q":
        return _TEN_Q_SECTIONS, _EXPECTED_TEN_Q
    return {}, ()


def _section_type(form: str, heading: _HeadingCandidate) -> str | None:
    normalized = form.upper().removesuffix("/A")
    if normalized == "10-K":
        return _TEN_K_SECTIONS.get(heading.item)
    if normalized != "10-Q":
        return None

    title = heading.title
    part = heading.part
    if heading.item == "1a" and (part == "II" or "risk factor" in title):
        return "risk_factors"
    if heading.item == "1" and (part == "I" or "financial statement" in title):
        return "financial_statements"
    if heading.item == "2" and part != "II" and (
        part == "I"
        or "management's discussion" in title
        or "management discussion" in title
    ):
        return "md_and_a"
    if heading.item == "4" and part != "II" and (
        part == "I" or "controls and procedures" in title
    ):
        return "controls"
    return None


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
    if not mapping:
        diagnostic = ParserDiagnostic(
            code="HTML_FORM_UNSUPPORTED",
            detail=f"HTML section extraction does not support form {document.filing.form}",
            scope="sections",
            relative_path=document.relative_path,
            severity=DiagnosticSeverity.WARNING,
        )
        return [
            SectionDraft(
                section_type="unsupported",
                order_index=1,
                status=RowStatus.UNSUPPORTED,
                diagnostics=(diagnostic,),
                evidence=EvidenceDraft(
                    locator_type=LocatorType.HEADING,
                    locator_value=f"unsupported-form:{document.filing.form}",
                    relative_path=document.relative_path,
                    content_sha256=document.content_sha256,
                ),
            )
        ]

    headings = _item_headings(document)
    boundaries = _section_boundaries(document, headings)
    boundary_positions = {id(element): index for index, element in enumerate(boundaries)}
    selected: dict[str, tuple[_HeadingCandidate, str, str]] = {}

    for heading in headings:
        section_type = _section_type(document.filing.form, heading)
        if section_type is None:
            continue
        boundary_index = boundary_positions[id(heading.element)]
        next_boundary = (
            boundaries[boundary_index + 1]
            if boundary_index + 1 < len(boundaries)
            else None
        )
        text = _section_text(heading.element, next_boundary)
        fragment = _section_fragment(heading.element, next_boundary)
        previous = selected.get(section_type)
        if previous is None or len(text) >= len(previous[1]):
            selected[section_type] = (heading, text, fragment)

    sections: list[SectionDraft] = []
    for section_type, (heading, text, fragment) in sorted(
        selected.items(), key=lambda item: item[1][0].source_index
    ):
        sections.append(
            SectionDraft(
                section_type=section_type,
                order_index=len(sections) + 1,
                heading=_normalize_text(heading.element.get_text(" ", strip=True)),
                text=text or None,
                status=RowStatus.PARSED,
                raw_fragment=fragment,
                raw_fragment_hash=_fragment_hash(fragment),
                evidence=_section_evidence(
                    document,
                    heading.element,
                    section_type,
                    text,
                ),
            )
        )

    for section_type in expected:
        if section_type in selected:
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


def _row_is_explicit_header(row: Tag) -> bool:
    cells = row.find_all(("th", "td"), recursive=False)
    return bool(cells) and (
        row.find_parent("thead") is not None or all(cell.name == "th" for cell in cells)
    )


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
        parsed_rows = [
            (row, cells)
            for row in row_elements
            if (cells := _expanded_cells(row))
        ]
        matrix = [cells for _, cells in parsed_rows]
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
            has_explicit_header = _row_is_explicit_header(parsed_rows[0][0])
            original_columns = matrix[0] if has_explicit_header else []
            data_matrix = matrix[1:] if has_explicit_header else matrix
            if has_explicit_header:
                columns = _unique_columns(original_columns)
            else:
                columns = tuple(f"column_{index + 1}" for index in range(len(matrix[0])))
                diagnostics.append(
                    ParserDiagnostic(
                        code="UNSUPPORTED_HTML_TABLE",
                        detail="table has no explicit header row; positional columns were retained",
                        scope=f"table:{order_index}",
                        relative_path=document.relative_path,
                        severity=DiagnosticSeverity.WARNING,
                    )
                )
            expected_width = len(columns)
            normalized: list[dict[str, Any]] = []
            for source_row_index, row in enumerate(
                data_matrix,
                start=2 if has_explicit_header else 1,
            ):
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
            if has_explicit_header and not normalized_rows:
                diagnostics.append(
                    ParserDiagnostic(
                        code="MALFORMED_HTML_TABLE",
                        detail="table has a header row but no data rows",
                        scope=f"table:{order_index}",
                        relative_path=document.relative_path,
                        severity=DiagnosticSeverity.ERROR,
                    )
                )

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

        has_malformed_diagnostic = any(
            diagnostic.code == "MALFORMED_HTML_TABLE" for diagnostic in diagnostics
        )
        has_unsupported_diagnostic = any(
            diagnostic.code == "UNSUPPORTED_HTML_TABLE" for diagnostic in diagnostics
        )
        if has_malformed_diagnostic:
            status = RowStatus.FAILED
        elif has_unsupported_diagnostic:
            status = RowStatus.UNSUPPORTED
        else:
            status = RowStatus.PARSED
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
    has_nonparsed_section = any(section.status is not RowStatus.PARSED for section in sections)
    has_nonparsed_table = any(table.status is not RowStatus.PARSED for table in tables)
    status = (
        ParseStatus.PARTIAL
        if has_nonparsed_section or has_nonparsed_table
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
