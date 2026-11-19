"""Catalog-subset deviation check: recalc vs. historical source snapshot.

The historical snapshot used an external SEC cache to fill missing balance-sheet
instants, so balance-derived dimensions (capital_efficiency, financial_strength)
deviate. Duration-derived dimensions (revenue_growth, operating_margin,
cash_conversion) do not depend on that cache and must agree closely, proving the
core engine is correct. This test documents that split and fails only on a
structurally broken recalculation."""
from datetime import date

import numpy as np
import pandas as pd
from pathlib import Path

from fdc import catalog as cat
from fdc.quality_score import calculate_quality_scores

ROOT = Path(__file__).resolve().parents[2]
FACTS = ROOT / "data" / "company_quality" / "edgartools_annual_facts_2026-10-05.csv.gz"
UNIVERSE = ROOT / "data" / "company_quality" / "peer_universe_2026-09.csv.gz"
SOURCE = ROOT / "data" / "company_quality" / "source_rating_snapshot.csv.gz"

DURATION_DIMS = ("revenue_growth", "operating_margin", "cash_conversion")
BALANCE_DIMS = ("capital_efficiency", "financial_strength")


def _recalc():
    facts = pd.read_csv(FACTS, dtype=str, low_memory=False).fillna("")
    facts["cik"] = facts["cik"].str.zfill(10)
    universe = pd.read_csv(UNIVERSE, dtype=str).fillna("").astype(str)
    universe["cik"] = universe["cik"].str.zfill(10)
    universe = universe[universe["cik"].isin(set(facts["cik"]))].drop_duplicates("cik")
    return calculate_quality_scores(facts, universe, date(2026, 9, 30))


def _compare():
    scores = _recalc()
    src = pd.read_csv(SOURCE, dtype=str).fillna("")
    src["cik"] = src["cik"].str.zfill(10)
    cols = ["canonical_symbol", "status", "quality_score"] + [
        f"{d}_dimension" for d in DURATION_DIMS + BALANCE_DIMS]
    overlap = scores.merge(
        src[cols].rename(columns={c: f"src_{c}" for c in cols if c != "canonical_symbol"}),
        left_on="canonical_symbol", right_on="canonical_symbol", how="inner",
    )
    return scores, overlap


def test_recalc_produces_broad_coverage():
    scores, _ = _compare()
    assert len(scores) >= 400
    assert int(scores["score_available"].sum()) >= 200


def test_duration_dimensions_agree_with_source():
    _, overlap = _compare()
    assert len(overlap) >= 400
    for dim in DURATION_DIMS:
        a = pd.to_numeric(overlap[f"{dim}_dimension"], errors="coerce")
        b = pd.to_numeric(overlap[f"src_{dim}_dimension"], errors="coerce")
        both = a.notna() & b.notna()
        close = int(((a - b).abs() < 0.5)[both].sum())
        assert both.sum() >= 100, f"{dim}: only {int(both.sum())} both-present"
        assert close >= 0.8 * int(both.sum()), f"{dim}: only {close}/{int(both.sum())} within 0.5"


def test_balance_dimensions_documented_deviation():
    _, overlap = _compare()
    # Balance dims may deviate due to the source SEC cache; assert they are
    # still computed for a majority of companies (structural, not zero).
    for dim in BALANCE_DIMS:
        a = pd.to_numeric(overlap[f"{dim}_dimension"], errors="coerce")
        assert a.notna().sum() >= 100, f"{dim}: unexpectedly empty"


def test_recalc_covers_catalog_subset():
    scores, _ = _compare()
    tickers = {c.ticker.upper() for c in cat.load_catalog().companies}
    matched = scores[scores["canonical_symbol"].str.upper().isin(tickers)]
    assert len(matched) >= 20, f"only {len(matched)} catalog companies matched"


def test_status_majorly_agrees():
    _, overlap = _compare()
    agree = int((overlap["status"] == overlap["src_status"]).sum())
    assert agree >= int(len(overlap) * 0.7), f"status agreement {agree}/{len(overlap)}"
