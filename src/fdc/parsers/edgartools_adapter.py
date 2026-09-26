"""EdgarTools adapter: normalize local XBRL into parser contracts.

EdgarTools is the standard-data adapter of the parsing platform.  This module
is the only place that imports it: it opens a filing package with
``XBRL.from_directory``, reads the dict-shaped facts and statement rows that
release exposes, and emits :mod:`fdc.contracts` drafts so the database layer
never depends on EdgarTools model classes.

When the installed release cannot open a local package, the adapter falls back
to parsing the downloaded XBRL instances itself (classic and inline XBRL) and
records ``mode="raw-xbrl-fallback"`` in the parse output, so a fallback is
always visible rather than silently degraded.
"""

from __future__ import annotations

import importlib.metadata
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from fdc.contracts import (
    DiagnosticCode,
    DiagnosticSeverity,
    EvidenceDraft,
    FactDraft,
    LocalFiling,
    LocatorType,
    ParserDiagnostic,
    ParserOutput,
    ParseStatus,
    StatementDraft,
)

#: Parser version used when ``FDC_PARSER_VERSION`` is not configured.
DEFAULT_PARSER_VERSION = "filing-parser-v1"

#: Primary statements normalized into ``statement_line`` rows.
DEFAULT_STATEMENT_TYPES: tuple[str, ...] = (
    "IncomeStatement",
    "BalanceSheet",
    "CashFlowStatement",
    "StatementOfEquity",
    "ComprehensiveIncome",
)

PARSE_MODE_EDGARTOOLS = "edgartools-local"
PARSE_MODE_RAW_XBRL = "raw-xbrl-fallback"

EDGARTOOLS_FACT_METHOD = "edgartools_fact"
RAW_XBRL_FACT_METHOD = "raw_xbrl_instance"

PeriodTypeLiteral = Literal["instant", "quarter", "annual", "ytd", "other"]

XBRLI_NS = "http://www.xbrl.org/2003/instance"
XBRLDI_NS = "http://xbrl.org/2006/xbrldi"
INLINE_XBRL_NAMESPACES = (
    "http://www.xbrl.org/2013/inlineXBRL",
    "http://www.xbrl.org/2008/inlineXBRL",
)

#: Linkbase files that are not instance documents.
LINKBASE_SUFFIXES = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml")

#: Markers that identify a file as an XBRL instance document.
INSTANCE_MARKERS = ("<xbrli:xbrl", "<ix:", "nonfraction", "nonnumeric")

#: Bytes read when sniffing whether an artifact is an XBRL instance.
SNIFF_BYTES = 8192

#: Character budget kept as an evidence excerpt.
EXCERPT_LIMIT = 500

XbrlOpener = Callable[[Path], Any]


def installed_edgartools_version() -> str | None:
    """Return the pinned EdgarTools version, or ``None`` when not installed."""

    try:
        return importlib.metadata.version("edgartools")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - env specific
        return None


def default_parser_version() -> str:
    """Parser version: ``FDC_PARSER_VERSION`` when set, else the pinned default."""

    override = os.environ.get("FDC_PARSER_VERSION", "").strip()
    return override or DEFAULT_PARSER_VERSION


def xbrl_from_directory(directory: Path) -> Any:
    """Open a local XBRL package with the installed EdgarTools release.

    The import stays inside this function so importing :mod:`fdc.parsers` never
    requires EdgarTools, and so a missing dependency is a parse-time error
    instead of an import-time one.
    """

    from edgar.xbrl import XBRL

    return XBRL.from_directory(directory)


