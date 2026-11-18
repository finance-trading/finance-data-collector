from datetime import date

import pandas as pd
import pytest

from fdc.quality_score import calculate_quality_scores, match_catalog_companies, rank_peer_metrics


def test_peer_rank_requires_ten_comparable_companies_and_uses_full_universe():
    frame = pd.DataFrame({"sector": ["A"] * 10 + ["B"] * 9, "value": list(range(10)) + list(range(9))})
    ranked = rank_peer_metrics(frame, "sector", {"value": "high"})
    assert ranked.loc[0, "value_peer_score"] == 0
    assert ranked.loc[9, "value_peer_score"] == 100
    assert ranked.loc[10:, "value_peer_score"].isna().all()


def test_rejects_missing_source_columns():
    with pytest.raises(ValueError, match="missing"):
        calculate_quality_scores(pd.DataFrame(), pd.DataFrame(), date(2026, 9, 30))


def test_match_catalog_filters_after_ranking_and_normalizes_tickers():
    scores = pd.DataFrame({"canonical_symbol": ["AAA", "BBB"], "cik": ["0000000001", "0000000002"], "quality_score": [80, 20]})
    catalog = type("Catalog", (), {"companies": [type("Company", (), {"ticker": "aaa"})()]})()
    result = match_catalog_companies(scores, catalog)
    assert result["canonical_symbol"].tolist() == ["AAA"]
    assert result["quality_score"].tolist() == [80]


def _inputs(years=(2020, 2021, 2022, 2023, 2024), missing_latest_debt=False):
    rows = []
    for year in years:
        start, end = f"{year}-01-01", f"{year}-12-31"
        for metric, value in {"revenue": 100, "operating_income": 20, "net_income": 10, "cfo": 20, "capex": 5, "interest_expense": 2, "depreciation_amortization": 5}.items():
            rows.append({"cik": "1", "concept": metric, "metric": metric, "numeric_value": value, "period_type": "duration", "period_start": start, "period_end": end, "filing_date": f"{year + 1}-02-01", "accession": str(year)})
        for metric, concept, value in (("assets", "Assets", 100), ("cash", "CashAndCashEquivalentsAtCarryingValue", 10), ("debt", "LongTermDebt", 20)):
            if metric == "debt" and missing_latest_debt and year == max(years):
                continue
            rows.append({"cik": "1", "concept": concept, "metric": metric, "numeric_value": value, "period_type": "instant", "period_start": "", "period_end": end, "filing_date": f"{year + 1}-02-01", "accession": str(year)})
    universe = pd.DataFrame([{"cik": "1", "canonical_symbol": "AAA", "company_name": "A", "gics_sector": "Technology"}])
    return pd.DataFrame(rows), universe


def test_hand_calculated_dimensions_and_insufficient_peers():
    facts, universe = _inputs()
    row = calculate_quality_scores(facts, universe, date(2025, 3, 1)).iloc[0]
    assert row["five_year_ready"]
    assert row["revenue_growth"] == pytest.approx(0)
    assert row["operating_margin"] == pytest.approx(0.2)
    assert row["cash_conversion"] == pytest.approx(0.15)
    assert row["capital_efficiency"] == pytest.approx(0.1)
    assert row["financial_strength"] == pytest.approx(-10 / 15)
    assert pd.isna(row["peer_score"])
    assert not row["score_available"]


def test_noncontiguous_periods_are_not_five_year_window():
    facts, universe = _inputs((2019, 2020, 2022, 2023, 2024))
    row = calculate_quality_scores(facts, universe, date(2025, 3, 1)).iloc[0]
    assert not row["five_year_ready"]
    assert row["v2_hard_status"] == "UNKNOWN"
    assert row["v2_unknown_reasons"] == "missing_five_year_window"


def test_missing_latest_debt_does_not_assume_zero():
    facts, universe = _inputs(missing_latest_debt=True)
    row = calculate_quality_scores(facts, universe, date(2025, 3, 1)).iloc[0]
    assert pd.isna(row["v2_net_debt_ebitda"])
    assert row["v2_hard_status"] == "UNKNOWN"


def test_three_years_and_cutoff_exclude_incomplete_window():
    facts, universe = _inputs()
    row = calculate_quality_scores(facts, universe, date(2023, 3, 1)).iloc[0]
    assert not row["five_year_ready"]
    assert all(pd.isna(row[name]) for name in ("revenue_growth", "operating_margin", "cash_conversion", "capital_efficiency", "financial_strength"))


def test_catalog_cik_conflict_is_explicit():
    scores = pd.DataFrame({"canonical_symbol": ["AAA"], "cik": ["0000000001"]})
    company = type("Company", (), {"ticker": "AAA", "cik": "2"})()
    catalog = type("Catalog", (), {"companies": [company]})()
    with pytest.raises(ValueError, match="AAA.*0000000002.*0000000001"):
        match_catalog_companies(scores, catalog)


def test_catalog_without_cik_matches_by_ticker():
    scores = pd.DataFrame({"canonical_symbol": ["AAA"], "cik": ["0000000001"]})
    company = type("Company", (), {"ticker": "aaa", "cik": None})()
    catalog = type("Catalog", (), {"companies": [company]})()
    assert len(match_catalog_companies(scores, catalog)) == 1


