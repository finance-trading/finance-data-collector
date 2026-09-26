"""Scan local SEC filing archives and expose parser-ready contracts.

The existing downloader owns the archive layout ``sec/<TICKER>/<FORM>/<ACCESSION>/``
plus ``sec/<TICKER>/filings_index.json``.  This module never rediscovers or
re-downloads filings: it validates that index, hashes the files that actually
exist on disk, and reports every missing package, missing primary document, and
unreadable artifact explicitly instead of silently dropping it.

Run it directly to inspect one ticker before parsing::

    python -m fdc.archive MSFT --sec-root sec
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from fdc.contracts import (
    ArchiveGap,
    ArchiveScan,
    ArtifactRef,
    ArtifactRole,
    ArtifactStatus,
    DiagnosticCode,
    DiagnosticSeverity,
    LocalFiling,
)
from fdc.sec_storage import SEC_ROOT

#: Forms parsed by the filing parser platform.
PARSER_FORMS: tuple[str, ...] = ("10-K", "10-Q", "10-K/A", "10-Q/A")

#: Artifacts classified as images: indexed for provenance, never parsed.
IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".tif", ".tiff", ".ico"}
)

#: Markup extensions treated as XBRL (instances, linkbases, schemas).
XBRL_EXTENSIONS: frozenset[str] = frozenset({".xml", ".xsd"})

#: Markup extensions treated as HTML narrative documents.
HTML_EXTENSIONS: frozenset[str] = frozenset({".htm", ".html", ".xhtml"})

#: Snippet size used to classify ``.txt`` artifacts by their content.
CONTENT_SNIFF_BYTES = 8192

CONTENT_TYPES: dict[str, str] = {
    ".htm": "text/html",
    ".html": "text/html",
    ".xhtml": "application/xhtml+xml",
    ".txt": "text/plain",
    ".xml": "application/xml",
    ".xsd": "application/xml",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".ico": "image/x-icon",
}

DEFAULT_CONTENT_TYPE = "application/octet-stream"

INDEX_FILENAME = "filings_index.json"

#: Maximum filing/gap lines the human-readable report prints unless verbose.
MAX_REPORTED_RECORDS = 40

#: Exhibit names such as ``msft-ex31_1.htm`` or ``exhibit-10-1.htm``.
_EXHIBIT_RE = re.compile(r"(?:^|[-_])ex(?:hibit)?[-_]?\d", re.IGNORECASE)

#: SEC document type tags used by text exhibits without exhibit-like names.
_EXHIBIT_TYPE_RE = re.compile(r"<TYPE>\s*EX(?:HIBIT)?[-_\s]?\d", re.IGNORECASE)

#: Inline XBRL instance documents, e.g. ``msft-20250630_htm.xml``.
_INLINE_XBRL_RE = re.compile(r"_htm\.xml$", re.IGNORECASE)

#: Canonical dashed accession number.
_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")

#: Undashed accession number as returned by some EDGAR endpoints.
_COMPACT_ACCESSION_RE = re.compile(r"^\d{18}$")

#: ``YYYYMMDD`` period end embedded in primary document names.
_DOCUMENT_DATE_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)")

#: Index record fields that may name the primary document.
_PRIMARY_DOCUMENT_KEYS = ("primary_document", "primaryDocument", "primary_doc", "primary")


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path``, streamed in chunks."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_form(value: str | None) -> str | None:
    """Normalize an index/CLI form value, e.g. ``"10-k"`` or ``"DEF 14A"``."""

    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None
    return cleaned.upper().replace(" ", "-")


def normalize_accession(value: str | None) -> str | None:
    """Return the canonical dashed accession number, or ``None`` if invalid."""

    if value is None:
        return None
    cleaned = str(value).strip()
    if _ACCESSION_RE.match(cleaned):
        return cleaned
    if _COMPACT_ACCESSION_RE.match(cleaned):
        return f"{cleaned[:10]}-{cleaned[10:12]}-{cleaned[12:]}"
    return None


def is_exhibit_name(name: str) -> bool:
    """True when a file name follows SEC exhibit naming conventions."""

    return bool(_EXHIBIT_RE.search(name))


def content_type_for(path: Path) -> str:
    """Return the stored content type for one artifact path."""

    return CONTENT_TYPES.get(path.suffix.lower(), DEFAULT_CONTENT_TYPE)


def read_snippet(path: Path, size: int = CONTENT_SNIFF_BYTES) -> str | None:
    """Read a decoded text snippet, returning ``None`` when unreadable."""

    try:
        with path.open("rb") as handle:
            return handle.read(size).decode("utf-8", errors="replace")
    except OSError:
        return None


def _is_complete_submission(snippet: str) -> bool:
    """True when a snippet comes from the complete-submission ``.txt`` package."""

    lowered = snippet.lower()
    return "<sec-document>" in lowered or "<sec-header>" in lowered


def _is_text_exhibit(name: str, snippet: str) -> bool:
    """True when a text artifact is named or tagged as an SEC exhibit."""

    return is_exhibit_name(name) or bool(_EXHIBIT_TYPE_RE.search(snippet))


def classify_artifact(path: Path) -> ArtifactRole:
    """Classify one package artifact, reading content for ambiguous extensions.

    The selected primary document is promoted to :attr:`ArtifactRole.PRIMARY` by
    the scanner; this function only reports what a file *is*.  ``.txt`` files are
    never classified by extension alone: the complete-submission container is
    detected by its content, and so is an XML or HTML document stored with a
    ``.txt`` suffix.
    """

    name = path.name
    suffix = path.suffix.lower()

    if suffix in IMAGE_EXTENSIONS:
        return ArtifactRole.IMAGE
    if suffix in XBRL_EXTENSIONS:
        return ArtifactRole.XBRL
    if suffix in HTML_EXTENSIONS:
        return ArtifactRole.EXHIBIT if is_exhibit_name(name) else ArtifactRole.TEXT
    if suffix == ".txt":
        snippet = read_snippet(path) or ""
        if _is_complete_submission(snippet):
            return ArtifactRole.TEXT
        if "<?xml" in snippet.lower():
            return ArtifactRole.XBRL
        if _is_text_exhibit(name, snippet):
            return ArtifactRole.EXHIBIT
        return ArtifactRole.TEXT
    return ArtifactRole.UNKNOWN


def is_parse_eligible(path: Path, role: ArtifactRole) -> bool:
    """Whether a parser should ever read this artifact.

    Images and unknown binaries are indexed for provenance but never parsed.
    Complete-submission ``.txt`` containers are skipped; independent text
    exhibits and ordinary text remain part of parsing and filing identity.
    """

    if role in (ArtifactRole.IMAGE, ArtifactRole.UNKNOWN):
        return False
    if path.suffix.lower() == ".txt":
        snippet = read_snippet(path) or ""
        return not _is_complete_submission(snippet)
    return True


def artifact_set_hash(artifacts: Iterable[ArtifactRef]) -> str:
    """Hash the sorted ``(relative_path, byte_size, sha256)`` triples.

    The hash is the parse identity of an artifact set: it does not depend on
    directory iteration order and changes whenever any eligible artifact's
    content or size changes.
    """

    digest = hashlib.sha256()
    for artifact in sorted(artifacts, key=lambda item: item.relative_path):
        digest.update(
            f"{artifact.relative_path}\n{artifact.byte_size}\n"
            f"{artifact.sha256 or 'unreadable'}\n".encode()
        )
    return digest.hexdigest()


def parse_document_date(name: str) -> date | None:
    """Extract the period end date encoded in a primary document name."""

    match = _DOCUMENT_DATE_RE.search(name)
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_iso_date(value: Any) -> date | None:
    """Parse an ISO-8601 date from index metadata, ignoring unusable values."""

    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def package_files(package_dir: Path) -> list[Path]:
    """Return every file in a package, in deterministic path order."""

    files = (path for path in package_dir.rglob("*") if path.is_file() or path.is_symlink())
    return sorted(files, key=lambda path: path.relative_to(package_dir).as_posix())


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def collect_artifacts(
    ticker_dir: Path,
    package_dir: Path,
    *,
    ticker: str,
    form: str,
    accession: str,
) -> tuple[tuple[ArtifactRef, ...], list[ArchiveGap]]:
    """Index every file in a package, hashing it and recording read failures.

    A file that cannot be read is still indexed (so its presence is visible)
    but is never parse-eligible, and the failure is reported as a gap.
    """

    artifacts: list[ArtifactRef] = []
    gaps: list[ArchiveGap] = []
    resolved_package_dir = package_dir.resolve()

    for path in package_files(package_dir):
        relative_path = path.relative_to(ticker_dir).as_posix()
        if not path.resolve().is_relative_to(resolved_package_dir):
            gaps.append(
                ArchiveGap(
                    code=DiagnosticCode.ARTIFACT_OUTSIDE_PACKAGE,
                    detail="artifact resolves outside the filing package",
                    ticker=ticker,
                    form=form,
                    accession=accession,
                    path=relative_path,
                )
            )
            continue
        role = classify_artifact(path)
        eligible = is_parse_eligible(path, role)
        try:
            sha256 = sha256_file(path)
            byte_size = _file_size(path)
            # Indexed files that no parser reads (images, binaries, the
            # complete-submission container) are recorded as skipped.
            status = ArtifactStatus.INDEXED if eligible else ArtifactStatus.SKIPPED
        except OSError as error:
            sha256 = None
            byte_size = _file_size(path)
            status = ArtifactStatus.UNREADABLE
            eligible = False
            gaps.append(
                ArchiveGap(
                    code=DiagnosticCode.UNREADABLE_ARTIFACT,
                    detail=f"cannot read artifact: {error}",
                    ticker=ticker,
                    form=form,
                    accession=accession,
                    path=relative_path,
                )
            )
        artifacts.append(
            ArtifactRef(
                relative_path=relative_path,
                path=path,
                byte_size=byte_size,
                sha256=sha256,
                role=role,
                content_type=content_type_for(path),
                status=status,
                parse_eligible=eligible,
            )
        )

    return tuple(artifacts), gaps


def primary_document_hint(record: Mapping[str, Any]) -> str | None:
    """Return the index-provided primary document name, if the index has one."""

    for key in _PRIMARY_DOCUMENT_KEYS:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _primary_rank(artifact: ArtifactRef) -> tuple[int, int, int, str]:
    """Deterministic primary-document ranking used when the index has no hint.

    HTML documents win over inline XBRL instances and linkbases, exhibit-named
    files lose to narrative documents, files carrying the period end date in
    their name are preferred, and larger files break remaining ties.
    """

    name = artifact.relative_path.rsplit("/", 1)[-1]
    suffix = Path(name).suffix.lower()

    if suffix in HTML_EXTENSIONS:
        kind = 3 if is_exhibit_name(name) else 0
    elif suffix == ".txt":
        kind = 1
    elif _INLINE_XBRL_RE.search(name):
        kind = 2
    elif suffix in XBRL_EXTENSIONS:
        kind = 4
    else:
        kind = 5

    dated = 0 if _DOCUMENT_DATE_RE.search(name) else 1
    return (kind, dated, -artifact.byte_size, artifact.relative_path)


def select_primary_document(
    artifacts: Sequence[ArtifactRef],
    hint: str | None = None,
) -> ArtifactRef | None:
    """Select the primary document from the index hint, then by ranking."""

    eligible = [artifact for artifact in artifacts if artifact.parse_eligible]
    if hint:
        wanted = hint.replace("\\", "/").removeprefix("./")
        for artifact in eligible:
            if artifact.relative_path == wanted or artifact.relative_path.endswith(f"/{wanted}"):
                return artifact
            if artifact.path.name == wanted:
                return artifact
    if not eligible:
        return None
    return min(eligible, key=_primary_rank)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _build_filing(
    *,
    ticker: str,
    ticker_dir: Path,
    form: str,
    accession: str,
    package_path: str,
    package_dir: Path,
    record: Mapping[str, Any],
) -> tuple[LocalFiling | None, list[ArchiveGap]]:
    """Build one eligible filing, or explain why it cannot be parsed."""

    artifacts, gaps = collect_artifacts(
        ticker_dir, package_dir, ticker=ticker, form=form, accession=accession
    )
    if not artifacts:
        gaps.append(
            ArchiveGap(
                code=DiagnosticCode.PACKAGE_EMPTY,
                detail="package directory holds no files",
                ticker=ticker,
                form=form,
                accession=accession,
                path=package_path,
            )
        )
        return None, gaps

    primary = select_primary_document(artifacts, primary_document_hint(record))
    if primary is None:
        gaps.append(
            ArchiveGap(
                code=DiagnosticCode.PRIMARY_MISSING,
                detail="no parseable primary document or XBRL instance in package",
                ticker=ticker,
                form=form,
                accession=accession,
                path=package_path,
            )
        )
        return None, gaps

    artifacts = tuple(
        replace(artifact, role=ArtifactRole.PRIMARY)
        if artifact.relative_path == primary.relative_path
        else artifact
        for artifact in artifacts
    )
    parseable = tuple(artifact for artifact in artifacts if artifact.parse_eligible)

    return (
        LocalFiling(
            ticker=ticker,
            form=form,
            accession=accession,
            is_amended=form.endswith("/A"),
            filing_date=parse_iso_date(record.get("date")),
            # Index metadata wins; otherwise the document name carries the period end.
            report_date=parse_iso_date(record.get("report_date"))
            or parse_document_date(primary.path.name),
            fiscal_year=_optional_int(record.get("fiscal_year")),
            fiscal_period=_optional_str(record.get("fiscal_period")),
            package_path=package_path,
            package_dir=package_dir,
            primary_relative_path=primary.relative_path,
            primary_document=primary.path,
            artifacts=artifacts,
            artifact_set_hash=artifact_set_hash(parseable),
            index_record=dict(record),
        ),
        gaps,
    )


def scan_ticker_archive(
    sec_root: Path,
    ticker: str,
    forms: Collection[str] | None = PARSER_FORMS,
    *,
    limit: int | None = None,
) -> ArchiveScan:
    """Scan ``sec_root/<TICKER>`` for eligible filings and explicit gaps.

    ``forms`` narrows the four parser-supported forms; ``None`` accepts all four.
    Eligible filings are ordered chronologically (oldest first) so a checkpointed
    run can resume where it stopped.
    """

    root = Path(sec_root)
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    normalized_ticker = str(ticker).strip().upper()
    ticker_dir = root / normalized_ticker
    index_path = ticker_dir / INDEX_FILENAME
    relative_index_path = f"{normalized_ticker}/{INDEX_FILENAME}"
    parser_forms = frozenset(PARSER_FORMS)
    requested_forms = (
        {form for form in (normalize_form(item) for item in forms) if form}
        if forms is not None
        else parser_forms
    )
    wanted = tuple(sorted(parser_forms.intersection(requested_forms)))

    scan = ArchiveScan(
        ticker=normalized_ticker,
        sec_root=root,
        ticker_dir=ticker_dir,
        index_path=index_path,
        forms=wanted,
    )

    if not index_path.is_file():
        scan.gaps.append(
            ArchiveGap(
                code=DiagnosticCode.MISSING_INDEX,
                detail=f"no {INDEX_FILENAME} for {normalized_ticker}",
                ticker=normalized_ticker,
                path=relative_index_path,
            )
        )
        return scan

    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        scan.gaps.append(
            ArchiveGap(
                code=DiagnosticCode.MALFORMED_INDEX,
                detail=f"cannot parse {INDEX_FILENAME}: {error}",
                ticker=normalized_ticker,
                path=relative_index_path,
            )
        )
        return scan

    records = payload.get("filings") if isinstance(payload, Mapping) else None
    if isinstance(records, str) or not isinstance(records, Sequence):
        scan.gaps.append(
            ArchiveGap(
                code=DiagnosticCode.MALFORMED_INDEX,
                detail=f"{INDEX_FILENAME} must be an object with a filings list",
                ticker=normalized_ticker,
                path=relative_index_path,
            )
        )
        return scan

    scan.index_metadata = {key: value for key, value in payload.items() if key != "filings"}
    scan.index_record_count = len(records)
    resolved_ticker_dir = ticker_dir.resolve()
    eligible: list[LocalFiling] = []

    for position, record in enumerate(records):
        if not isinstance(record, Mapping):
            scan.gaps.append(
                ArchiveGap(
                    code=DiagnosticCode.INVALID_INDEX_RECORD,
                    detail=f"index record {position} is not an object",
                    ticker=normalized_ticker,
                    path=relative_index_path,
                )
            )
            continue

        form = normalize_form(record.get("form") if isinstance(record.get("form"), str) else None)
        directory = _optional_str(record.get("directory"))
        record_context: dict[str, Any] = {
            "ticker": normalized_ticker,
            "form": form,
            "accession": _optional_str(record.get("accession")),
        }

        if form is None or directory is None:
            scan.gaps.append(
                ArchiveGap(
                    code=DiagnosticCode.INVALID_INDEX_RECORD,
                    detail=f"index record {position} has no usable form/directory",
                    path=relative_index_path,
                    **record_context,
                )
            )
            continue

        if form not in wanted:
            scan.skipped.append(
                ArchiveGap(
                    code=DiagnosticCode.UNSUPPORTED_FORM,
                    detail=f"form {form} is outside the requested set",
                    path=directory,
                    severity=DiagnosticSeverity.INFO,
                    **record_context,
                )
            )
            continue

        package_path = directory.replace("\\", "/").removeprefix("./").rstrip("/")
        accession = normalize_accession(record.get("accession"))
        if accession is None:
            scan.gaps.append(
                ArchiveGap(
                    code=DiagnosticCode.INVALID_ACCESSION,
                    detail=f"accession {record.get('accession')!r} is not a valid accession number",
                    path=package_path,
                    **record_context,
                )
            )
        package_dir = (resolved_ticker_dir / package_path).resolve()
        if not package_dir.is_relative_to(resolved_ticker_dir):
            scan.gaps.append(
                ArchiveGap(
                    code=DiagnosticCode.INVALID_INDEX_RECORD,
                    detail=f"index record {position} points outside the ticker directory",
                    path=package_path,
                    **record_context,
                )
            )
            continue
        if not package_dir.is_dir():
            scan.gaps.append(
                ArchiveGap(
                    code=DiagnosticCode.PACKAGE_MISSING,
                    detail="package directory does not exist",
                    path=package_path,
                    **record_context,
                )
            )
            continue
        if accession is None:
            continue

        filing, filing_gaps = _build_filing(
            ticker=normalized_ticker,
            ticker_dir=resolved_ticker_dir,
            form=form,
            accession=accession,
            package_path=package_path,
            package_dir=package_dir,
            record=record,
        )
        scan.gaps.extend(filing_gaps)
        if filing is not None:
            eligible.append(filing)

    eligible.sort(key=lambda filing: (filing.filing_date or date.min, filing.accession))
    scan.eligible_count = len(eligible)
    scan.filings = eligible[:limit] if limit is not None else eligible
    return scan


def default_sec_root() -> Path:
    """Return the archive root: ``FDC_SEC_ROOT`` when set, else the repo ``sec/``.

    The scanner never contacts EDGAR, so it deliberately avoids depending on the
    SEC user-agent requirement of the full settings object.
    """

    override = os.environ.get("FDC_SEC_ROOT", "").strip()
    return Path(override) if override else SEC_ROOT


def _positive_int(value: str) -> int:
    """Parse a positive CLI integer."""

    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fdc.archive",
        description="Scan a local SEC filing archive and report eligible filings.",
    )
    parser.add_argument("ticker", help="ticker whose archive directory is scanned")
    parser.add_argument(
        "--sec-root",
        default=None,
        help="archive root containing <TICKER>/filings_index.json (default: FDC_SEC_ROOT or ./sec)",
    )
    parser.add_argument(
        "--forms",
        default=",".join(PARSER_FORMS),
        help="comma-separated forms to accept, e.g. '10-K,10-Q'",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help="report at most N eligible filings",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="list every filing, gap and skipped record instead of summarizing",
    )
    parser.add_argument("--json", action="store_true", help="print the scan summary as JSON")
    return parser


def _gap_lines(
    label: str,
    gaps: Sequence[ArchiveGap],
    *,
    verbose: bool,
    limit: int = MAX_REPORTED_RECORDS,
) -> list[str]:
    """Render gap lines, truncating long lists unless ``verbose`` is set."""

    lines = [
        f"{label} {gap.code} {gap.form or '-'} {gap.accession or '-'} "
        f"{gap.path or '-'}: {gap.detail}"
        for gap in gaps
    ]
    if not verbose and len(lines) > limit:
        hidden = len(lines) - limit
        lines = [*lines[:limit], f"{label}: +{hidden} more (use --verbose)"]
    return lines


def format_report(scan: ArchiveScan, *, verbose: bool = False) -> str:
    """Render a human-readable scan report with one line per filing and gap."""

    lines = [
        f"{scan.ticker} {scan.ticker_dir} — {scan.index_record_count} index records, "
        f"{scan.eligible_count} eligible filings, {len(scan.gaps)} gaps, "
        f"{len(scan.skipped)} skipped"
    ]
    filing_lines = [
        f"  {filing.form} {filing.accession} {filing.filing_date or '-'} "
        f"primary={filing.primary_document.name if filing.primary_document else '-'} "
        f"artifacts={len(filing.artifacts)} parseable={len(filing.parseable_artifacts)} "
        f"hash={filing.artifact_set_hash[:12]}"
        for filing in scan.filings
    ]
    if not verbose and len(filing_lines) > MAX_REPORTED_RECORDS:
        hidden = len(filing_lines) - MAX_REPORTED_RECORDS
        filing_lines = [
            *filing_lines[:MAX_REPORTED_RECORDS],
            f"  +{hidden} more eligible filings (use --limit or --verbose)",
        ]
    lines.extend(filing_lines)
    lines.extend(_gap_lines("gap", scan.gaps, verbose=verbose))

    if scan.skipped:
        if verbose:
            lines.extend(_gap_lines("skipped", scan.skipped, verbose=True))
        else:
            counts = Counter(gap.form or "-" for gap in scan.skipped)
            breakdown = ", ".join(f"{form}={count}" for form, count in sorted(counts.items()))
            codes = ", ".join(sorted({str(gap.code) for gap in scan.skipped}))
            lines.append(f"skipped {codes}: {len(scan.skipped)} records ({breakdown})")

    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Scan one ticker archive and print a report; returns 1 if the scan is unusable."""

    args = _build_parser().parse_args(argv)
    forms = {piece for piece in (item.strip() for item in args.forms.split(",")) if piece}
    sec_root = Path(args.sec_root) if args.sec_root else default_sec_root()
    scan = scan_ticker_archive(sec_root, args.ticker, forms or None, limit=args.limit)

    if args.json:
        print(json.dumps(scan.summary(), indent=2))
    else:
        print(format_report(scan, verbose=args.verbose))

    return 0 if scan.ok else 1


if __name__ == "__main__":
    sys.exit(main())