def period_type(start: date | None, end: date | None) -> PeriodTypeLiteral:
    """Classify a fact period from its start and end dates.

    An instant has no start date, a quarter covers up to ~100 days, a year at
    least 300 days, and everything in between — including a nine-month
    year-to-date — stays ``ytd`` so it is never reported as a quarter.
    """

    if end is None:
        return "other"
    if start is None:
        return "instant"
    days = (end - start).days + 1
    if days >= 300:
        return "annual"
    if days <= 100:
        return "quarter"
    return "ytd"


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    if number is None:
        return None
    try:
        return int(number)
    except (OverflowError, ValueError):  # pragma: no cover - defensive
        return None


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _clean_str(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _namespace_of(concept: str) -> str | None:
    prefix, separator, _ = concept.partition(":")
    return prefix if separator else None


def _unit_of(raw_fact: Mapping[str, Any]) -> str | None:
    for key in ("currency", "unit_ref"):
        unit = _clean_str(raw_fact.get(key))
        if unit is not None:
            return unit.removeprefix("U_")
    return None


def _dimensions_of(raw_fact: Mapping[str, Any]) -> dict[str, str]:
    """Return the axis/member map of a raw fact.

    EdgarTools reports the primary dimension as ``dimension``/``member``; extra
    ``dim_*`` axes of exotic facts are not reconstructed because their names
    cannot be split back into prefixed QNames reliably.
    """

    axis = _clean_str(raw_fact.get("dimension"))
    member = _clean_str(raw_fact.get("member"))
    if axis is None or member is None:
        return {}
    return {axis: member}


def _evidence_for(
    filing: LocalFiling,
    *,
    locator_value: str,
    excerpt: str | None,
) -> EvidenceDraft:
    """Build an XBRL-fact locator pointing at the filing's primary document."""

    primary = filing.primary_artifact
    return EvidenceDraft(
        locator_type=LocatorType.XBRL_FACT,
        locator_value=locator_value,
        relative_path=filing.primary_relative_path,
        # The accession URL needs the issuer CIK, which the persistence layer
        # owns; the scanner deliberately does not read company metadata.
        accession_url=None,
        content_sha256=primary.sha256 if primary is not None else None,
        excerpt=excerpt[:EXCERPT_LIMIT] if excerpt else None,
    )


def normalize_fact(
    raw_fact: Mapping[str, Any],
    filing: LocalFiling,
    parser_version: str,
    *,
    extraction_method: str = EDGARTOOLS_FACT_METHOD,
) -> FactDraft | None:
    """Normalize one raw fact into a :class:`FactDraft`.

    Returns ``None`` only when the raw fact has no concept: such a fact cannot be
    tagged, located or queried, so the caller records a ``FACT_MALFORMED``
    diagnostic instead of storing an anonymous number.
    """

    concept = _clean_str(raw_fact.get("concept"))
    if concept is None:
        return None

    start = _to_date(raw_fact.get("period_start"))
    end = _to_date(raw_fact.get("period_end"))
    numeric = _to_float(raw_fact.get("numeric_value"))
    if numeric is None:
        numeric = _to_float(raw_fact.get("value")) if _unit_of(raw_fact) else None
    raw_value = _clean_str(raw_fact.get("value"))

    return FactDraft(
        concept=concept,
        concept_namespace=_namespace_of(concept),
        label=_clean_str(raw_fact.get("label")) or _clean_str(raw_fact.get("original_label")),
        value_numeric=numeric,
        value_text=None if numeric is not None else raw_value,
        unit=_unit_of(raw_fact),
        decimals=_to_int(raw_fact.get("decimals")),
        start_date=start,
        end_date=end,
        period_type=period_type(start, end),
        dimensions=_dimensions_of(raw_fact),
        extraction_method=extraction_method,
        evidence=_evidence_for(filing, locator_value=concept, excerpt=raw_value),
    )


def _fact_is_malformed(raw_fact: Mapping[str, Any], draft: FactDraft) -> bool:
    """True when a fact looked numeric but carried no usable number."""

    if draft.value_numeric is not None:
        return False
    expected_numeric = bool(_clean_str(raw_fact.get("unit_ref"))) or (
        raw_fact.get("numeric_value") is not None
    )
    return expected_numeric


def _period_bounds(period_key: str) -> tuple[date | None, date | None]:
    """Parse an EdgarTools period key such as ``duration_2024-01-01_2024-03-31``."""

    parts = period_key.split("_")
    if parts[0] == "instant" and len(parts) >= 2:
        return None, _to_date(parts[1])
    if parts[0] == "duration" and len(parts) >= 3:
        return _to_date(parts[1]), _to_date(parts[2])
    return None, None


def _period_sort_key(period_key: str) -> tuple[date, date]:
    start, end = _period_bounds(period_key)
    return (end or date.min, start or date.min)


def _ordered_period_keys(values: Mapping[str, Any]) -> list[str]:
    """Return period keys newest period first, independent of dict order."""

    return sorted((str(key) for key in values), key=_period_sort_key, reverse=True)


def _normalize_concept_name(name: str | None) -> str | None:
    """Turn EdgarTools' ``us-gaap_Revenue`` into the ``us-gaap:Revenue`` QName."""

    if name is None:
        return None
    prefix, separator, local = name.partition("_")
    if not separator:
        return name
    return f"{prefix}:{local}"


def _normalize_unit_ref(unit_ref: Any) -> str | None:
    unit = _clean_str(unit_ref)
    return None if unit is None else unit.removeprefix("U_")


def normalize_statement_rows(
    rows: Iterable[Any],
    *,
    statement_type: str,
    filing: LocalFiling,
    parser_version: str,
) -> list[StatementDraft]:
    """Expand presentation rows into one draft per valued period.

    EdgarTools returns one row per line item with a ``values`` map keyed by
    period; the database stores one row per period, so each value becomes its own
    draft.  Abstract rows without values are presentation scaffolding and are
    skipped.
    """

    drafts: list[StatementDraft] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        values = row.get("values")
        if not isinstance(values, Mapping) or not values:
            continue
        units = row.get("units") if isinstance(row.get("units"), Mapping) else {}
        concept = _normalize_concept_name(_clean_str(row.get("concept")))
        label = _clean_str(row.get("label"))

        for period_position, period_key in enumerate(_ordered_period_keys(values)):
            start, end = _period_bounds(period_key)
            value = values[period_key]
            drafts.append(
                StatementDraft(
                    statement_type=statement_type,
                    order_index=row_index * 100 + period_position,
                    label=label,
                    section=_normalize_concept_name(_clean_str(row.get("parent"))),
                    depth=_to_int(row.get("level")) or 0,
                    concept=concept,
                    value_numeric=_to_float(value),
                    unit=_normalize_unit_ref(units.get(period_key)),
                    start_date=start,
                    end_date=end,
                    period_type=period_type(start, end),
                    evidence=_evidence_for(
                        filing,
                        locator_value=concept or f"{statement_type}:{label or row_index}",
                        excerpt=str(value),
                    ),
                )
            )
    return drafts


def _xml_qname(element) -> Any:
    """Return the element QName, or ``None`` for comments and processing instructions."""

    if not isinstance(element.tag, str):  # comments and PIs have callable tags
        return None
    from lxml import etree

    return etree.QName(element)


def _iter_elements(root):
    for element in root.iter():
        qname = _xml_qname(element)
        if qname is not None:
            yield element, qname


def _parse_contexts(root) -> dict[str, dict[str, Any]]:
    """Map context ids to periods and explicit dimensions."""

    contexts: dict[str, dict[str, Any]] = {}
    for element, qname in _iter_elements(root):
        if qname.namespace != XBRLI_NS or qname.localname != "context":
            continue
        context_id = element.get("id")
        if not context_id:
            continue
        start = end = instant = None
        dimensions: dict[str, str] = {}
        for child, child_qname in _iter_elements(element):
            if child_qname.namespace == XBRLI_NS:
                if child_qname.localname == "startDate":
                    start = _to_date(child.text)
                elif child_qname.localname == "endDate":
                    end = _to_date(child.text)
                elif child_qname.localname == "instant":
                    instant = _to_date(child.text)
            elif child_qname.namespace == XBRLDI_NS and child_qname.localname == "explicitMember":
                axis = _clean_str(child.get("dimension"))
                member = _clean_str(child.text)
                if axis is not None and member is not None:
                    dimensions[axis] = member
        contexts[context_id] = {
            "start": start,
            "end": end if end is not None else instant,
            "instant": instant,
            "dimensions": dimensions,
        }
    return contexts


def _parse_units(root) -> dict[str, str]:
    """Map unit ids to their primary measure, e.g. ``U_USD`` -> ``USD``."""

    units: dict[str, str] = {}
    for element, qname in _iter_elements(root):
        if qname.namespace != XBRLI_NS or qname.localname != "unit":
            continue
        unit_id = element.get("id")
        if not unit_id:
            continue
        measures = [
            _clean_str(child.text)
            for child, child_qname in _iter_elements(element)
            if child_qname.localname == "measure"
        ]
        measure = next((item for item in measures if item), None)
        if measure is None:
            continue
        # ``iso4217:USD`` -> ``USD``; divisional units keep their shape.
        units[unit_id] = measure.partition(":")[2] if measure.startswith("iso4217:") else measure
    return units


def _raw_fact(
    *,
    concept: str,
    value: str | None,
    numeric_value: float | None,
    unit_ref: str | None,
    decimals: str | None,
    context_ref: str | None,
    context: Mapping[str, Any] | None,
    fact_id: str | None,
) -> dict[str, Any]:
    """Shape a parsed XBRL fact like an EdgarTools ``get_facts()`` entry."""

    start = context.get("start") if context else None
    end = context.get("end") if context else None
    dimensions = context.get("dimensions") if context else {}
    is_dimensioned = bool(dimensions)
    axis = next(iter(dimensions)) if is_dimensioned else None
    return {
        "concept": concept,
        "value": value,
        "numeric_value": numeric_value,
        "unit_ref": unit_ref,
        "currency": None,
        "decimals": decimals,
        "period_type": "instant" if start is None else "duration",
        "period_start": start.isoformat() if start else None,
        "period_end": end.isoformat() if end else None,
        "is_dimensioned": is_dimensioned,
        "dimension": axis,
        "member": dimensions.get(axis) if is_dimensioned else None,
        "label": None,
        "original_label": None,
        "fact_id": fact_id,
        "context_ref": context_ref,
    }


def _numeric_text(text: str, scale: str | None, sign: str | None) -> float | None:
    number = _to_float(text)
    if number is None:
        return None
    factor = 10 ** (_to_int(scale) or 0)
    number *= factor
    if sign == "-":
        number = -number
    return number


def _parse_classic_facts(
    root,
    contexts: Mapping[str, Mapping[str, Any]],
    units: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Extract facts tagged with real namespaces (``us-gaap:Revenues`` and co.)."""

    facts: list[dict[str, Any]] = []
    for element, qname in _iter_elements(root):
        context_ref = element.get("contextRef")
        if context_ref is None:
            continue
        if qname.namespace in (XBRLI_NS, XBRLDI_NS) or qname.namespace in INLINE_XBRL_NAMESPACES:
            continue
        prefix = element.prefix
        concept = f"{prefix}:{qname.localname}" if prefix else qname.localname
        context = contexts.get(context_ref)
        text = _clean_str("".join(element.itertext()))
        unit_id = element.get("unitRef")
        facts.append(
            _raw_fact(
                concept=concept,
                value=text,
                numeric_value=_to_float(text),
                unit_ref=units.get(unit_id, unit_id),
                decimals=element.get("decimals"),
                context_ref=context_ref,
                context=context,
                fact_id=element.get("id"),
            )
        )
    return facts


def _parse_inline_facts(
    root,
    contexts: Mapping[str, Mapping[str, Any]],
    units: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Extract inline XBRL ``ix:nonFraction``/``ix:nonNumeric`` facts."""

    facts: list[dict[str, Any]] = []
    for element, qname in _iter_elements(root):
        if qname.namespace not in INLINE_XBRL_NAMESPACES:
            continue
        if qname.localname not in ("nonFraction", "nonNumeric"):
            continue
        context_ref = element.get("contextRef")
        name = _clean_str(element.get("name"))
        if context_ref is None or name is None:
            continue
        text = _clean_str("".join(element.itertext()))
        if qname.localname == "nonFraction":
            numeric = _numeric_text(text or "", element.get("scale"), element.get("sign"))
        else:
            numeric = None
        unit_id = element.get("unitRef")
        facts.append(
            _raw_fact(
                concept=name,
                value=text,
                numeric_value=numeric,
                unit_ref=units.get(unit_id, unit_id),
                decimals=element.get("decimals"),
                context_ref=context_ref,
                context=contexts.get(context_ref),
                fact_id=element.get("id"),
            )
        )
    return facts


def parse_xbrl_instance(path: Path) -> list[dict[str, Any]]:
    """Parse a local XBRL instance into EdgarTools-shaped fact dicts.

    Handles classic ``xbrli:xbrl`` instances and inline XBRL documents as
    stored by the downloader (``<accession>_htm.xml``).  Facts whose context
    cannot be resolved carry no period and are dropped, because a number
    without a period is not a usable observation.  Raises ``ValueError`` when
    the document cannot be parsed at all.
    """

    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    try:
        tree = etree.parse(str(path), parser)
    except (etree.XMLSyntaxError, OSError) as error:
        raise ValueError(f"cannot parse XBRL instance {path.name}: {error}") from error

    root = tree.getroot()
    contexts = _parse_contexts(root)
    units = _parse_units(root)
    facts = _parse_classic_facts(root, contexts, units) + _parse_inline_facts(root, contexts, units)
    return [fact for fact in facts if fact["context_ref"] in contexts]


def looks_like_instance(path: Path) -> bool:
    """Sniff whether an artifact is an XBRL instance document."""

    if path.suffix.lower() != ".xml":
        return False
    if path.name.lower().endswith(LINKBASE_SUFFIXES):
        return False
    try:
        with path.open("rb") as handle:
            head = handle.read(SNIFF_BYTES).decode("utf-8", errors="replace").lower()
    except OSError:
        return False
    return any(marker in head for marker in INSTANCE_MARKERS)


def _find_instance_artifacts(filing: LocalFiling) -> list[Path]:
    """Return local XML artifacts that can be parsed as XBRL instances."""

    candidates: list[Path] = []
    for artifact in filing.artifacts:
        path = artifact.path
        if looks_like_instance(path):
            candidates.append(path)
    return candidates


class EdgarToolsAdapter:
    """Standard-data adapter that parses a local filing into parser contracts.

    Tries the installed EdgarTools release first, and falls back to parsing
    downloaded XBRL instance documents if the release cannot open the package.
    """

    def __init__(
        self,
        *,
        parser_version: str | None = None,
        statement_types: Sequence[str] = DEFAULT_STATEMENT_TYPES,
        opener: XbrlOpener | None = None,
    ) -> None:
        self.parser_version = parser_version or default_parser_version()
        self.statement_types = tuple(statement_types)
        self._opener = opener

    def parse(self, filing: LocalFiling) -> ParserOutput:
        """Parse ``filing`` and emit normalized facts and statement rows."""

        edgar_version = installed_edgartools_version()
        opener = self._opener or xbrl_from_directory
        try:
            xbrl = opener(filing.package_dir)
            return self._parse_with_edgartools(xbrl, filing, edgar_version)
        except Exception as error:
            return self._parse_with_fallback(filing, edgar_version, error)

    def _parse_with_edgartools(
        self,
        xbrl: Any,
        filing: LocalFiling,
        edgar_version: str | None,
    ) -> ParserOutput:
        output = ParserOutput(
            status=ParseStatus.SUCCESS,
            parser_version=self.parser_version,
            parse_mode=PARSE_MODE_EDGARTOOLS,
            edgartools_version=edgar_version,
        )

        try:
            raw_facts = xbrl.facts.get_facts()
        except Exception as error:  # pragma: no cover - defensive
            raw_facts = []
            output.diagnostics.append(
                ParserDiagnostic(
                    code=DiagnosticCode.XBRL_UNAVAILABLE,
                    detail=f"facts.get_facts() raised: {error}",
                    scope="facts",
                    severity=DiagnosticSeverity.ERROR,
                )
            )

        for raw_fact in raw_facts:
            if not isinstance(raw_fact, Mapping):
                continue
            draft = normalize_fact(raw_fact, filing, self.parser_version)
            if draft is None:
                output.diagnostics.append(
                    ParserDiagnostic(
                        code=DiagnosticCode.FACT_MALFORMED,
                        detail="raw fact has no concept name",
                        scope="facts",
                        severity=DiagnosticSeverity.WARNING,
                    )
                )
                continue
            if _fact_is_malformed(raw_fact, draft):
                output.diagnostics.append(
                    ParserDiagnostic(
                        code=DiagnosticCode.FACT_MALFORMED,
                        detail=f"fact {draft.concept} carried no usable numeric value",
                        scope="facts",
                        relative_path=filing.primary_relative_path,
                        severity=DiagnosticSeverity.WARNING,
                    )
                )
            output.facts.append(draft)

        statement_failures = 0
        for statement_type in self.statement_types:
            try:
                rows = xbrl.get_statement(statement_type)
                drafts = normalize_statement_rows(
                    rows,
                    statement_type=statement_type,
                    filing=filing,
                    parser_version=self.parser_version,
                )
                output.statements.extend(drafts)
            except Exception as error:
                statement_failures += 1
                output.diagnostics.append(
                    ParserDiagnostic(
                        code=DiagnosticCode.STATEMENT_UNAVAILABLE,
                        detail=f"{statement_type} unavailable: {error}",
                        scope=statement_type,
                        severity=DiagnosticSeverity.WARNING,
                    )
                )

        if statement_failures == len(self.statement_types) and output.facts:
            output.status = ParseStatus.PARTIAL
        elif not output.facts and not output.statements:
            output.status = ParseStatus.FAILED

        return output

    def _parse_with_fallback(
        self,
        filing: LocalFiling,
        edgar_version: str | None,
        reason: Exception,
    ) -> ParserOutput:
        output = ParserOutput(
            status=ParseStatus.PARTIAL,
            parser_version=self.parser_version,
            parse_mode=PARSE_MODE_RAW_XBRL,
            edgartools_version=edgar_version,
        )
        output.diagnostics.append(
            ParserDiagnostic(
                code=DiagnosticCode.XBRL_UNAVAILABLE,
                detail=f"EdgarTools could not open package: {reason}",
                scope="opener",
                severity=DiagnosticSeverity.WARNING,
            )
        )

        instances = _find_instance_artifacts(filing)
        if not instances:
            output.status = ParseStatus.FAILED
            output.diagnostics.append(
                ParserDiagnostic(
                    code=DiagnosticCode.XBRL_UNAVAILABLE,
                    detail="no XML artifacts matching XBRL instance patterns in package",
                    scope="fallback",
                    severity=DiagnosticSeverity.ERROR,
                )
            )
            return output

        output.diagnostics.append(
            ParserDiagnostic(
                code=DiagnosticCode.RAW_XBRL_FALLBACK,
                detail=f"parsed {len(instances)} raw XBRL instance documents directly",
                scope="fallback",
                severity=DiagnosticSeverity.INFO,
            )
        )

        for path in instances:
            try:
                raw_facts = parse_xbrl_instance(path)
            except ValueError as error:
                output.diagnostics.append(
                    ParserDiagnostic(
                        code=DiagnosticCode.FACT_MALFORMED,
                        detail=str(error),
                        scope="fallback",
                        relative_path=path.relative_to(filing.package_dir.parent.parent).as_posix(),
                        severity=DiagnosticSeverity.WARNING,
                    )
                )
                continue

            for raw_fact in raw_facts:
                draft = normalize_fact(
                    raw_fact,
                    filing,
                    self.parser_version,
                    extraction_method=RAW_XBRL_FACT_METHOD,
                )
                if draft is not None:
                    output.facts.append(draft)

        if not output.facts:
            output.status = ParseStatus.FAILED
        return output
