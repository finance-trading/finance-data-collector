import importlib.util
from pathlib import Path

from fdc.sec_storage import default_output_dir

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _fake_response():
    return type("Response", (), {"content": b"ok"})()


def _load_sec_downloader():
    script = (
        PROJECT_ROOT
        / ".agents"
        / "skills"
        / "sec-filings-download"
        / "scripts"
        / "download_sec_filings.py"
    )
    spec = importlib.util.spec_from_file_location("download_sec_filings", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_output_dir_uses_central_sec_root():
    assert default_output_dir("msft") == PROJECT_ROOT / "sec" / "MSFT"


def test_download_filing_skips_images_by_default(monkeypatch, tmp_path):
    downloader = _load_sec_downloader()
    monkeypatch.setattr(
        downloader,
        "get_filing_files",
        lambda cik, accession, ua: ["report.htm", "chart.jpg"],
    )
    monkeypatch.setattr(downloader, "_get", lambda url, timeout: _fake_response())
    monkeypatch.setattr(downloader, "_tick_api", lambda: None)

    downloaded = downloader.download_filing(
        123,
        {"form": "10-K", "accession": "0000123-24-000001"},
        tmp_path,
        "test@example.com/1.0",
        force=False,
    )

    assert [path.name for path in downloaded] == ["report.htm"]
    assert (tmp_path / "10-K" / "0000123-24-000001" / "report.htm").exists()
    assert not (tmp_path / "10-K" / "0000123-24-000001" / "chart.jpg").exists()


def test_download_filing_can_include_images_explicitly(monkeypatch, tmp_path):
    downloader = _load_sec_downloader()
    monkeypatch.setattr(
        downloader,
        "get_filing_files",
        lambda cik, accession, ua: ["report.htm", "chart.jpg"],
    )
    monkeypatch.setattr(downloader, "_get", lambda url, timeout: _fake_response())
    monkeypatch.setattr(downloader, "_tick_api", lambda: None)

    downloaded = downloader.download_filing(
        123,
        {"form": "10-K", "accession": "0000123-24-000001"},
        tmp_path,
        "test@example.com/1.0",
        force=False,
        no_images=False,
    )

    assert [path.name for path in downloaded] == ["report.htm", "chart.jpg"]
