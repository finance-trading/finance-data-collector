"""Unit tests for the local SEC archive scanner and parser contracts.

The scanner decides which local packages may be parsed, so every skip must be
explicit, every hash reproducible, and the whole module must work without
network access.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from fdc.archive import (
    artifact_set_hash,
    classify_artifact,
    default_sec_root,
    main,
    normalize_accession,
    normalize_form,
    scan_ticker_archive,
    sha256_file,
)
from fdc.contracts import (
    ArtifactRole,
    ArtifactStatus,
    DiagnosticCode,
    EvidenceDraft,
    FactDraft,
    LocatorType,
    ParserDiagnostic,
    ParserOutput,
    ParseStatus,
    SectionDraft,
    TableDraft,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "filings"
PARSER_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}
MINIMAL_HTML = "<html><body><p>Filing body</p></body></html>"
SUBMISSION_TXT = (
    "<SEC-DOCUMENT>\n<TYPE>10-K\n<FILENAME>acme-20240630.htm\n<TEXT><html/></TEXT>\n"
    "</SEC-DOCUMENT>\n"
)


def write_index(root: Path, ticker: str, records: list[dict], **metadata) -> Path:
    """Write a ``filings_index.json`` shaped like the SEC downloader output."""

    ticker_dir = root / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_updated": "2026-09-22T16:38:12.886342",
        "total_filings": len(records),
        "filings": records,
        **metadata,
    }
    (ticker_dir / "filings_index.json").write_text(json.dumps(payload))
    return ticker_dir


def write_package(ticker_dir: Path, directory: str, files: dict[str, str | bytes]) -> Path:
    """Create one accession package directory and return its path."""

    package = ticker_dir / directory
    package.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        data = content.encode() if isinstance(content, str) else content
        (package / name).write_bytes(data)
    return package


def single_filing_archive(tmp_path: Path, files: dict[str, str | bytes], **record):
    """Build a one-record archive and return its scan."""

    record = {
        "form": "10-K",
        "date": "2024-07-25",
        "accession": "0000000000-24-000001",
        "directory": "10-K/0000000000-24-000001",
        **record,
    }
    ticker_dir = write_index(tmp_path, "MSFT", [record])
    write_package(ticker_dir, record["directory"], files)
    return scan_ticker_archive(tmp_path, "MSFT", PARSER_FORMS)


@pytest.fixture
def fixture_root() -> Path:
    return FIXTURE_ROOT


def test_scan_normalizes_forms_and_hashes_artifacts(fixture_root):
    scan = scan_ticker_archive(fixture_root, "MSFT", PARSER_FORMS)

    assert [filing.form for filing in scan.filings] == ["10-K", "10-Q"]
    assert scan.filings[0].accession == "0000000000-24-000001"
    assert len(scan.filings[0].artifact_set_hash) == 64
    assert scan.filings[0].primary_document.suffix in {".htm", ".html", ".xml"}


def test_scan_orders_eligible_filings_chronologically(fixture_root):
    scan = scan_ticker_archive(fixture_root, "MSFT", PARSER_FORMS)

    assert scan.accessions == ["0000000000-24-000001", "0000000000-25-000002"]
    assert scan.filings[0].filing_date == date(2024, 7, 25)
    assert scan.filings[1].filing_date == date(2025, 1, 28)


def test_scan_records_report_date_from_index_and_primary_document(fixture_root):
    scan = scan_ticker_archive(fixture_root, "MSFT", PARSER_FORMS)

    # Index metadata wins for the 10-Q; the 10-K falls back to its document name.
    assert scan.filings[1].report_date == date(2024, 12, 31)
    assert scan.filings[0].report_date == date(2024, 6, 30)
    assert scan.filings[0].is_amended is False


def test_scan_reports_missing_packages_as_gaps(fixture_root):
    scan = scan_ticker_archive(fixture_root, "MSFT", PARSER_FORMS)

    assert [gap.code for gap in scan.gaps] == [DiagnosticCode.PACKAGE_MISSING]
    assert scan.gaps[0].accession == "0000000000-25-000003"
    assert scan.gaps[0].form == "10-Q"
    assert scan.gaps[0].path == "10-Q/0000000000-25-000003"


def test_unsupported_forms_are_skipped_explicitly(fixture_root):
    scan = scan_ticker_archive(fixture_root, "MSFT", PARSER_FORMS)

    assert [gap.code for gap in scan.skipped] == [DiagnosticCode.UNSUPPORTED_FORM]
    assert scan.skipped[0].form == "8-K"
    assert scan.skipped[0].accession == "0000000000-24-000004"
    assert "0000000000-24-000004" not in scan.accessions


def test_missing_package_is_explicit_gap(tmp_path):
    (tmp_path / "MSFT").mkdir()
    (tmp_path / "MSFT" / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "form": "10-K",
                        "date": "2024-01-01",
                        "accession": "a",
                        "directory": "10-K/a",
                    }
                ]
            }
        )
    )
    scan = scan_ticker_archive(tmp_path, "MSFT", {"10-K"})

    assert scan.gaps[0].code == "PACKAGE_MISSING"
    assert scan.filings == []


def test_missing_index_is_explicit_gap(tmp_path):
    scan = scan_ticker_archive(tmp_path, "MSFT", PARSER_FORMS)

    assert [gap.code for gap in scan.gaps] == [DiagnosticCode.MISSING_INDEX]
    assert scan.gaps[0].path == "MSFT/filings_index.json"
    assert scan.filings == []
    assert scan.ok is False
    assert scan.summary()["ok"] is False


@pytest.mark.parametrize("payload", ["{not json", '{"filings": "nope"}', '["10-K"]'])
def test_malformed_index_is_explicit_gap(tmp_path, payload):
    ticker_dir = tmp_path / "MSFT"
    ticker_dir.mkdir()
    (ticker_dir / "filings_index.json").write_text(payload)

    scan = scan_ticker_archive(tmp_path, "MSFT", PARSER_FORMS)

    assert [gap.code for gap in scan.gaps] == [DiagnosticCode.MALFORMED_INDEX]
    assert scan.filings == []
    assert scan.ok is False


def test_invalid_index_records_do_not_stop_the_scan(tmp_path):
    good = {
        "form": "10-K",
        "date": "2024-07-25",
        "accession": "0000000000-24-000001",
        "directory": "10-K/0000000000-24-000001",
    }
    broken = {"form": "10-K", "date": "2024-07-25", "accession": "n/a", "directory": "10-K/n-a"}
    ticker_dir = write_index(tmp_path, "MSFT", ["10-K", broken, good])
    write_package(ticker_dir, good["directory"], {"acme-20240630.htm": MINIMAL_HTML})
    write_package(ticker_dir, broken["directory"], {"acme-20240331.htm": MINIMAL_HTML})

    scan = scan_ticker_archive(tmp_path, "MSFT", PARSER_FORMS)

    assert [gap.code for gap in scan.gaps] == [
        DiagnosticCode.INVALID_INDEX_RECORD,
        DiagnosticCode.INVALID_ACCESSION,
    ]
    assert scan.accessions == ["0000000000-24-000001"]


def test_primary_document_honours_index_hint(tmp_path):
    scan = single_filing_archive(
        tmp_path,
        {
            "acme-20240630.htm": MINIMAL_HTML,
            "acme-20240630-exhibit-like-primary.htm": MINIMAL_HTML * 3,
        },
        primary_document="acme-20240630.htm",
    )

    filing = scan.filings[0]

    assert filing.primary_relative_path == "10-K/0000000000-24-000001/acme-20240630.htm"
    assert filing.primary_artifact.role is ArtifactRole.PRIMARY


def test_primary_document_falls_back_to_ranking(tmp_path):
    scan = single_filing_archive(
        tmp_path,
        {
            "acme-20240630.htm": MINIMAL_HTML,
            "acme-ex31_1.htm": MINIMAL_HTML * 4,
            "acme-20240630_htm.xml": "<?xml version='1.0'?><xbri/>",
        },
        primary_document="missing-from-package.htm",
    )

    assert scan.filings[0].primary_document.name == "acme-20240630.htm"


def test_primary_document_falls_back_to_inline_xbrl(tmp_path):
    scan = single_filing_archive(
        tmp_path,
        {"acme-20240630_htm.xml": "<?xml version='1.0'?><xbri/>", "chart.png": b"\x89PNG"},
    )

    filing = scan.filings[0]

    assert filing.primary_document.name == "acme-20240630_htm.xml"
    assert filing.primary_artifact.role is ArtifactRole.PRIMARY
    assert filing.primary_artifact.content_type == "application/xml"


def test_missing_primary_document_is_a_gap(tmp_path):
    scan = single_filing_archive(tmp_path, {"chart.png": b"\x89PNG"})

    assert [gap.code for gap in scan.gaps] == [DiagnosticCode.PRIMARY_MISSING]
    assert scan.filings == []


def test_empty_package_is_a_gap(tmp_path):
    record = {
        "form": "10-K",
        "date": "2024-07-25",
        "accession": "0000000000-24-000001",
        "directory": "10-K/0000000000-24-000001",
    }
    ticker_dir = write_index(tmp_path, "MSFT", [record])
    (ticker_dir / record["directory"]).mkdir(parents=True)

    scan = scan_ticker_archive(tmp_path, "MSFT", PARSER_FORMS)

    assert [gap.code for gap in scan.gaps] == [DiagnosticCode.PACKAGE_EMPTY]
    assert scan.filings == []


def test_images_are_indexed_but_not_parse_eligible(fixture_root):
    scan = scan_ticker_archive(fixture_root, "MSFT", PARSER_FORMS)
    filing = scan.filings[0]
    logo = next(a for a in filing.artifacts if a.relative_path.endswith("msft-logo.jpg"))

    assert logo.role is ArtifactRole.IMAGE
    assert logo.status is ArtifactStatus.SKIPPED
    assert logo.parse_eligible is False
    assert len(logo.sha256) == 64
    # Images never influence parse identity, but their bytes are still recorded.
    assert artifact_set_hash(filing.parseable_artifacts) == filing.artifact_set_hash


def test_txt_artifacts_are_classified_by_content(tmp_path):
    scan = single_filing_archive(
        tmp_path,
        {
            "acme-20240630.txt": MINIMAL_HTML,
            "0000000000-24-000001.txt": SUBMISSION_TXT,
        },
    )
    filing = scan.filings[0]
    by_name = {a.relative_path.rsplit("/", 1)[-1]: a for a in filing.artifacts}

    assert by_name["0000000000-24-000001.txt"].role is ArtifactRole.TEXT
    assert by_name["0000000000-24-000001.txt"].parse_eligible is False
    assert by_name["acme-20240630.txt"].parse_eligible is True
    assert filing.primary_document.name == "acme-20240630.txt"


def test_unreadable_artifacts_are_recorded_without_aborting_the_scan(tmp_path, monkeypatch):
    def unreadable(path: Path) -> str:
        if path.name == "broken-exhibit.htm":
            raise OSError("permission denied")
        return real_sha256_file(path)

    real_sha256_file = sha256_file
    monkeypatch.setattr("fdc.archive.sha256_file", unreadable)
    scan = single_filing_archive(
        tmp_path,
        {"acme-20240630.htm": MINIMAL_HTML, "broken-exhibit.htm": MINIMAL_HTML},
    )

    filing = scan.filings[0]
    broken = next(a for a in filing.artifacts if a.relative_path.endswith("broken-exhibit.htm"))

    assert broken.sha256 is None
    assert broken.status is ArtifactStatus.UNREADABLE
    assert broken.parse_eligible is False
    assert [gap.code for gap in scan.gaps] == [DiagnosticCode.UNREADABLE_ARTIFACT]
    assert scan.gaps[0].path == broken.relative_path


@pytest.mark.parametrize(
    ("name", "role"),
    [
        ("acme-20240630.htm", ArtifactRole.TEXT),
        ("acme-20240630.html", ArtifactRole.TEXT),
        ("acme-ex31_1.htm", ArtifactRole.EXHIBIT),
        ("exhibit-10-1.htm", ArtifactRole.EXHIBIT),
        ("acme-20240630_htm.xml", ArtifactRole.XBRL),
        ("acme-20240630.xsd", ArtifactRole.XBRL),
        ("acme-20240630_lab.xml", ArtifactRole.XBRL),
        ("logo.jpg", ArtifactRole.IMAGE),
        ("chart.PNG", ArtifactRole.IMAGE),
        ("notes.pdf", ArtifactRole.UNKNOWN),
        ("package.zip", ArtifactRole.UNKNOWN),
    ],
)
def test_classify_artifact_uses_names_without_reading_bytes(tmp_path, name, role):
    assert classify_artifact(tmp_path / name) is role


def test_sha256_file_is_content_addressed(tmp_path):
    document = tmp_path / "document.htm"
    document.write_text(MINIMAL_HTML)

    assert sha256_file(document) == hashlib.sha256(MINIMAL_HTML.encode()).hexdigest()


def test_artifact_set_hash_ignores_order_and_tracks_content(fixture_root):
    filing = scan_ticker_archive(fixture_root, "MSFT", PARSER_FORMS).filings[0]
    artifacts = filing.parseable_artifacts

    assert artifact_set_hash(list(reversed(artifacts))) == filing.artifact_set_hash
    assert artifact_set_hash(artifacts[:-1]) != filing.artifact_set_hash
    assert len(filing.artifact_set_hash) == 64


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0000000000-24-000001", "0000000000-24-000001"),
        ("000000000024000001", "0000000000-24-000001"),
        (" 0000000000-24-000001 ", "0000000000-24-000001"),
        ("0000000000-24-0000011", None),
        ("not-an-accession", None),
        ("", None),
    ],
)
def test_normalize_accession(value, expected):
    assert normalize_accession(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(" 10-k ", "10-K"), ("10-K/A", "10-K/A"), ("DEF 14A", "DEF-14A"), ("   ", None)],
)
def test_normalize_form(value, expected):
    assert normalize_form(value) == expected


def test_scan_marks_amendment_records(tmp_path):
    record = {
        "form": "10-K/A",
        "date": "2025-03-03",
        "accession": "0000000000-25-000006",
        "directory": "10-K-A/0000000000-25-000006",
    }
    ticker_dir = write_index(tmp_path, "MSFT", [record])
    write_package(ticker_dir, record["directory"], {"acme-20240630.htm": MINIMAL_HTML})

    scan = scan_ticker_archive(tmp_path, "MSFT", PARSER_FORMS)
    filing = scan.filings[0]

    assert filing.form == "10-K/A"
    assert filing.is_amended is True
    assert filing.package_path == "10-K-A/0000000000-25-000006"


def test_ticker_directory_lookup_is_case_insensitive(fixture_root):
    scan = scan_ticker_archive(fixture_root, "msft", PARSER_FORMS)

    assert scan.ticker == "MSFT"
    assert len(scan.filings) == 2


def test_scan_works_from_a_relative_sec_root(tmp_path, monkeypatch):
    record = {
        "form": "10-K",
        "date": "2024-07-25",
        "accession": "0000000000-24-000001",
        "directory": "10-K/0000000000-24-000001",
    }
    ticker_dir = write_index(tmp_path, "MSFT", [record])
    write_package(ticker_dir, record["directory"], {"acme-20240630.htm": MINIMAL_HTML})
    monkeypatch.chdir(tmp_path)

    scan = scan_ticker_archive(Path("."), "MSFT", PARSER_FORMS)

    assert scan.accessions == ["0000000000-24-000001"]
    assert scan.filings[0].artifacts[0].relative_path == (
        "10-K/0000000000-24-000001/acme-20240630.htm"
    )


def test_parser_output_contract_carries_rows_evidence_and_status():
    evidence = EvidenceDraft(
        locator_type=LocatorType.XBRL_FACT,
        locator_value="us-gaap:Revenues",
        relative_path="10-K/0000000000-24-000001/msft-20240630_htm.xml",
        accession_url="https://www.sec.gov/Archives/edgar/data/789019/000000000024000001/",
        content_sha256="a" * 64,
        excerpt="245122000000",
    )
    output = ParserOutput(status=ParseStatus.SUCCESS, parser_version="filing-parser-v1")

    assert output.counts() == {
        "facts": 0,
        "statements": 0,
        "sections": 0,
        "tables": 0,
        "evidence": 0,
        "diagnostics": 0,
    }

    output.facts.append(
        FactDraft(
            concept="us-gaap:Revenues",
            value_numeric=245122000000.0,
            unit="USD",
            period_type="annual",
            end_date=date(2024, 6, 30),
            evidence=evidence,
        )
    )
    output.sections.append(
        SectionDraft(
            section_type="md_and_a",
            heading="Item 7. Management's Discussion and Analysis",
            order_index=7,
            status="parsed",
            evidence=evidence,
        )
    )
    output.tables.append(
        TableDraft(
            table_type="segment",
            caption="Revenue by segment",
            order_index=1,
            columns=["segment", "2024"],
            rows=[{"segment": "Intelligent Cloud", "2024": 105362}],
            status="parsed",
            evidence=evidence,
        )
    )
    output.diagnostics.append(
        ParserDiagnostic(
            code=DiagnosticCode.PRIMARY_MISSING,
            detail="no primary document candidate",
            scope="scanner",
        )
    )

    assert output.counts()["facts"] == 1
    assert output.counts()["diagnostics"] == 1
    assert output.facts[0].evidence.locator_type is LocatorType.XBRL_FACT
    assert output.tables[0].rows[0]["segment"] == "Intelligent Cloud"


def test_cli_scan_reports_summary(fixture_root, capsys):
    assert main(["MSFT", "--sec-root", str(fixture_root)]) == 0
    text = capsys.readouterr().out

    assert "10-K" in text
    assert "10-Q" in text
    assert "PACKAGE_MISSING" in text
    assert "UNSUPPORTED_FORM" in text

    assert main(["MSFT", "--sec-root", str(fixture_root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["ticker"] == "MSFT"
    assert [filing["accession"] for filing in payload["filings"]] == [
        "0000000000-24-000001",
        "0000000000-25-000002",
    ]
    assert payload["filings"][0]["primary_document"] == "msft-20240630.htm"
    assert payload["gaps"][0]["code"] == "PACKAGE_MISSING"
    assert payload["skipped"][0]["code"] == "UNSUPPORTED_FORM"


def test_cli_can_restrict_forms_and_limit_reporting(fixture_root, capsys):
    assert main(["MSFT", "--sec-root", str(fixture_root), "--forms", "10-K", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert [filing["form"] for filing in payload["filings"]] == ["10-K"]
    assert [record["form"] for record in payload["skipped"]] == ["10-Q", "8-K", "10-Q"]

    assert main(["MSFT", "--sec-root", str(fixture_root), "--limit", "1", "--json"]) == 0
    limited = json.loads(capsys.readouterr().out)

    assert [filing["accession"] for filing in limited["filings"]] == ["0000000000-24-000001"]
    assert limited["filings_scanned"] == 2


def test_cli_fails_when_the_ticker_index_is_missing(tmp_path, capsys):
    assert main(["MSFT", "--sec-root", str(tmp_path)]) == 1
    assert "MISSING_INDEX" in capsys.readouterr().out


def test_default_sec_root_follows_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("FDC_SEC_ROOT", raising=False)
    assert default_sec_root().name == "sec"

    monkeypatch.setenv("FDC_SEC_ROOT", str(tmp_path / "archive"))
    assert default_sec_root() == tmp_path / "archive"