def test_balance_facts_choose_latest_filing_and_accession():
    from fdc.quality_score import debt_series, instant_series

    frame = pd.DataFrame([
        {"metric": metric, "concept": tag, "end": pd.Timestamp("2024-12-31"),
         "filing": pd.Timestamp(filing), "accession": accession, "value_num": value}
        for metric, tag in (("assets", "Assets"), ("debt", "LongTermDebt"))
        for filing, accession, value in (("2025-02-01", "a", 10), ("2025-03-01", "a", 20), ("2025-03-01", "b", 30))
    ])
    assert instant_series(frame, "assets", ("Assets",)).iloc[0] == 30
    assert debt_series(frame).iloc[0] == 30


def test_debt_components_choose_latest_filing():
    from fdc.quality_score import debt_series

    frame = pd.DataFrame([
        {"metric": "debt", "concept": tag, "end": pd.Timestamp("2024-12-31"),
         "filing": pd.Timestamp(filing), "accession": "a", "value_num": value}
        for tag, filing, value in (("LongTermDebtCurrent", "2025-03-01", 20), ("LongTermDebtCurrent", "2025-02-01", 10), ("LongTermDebtNoncurrent", "2025-02-01", 50))
    ])
    assert debt_series(frame).iloc[0] == 70


@pytest.mark.parametrize("debt,interest,leverage_ok,coverage_ok", [(85, 5, True, True), (85.01, 5, False, True), (85, 5.01, True, False)])
def test_hard_gate_thresholds(debt, interest, leverage_ok, coverage_ok):
    from fdc.quality_gates import evaluate_v2_hard_gates

    annual = pd.DataFrame({"operating_income": [20] * 5, "net_income": [10] * 5, "cfo": [20] * 5,
                           "depreciation_amortization": [5] * 5, "interest_expense": [interest] * 5})
    result = evaluate_v2_hard_gates(annual, cash=10, debt=debt)
    assert result.gates["net_debt_ebitda"] == leverage_ok
    assert result.gates["interest_coverage"] == coverage_ok


@pytest.mark.parametrize("sector", ["Financials", "Real Estate"])
def test_financial_and_real_estate_use_separate_model(sector):
    facts, universe = _inputs()
    universe.loc[0, "gics_sector"] = sector
    row = calculate_quality_scores(facts, universe, date(2025, 3, 1)).iloc[0]
    assert row["status"] == "SEPARATE_MODEL"


def test_shared_cik_share_classes_require_catalog_confirmation():
    scores = pd.DataFrame({"canonical_symbol": ["AAA", "AAB"], "cik": ["1", "1"]})
    company = lambda ticker, cik: type("Company", (), {"ticker": ticker, "cik": cik})()
    catalog = type("Catalog", (), {"companies": [company("AAA", "1"), company("AAB", "1")]})()
    assert len(match_catalog_companies(scores, catalog)) == 2
    catalog.companies[1].cik = None
    assert len(match_catalog_companies(scores, catalog)) == 2


def test_calculation_preserves_share_classes_without_double_counting_peers():
    facts, universe = _inputs()
    universe = pd.concat([universe, universe.assign(canonical_symbol="AAB")], ignore_index=True)
    scores = calculate_quality_scores(facts, universe, date(2025, 3, 1))
    assert set(scores.canonical_symbol) == {"AAA", "AAB"}
    assert scores.peer_count.tolist() == [1, 1]
    company = lambda ticker, cik: type("Company", (), {"ticker": ticker, "cik": cik})()
    catalog = type("Catalog", (), {"companies": [company("AAA", "1"), company("AAB", "1")]})()
    matched = match_catalog_companies(scores, catalog)
    assert set(matched.canonical_symbol) == {"AAA", "AAB"}
    assert matched.revenue_growth.nunique() == 1
    catalog.companies[1].cik = None
    assert len(match_catalog_companies(scores, catalog)) == 2


def test_catalog_without_cik_matches_source_universe_share_classes():
    from fdc.catalog import load_catalog

    facts, universe = _inputs()
    universe.loc[0, "canonical_symbol"] = "GOOG"
    universe = pd.concat([universe, universe.assign(canonical_symbol="GOOGL")], ignore_index=True)
    scores = calculate_quality_scores(facts, universe, date(2025, 3, 1))
    matched = match_catalog_companies(scores, load_catalog())
    assert set(matched.canonical_symbol) == {"GOOG", "GOOGL"}
    assert matched.peer_count.tolist() == [1, 1]


def test_duplicate_catalog_ticker_rejected():
    scores = pd.DataFrame({"canonical_symbol": ["AAA"], "cik": ["1"]})
    company = lambda ticker: type("Company", (), {"ticker": ticker, "cik": "1"})()
    catalog = type("Catalog", (), {"companies": [company("AAA"), company("aaa")]})()
    with pytest.raises(ValueError, match="duplicate catalog ticker"):
        match_catalog_companies(scores, catalog)
