import json
from pathlib import Path


FIXTURE = Path(__file__).parents[1] / "fixtures" / "quality_score" / "cq_v2_source_sample.json"
DIMENSIONS = (
    "revenue_growth_dimension",
    "operating_margin_dimension",
    "cash_conversion_dimension",
    "capital_efficiency_dimension",
    "financial_strength_dimension",
)


def load_fixture():
    return json.loads(FIXTURE.read_text())


def test_source_fixture_covers_all_quality_statuses_and_metadata():
    fixture = load_fixture()
    assert {row["status"] for row in fixture["samples"]} == {
        "QUALIFIED",
        "NOT_QUALIFIED",
        "UNKNOWN",
        "SEPARATE_MODEL",
    }
    assert any(row["score_available"] == "False" for row in fixture["samples"])
    assert fixture["metadata"] == {
        "source_run_id": "cq-edgartools-rating-snapshot-2026-10-05-cqv2-v4",
        "rating_cutoff": "2026-09-30",
        "rule_version": "CQ_V2",
        "semantic_policy": "CQ_EDGARTOOLS_SEMANTIC_POLICY_V2",
        "peer_key": "gics_sector",
        "peer_minimum": 10,
        "rating_snapshot_sha256": "2d488db42d5d11358a29f566d9220b87a91187595aea63bf6f45d77909e28b17",
    }


def test_source_fixture_preserves_company_identity_and_row_metadata():
    rows = load_fixture()["samples"]
    for row in rows:
        assert isinstance(row["cik"], str)
        assert len(row["cik"]) == 10 and row["cik"].isascii() and row["cik"].isdigit()
        assert row["ticker"] == row["canonical_symbol"]
        assert row["rating_cutoff"] == "2026-09-30"
        assert row["rule_version"] == "CQ_V2"
        assert row["semantic_policy"] == "CQ_EDGARTOOLS_SEMANTIC_POLICY_V2"
    by_ticker = {row["ticker"]: row for row in rows}
    assert by_ticker["CL"]["cik"] == "0000021665"
    assert by_ticker["CL"]["quality_score"] == 70.66666666666666
    assert by_ticker["APD"]["cik"] == "0000002969"
    assert by_ticker["APD"]["score_available"] == "False"
    assert by_ticker["APD"]["quality_score"] == 53.977272727272734


def test_source_fixture_has_dimensions_and_preserves_unavailable_scores():
    for row in load_fixture()["samples"]:
        assert all(field in row for field in DIMENSIONS)
        assert "quality_score" in row
        assert "unknown_reasons" in row
        assert "v2_unknown_reasons" in row
        if row["score_available"] == "True":
            assert isinstance(row["quality_score"], (int, float))
        else:
            # CQ_V2 retains a diagnostic mean even when a missing dimension
            # makes the score unavailable for certification.
            assert row["quality_score"] is None or isinstance(row["quality_score"], (int, float))
            assert any(row[field] is None for field in DIMENSIONS)
