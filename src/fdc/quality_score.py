"""CQ_V2 scores from supplied annual facts and full peer universe.

The historical snapshot also used an external SEC cache; this calculation does
not, so recalculated values need not match that historical snapshot.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Mapping

import numpy as np
import pandas as pd

from fdc.quality_gates import evaluate_v2_hard_gates

POLICY = "CQ_EDGARTOOLS_SEMANTIC_POLICY_V2"
CORE = ("revenue", "operating_income", "net_income", "cfo", "capex")
V2_AUX = ("interest_expense", "depreciation_amortization")

def local_tag(value: object) -> str:
    return str(value).split(":", 1)[-1]


def instant_series(frame: pd.DataFrame, metric: str, preferred: tuple[str, ...]) -> pd.Series:
    """Choose canonical balance-sheet facts instead of arbitrary last rows."""
    rows = frame[frame.metric.eq(metric)].copy()
    if rows.empty:
        return pd.Series(dtype=float)
    rows["tag"] = rows.concept.map(local_tag)
    rows["priority"] = rows.tag.map({tag: i for i, tag in enumerate(preferred)}).fillna(len(preferred))
    rows = rows.sort_values(["end", "priority", "filing", "accession"], ascending=[True, True, False, False], kind="stable")
    return rows.drop_duplicates("end", keep="first").set_index("end")["value_num"]


def debt_series(frame: pd.DataFrame) -> pd.Series:
    """Prefer reported total debt, then reconstruct from current/noncurrent parts."""
    rows = frame[frame.metric.eq("debt")].copy()
    if rows.empty:
        return pd.Series(dtype=float)
    rows["tag"] = rows.concept.map(local_tag)
    priority = {"DebtLongtermAndShorttermCombinedAmount": 0, "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities": 1, "LongTermDebtAndCapitalLeaseObligations": 2, "LongTermDebt": 3}
    rows["priority"] = rows.tag.map(priority).fillna(99)
    result = {}
    for end, group in rows.groupby("end"):
        totals = group[group.priority.lt(99)].sort_values(["priority", "filing", "accession"], ascending=[True, False, False], kind="stable")
        if not totals.empty:
            result[end] = float(totals.iloc[0].value_num)
            continue
        parts = group[group.tag.isin({"LongTermDebtCurrent", "LongTermDebtNoncurrent", "ShortTermBorrowings", "OtherShortTermBorrowings", "OtherLongTermDebt", "OtherLongTermDebtNoncurrent", "UnsecuredLongTermDebt"})]
        if not parts.empty:
            # Sum one latest-filed observation per component tag.
            latest = parts.sort_values(["filing", "accession"], ascending=[False, False], kind="stable").drop_duplicates("tag")
            result[end] = float(latest.value_num.sum())
    return pd.Series(result, dtype=float)


def norm_cik(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(10)




def rank_peer_metrics(frame: pd.DataFrame, peer_key: str, metric_specs: Mapping[str, str]) -> pd.DataFrame:
    if peer_key not in frame.columns:
        raise ValueError(f"missing peer key: {peer_key}")
    result = frame.copy()
    for metric, direction in metric_specs.items():
        if metric not in result.columns:
            raise ValueError(f"missing peer metric: {metric}")
        if direction not in {"high", "low"}:
            raise ValueError(f"invalid direction: {direction}")
        count = result.groupby(peer_key)[metric].transform(lambda values: values.notna().sum())
        ranks = result.groupby(peer_key)[metric].rank(method="average", ascending=True)
        score = 100.0 * (ranks - 1.0) / (count - 1.0)
        if direction == "low":
            score = 100.0 - score
        result[f"{metric}_peer_count"] = count
        result[f"{metric}_peer_score"] = score.where(count >= 10)
    result["peer_count"] = result.groupby(peer_key)[next(iter(metric_specs))].transform(lambda v: v.notna().sum())
    result["peer_score"] = result[[f"{metric}_peer_score" for metric in metric_specs]].mean(axis=1, skipna=False)
    return result


def latest_complete_annual_periods(complete: pd.Series[set[str]], required_metrics: set[str], limit: int = 5) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return the latest contiguous complete annual periods."""
    by_end: dict[pd.Timestamp, list[pd.Timestamp]] = {}
    for (start, end), metrics in complete.items():
        if required_metrics.issubset(metrics):
            days = (end - start).days + 1
            if 330 <= days <= 400:
                by_end.setdefault(end, []).append(start)
    contiguous: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for end in sorted(by_end):
        starts = sorted(by_end[end], key=lambda start: (abs((end - start).days + 1 - 365), start))
        next_start = pd.Timestamp(contiguous[-1][1]).date() + timedelta(days=1) if contiguous else None
        matching = next((start for start in starts if next_start is not None and pd.Timestamp(start).date() == next_start), None)
        contiguous = [*contiguous, (matching, end)] if matching is not None else [(starts[0], end)]
    return contiguous[-limit:]


def calculate_quality_scores(facts: pd.DataFrame, universe: pd.DataFrame, rating_cutoff: date) -> pd.DataFrame:
    required_facts = {"cik", "concept", "metric", "numeric_value", "period_type", "period_start", "period_end", "filing_date", "accession"}
    required_universe = {"cik", "canonical_symbol", "company_name", "gics_sector"}
    for label, frame, required in (("facts", facts, required_facts), ("universe", universe, required_universe)):
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"missing {label} columns: {', '.join(sorted(missing))}")
    facts = facts.copy().fillna("")
    universe = universe.copy().fillna("")
    facts["cik"] = norm_cik(facts["cik"])
    universe["cik"] = norm_cik(universe["cik"])
    universe["canonical_symbol"] = universe["canonical_symbol"].str.strip().str.upper()
    if universe["canonical_symbol"].duplicated().any():
        raise ValueError("duplicate universe ticker")
    # Rank each issuer once, retaining its verified ticker/CIK mapping for
    # expansion only after the peer scores have been calculated.
    universe = universe[universe["cik"].isin(set(facts["cik"]))]
    if universe.groupby("cik")["gics_sector"].nunique().gt(1).any():
        raise ValueError("conflicting sectors for shared CIK")
    share_classes = universe[["cik", "canonical_symbol", "company_name"]].copy()
    universe = universe.drop_duplicates("cik", keep="last")
    if universe.empty:
        raise ValueError("missing matching peer universe")
    facts["value_num"] = pd.to_numeric(facts["numeric_value"].replace("", np.nan), errors="coerce")
    facts["start"] = pd.to_datetime(facts["period_start"], errors="coerce")
    facts["end"] = pd.to_datetime(facts["period_end"], errors="coerce")
    facts["filing"] = pd.to_datetime(facts["filing_date"], errors="coerce")
    cutoff = pd.Timestamp(rating_cutoff)
    facts = facts[facts["end"].le(cutoff) & facts["filing"].le(cutoff)].copy()
    duration = facts[facts["period_type"].eq("duration") & facts["metric"].isin(CORE + V2_AUX)].copy()
    duration["days"] = (duration["end"] - duration["start"]).dt.days + 1
    duration = duration[duration["days"].between(330, 400) & duration["value_num"].notna()]
    instant = facts[facts["period_type"].eq("instant") & facts["value_num"].notna()].copy()
    rows = []
    for cik, u in universe.groupby("cik", sort=True):
        d = duration[duration.cik.eq(cik)].sort_values(["end", "filing", "accession"])
        # One latest filing candidate for each metric and fiscal period.
        d = d.drop_duplicates(["metric", "start", "end"], keep="last")
        complete = d.groupby(["start", "end"])["metric"].agg(set)
        # Ordinary CQ dimensions can still be calculated when an issuer's
        # taxonomy omits operating income or capex. Require the three stable
        # cash/profit series and retain missing dimensions as nulls.
        base = {"revenue", "net_income", "cfo"}
        periods = latest_complete_annual_periods(complete, base)
        annual = d[d.apply(lambda r: (r.start, r.end) in set(periods), axis=1)].copy() if periods else d.iloc[0:0]
        values = annual.pivot_table(index="end", columns="metric", values="value_num", aggfunc="last")
        values = values.reindex(columns=list(CORE + V2_AUX)).sort_index()
        five_year = len(periods) == 5 and len(values) == 5 and values[["revenue", "net_income", "cfo"]].notna().all(axis=None)
        raw = {"cik": cik, "five_year_ready": bool(five_year), "period_ends": "|".join(x[1].date().isoformat() for x in periods)}
        for col in CORE:
            raw[f"{col}_years"] = int(values[col].notna().sum()) if col in values else 0
        if five_year:
            revenue = values.revenue.astype(float)
            capex = values.capex.astype(float) if "capex" in values else pd.Series(index=values.index, dtype=float)
            fcf = values.cfo.astype(float) - capex.abs().fillna(0.0)
            company_instant = instant[instant.cik.eq(cik)]
            assets = instant_series(company_instant, "assets", ("Assets", "AssetsNet"))
            cash = instant_series(company_instant, "cash", ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"))
            debt = debt_series(company_instant)
            # A company with no debt facts at all is treated as zero-debt;
            # a company with partial debt history remains unavailable.
            if debt.empty and not cash.empty:
                debt = pd.Series(0.0, index=cash.index)
            assets = assets.reindex(values.index)
            raw["revenue_growth"] = (revenue.iloc[-1] / revenue.iloc[0]) ** (1 / 4) - 1 if revenue.iloc[0] > 0 and revenue.iloc[-1] > 0 else np.nan
            raw["operating_margin"] = (values.operating_income / revenue).replace([np.inf, -np.inf], np.nan).median() if values.operating_income.notna().any() else np.nan
            raw["cash_conversion"] = (fcf / revenue).replace([np.inf, -np.inf], np.nan).median()
            raw["capital_efficiency"] = (values.net_income / ((assets + assets.shift(1)) / 2)).replace([np.inf, -np.inf], np.nan).median()
            latest_end = values.index[-1]
            latest_fcf = float(fcf.iloc[-1])
            # A company that disclosed no debt facts at all is treated as
            # zero-debt (branch above). A company with debt history but no
            # latest-period fact stays unavailable; debt is never inferred
            # as zero for a period without a reported balance.
            v2_cash = float(cash.loc[latest_end]) if latest_end in cash.index else None
            v2_debt = float(debt.loc[latest_end]) if latest_end in debt.index else None
            v2 = evaluate_v2_hard_gates(values.reset_index(drop=True), cash=v2_cash, debt=v2_debt)
            raw["v2_hard_status"] = v2.status
            raw["v2_unknown_reasons"] = "|".join(v2.unknown_reasons)
            raw["v2_hard_gate_count"] = int(sum(value is True for value in v2.gates.values()))
            raw["v2_hard_gate_total"] = int(len(v2.gates))
            raw["v2_net_debt_ebitda"] = v2.metrics.get("net_debt_ebitda", np.nan)
            raw["v2_interest_coverage"] = v2.metrics.get("interest_coverage", np.nan)
            raw["v2_cumulative_net_income"] = v2.metrics.get("cumulative_net_income", np.nan)
            raw["v2_cumulative_cfo"] = v2.metrics.get("cumulative_cfo", np.nan)
            raw["v2_positive_operating_income_years"] = v2.metrics.get("positive_operating_income_years", np.nan)
            raw["v2_positive_cfo_years"] = v2.metrics.get("positive_cfo_years", np.nan)
            nd = (float(debt.reindex([latest_end]).iloc[0]) - float(cash.reindex([latest_end]).iloc[0])) if latest_end in debt.index and latest_end in cash.index else np.nan
            raw["financial_strength"] = (-nd / latest_fcf) if pd.notna(nd) and latest_fcf > 0 else (1.0 if pd.notna(nd) and nd <= 0 else np.nan)
            raw["positive_fcf_years"] = int((fcf > 0).sum())
            raw["capex_available"] = int(values.capex.notna().sum())
            raw["operating_income_available"] = int(values.operating_income.notna().sum())
            raw["latest_fcf"] = latest_fcf
        else:
            for name in ("revenue_growth", "operating_margin", "cash_conversion", "capital_efficiency", "financial_strength", "latest_fcf"):
                raw[name] = np.nan
            raw["positive_fcf_years"] = np.nan
            raw["v2_hard_status"] = "UNKNOWN"
            raw["v2_unknown_reasons"] = "missing_five_year_window"
            raw["v2_hard_gate_count"] = 0
            raw["v2_hard_gate_total"] = 0
            for name in ("v2_net_debt_ebitda", "v2_interest_coverage", "v2_cumulative_net_income", "v2_cumulative_cfo", "v2_positive_operating_income_years", "v2_positive_cfo_years"):
                raw[name] = np.nan
        row = dict(u.iloc[0].to_dict())
        row.update(raw)
        rows.append(row)
    raw = pd.DataFrame(rows)
    metric_specs = {"revenue_growth": "high", "operating_margin": "high", "cash_conversion": "high", "capital_efficiency": "high", "financial_strength": "high"}
    ranked = rank_peer_metrics(raw, "gics_sector", metric_specs)
    for metric in metric_specs:
        ranked[f"{metric}_dimension"] = ranked[f"{metric}_peer_score"]
    dim_cols = [f"{m}_dimension" for m in metric_specs]
    ranked["dimension_count"] = ranked[dim_cols].notna().sum(axis=1)
    ranked["dimension_score"] = ranked[dim_cols].mean(axis=1, skipna=True)
    ranked["data_status"] = np.where(ranked["dimension_count"].ge(5), "READY", "UNKNOWN")
    ranked["quality_score"] = ranked["dimension_score"]
    ranked["score_available"] = ranked["data_status"].eq("READY")
    ranked["status"] = "UNKNOWN"
    ranked.loc[ranked["v2_hard_status"].eq("NOT_QUALIFIED"), "status"] = "NOT_QUALIFIED"
    ranked.loc[ranked["score_available"] & ranked["v2_hard_status"].eq("QUALIFIED") & (ranked["dimension_score"] >= 70) & (ranked["capital_efficiency_dimension"] >= 50) & (ranked["cash_conversion_dimension"] >= 50), "status"] = "QUALIFIED"
    ranked.loc[ranked["score_available"] & ranked["status"].eq("UNKNOWN") & ranked["v2_hard_status"].eq("QUALIFIED"), "status"] = "NOT_QUALIFIED"
    ranked["unknown_reasons"] = np.where(ranked["score_available"], ranked["v2_unknown_reasons"], "missing_complete_five_dimensions")
    ranked["model_status"] = np.where(ranked["gics_sector"].isin({"Financials", "Real Estate"}), "SEPARATE_MODEL", "ORDINARY_CQ")
    ranked.loc[ranked["model_status"].eq("SEPARATE_MODEL"), "status"] = "SEPARATE_MODEL"
    ranked["rule_version"] = "CQ_V2"
    ranked["semantic_policy"] = POLICY.replace("V1", "V2")
    ranked["rating_cutoff"] = rating_cutoff.isoformat()
    return ranked.drop(columns=["canonical_symbol", "company_name"]).merge(
        share_classes, on="cik", how="inner", validate="one_to_many"
    )


def match_catalog_companies(scores: pd.DataFrame, catalog: object) -> pd.DataFrame:
    if "canonical_symbol" not in scores:
        raise ValueError("missing score canonical_symbol")
    symbols = scores["canonical_symbol"].astype(str).str.strip().str.upper()
    if symbols.duplicated().any():
        raise ValueError("duplicate score ticker")
    catalog_tickers = [company.ticker.strip().upper() for company in catalog.companies]
    if len(set(catalog_tickers)) != len(catalog_tickers):
        raise ValueError("duplicate catalog ticker")
    by_ticker = {company.ticker.strip().upper(): company for company in catalog.companies}
    matched = scores.loc[symbols.isin(catalog_tickers)].copy()
    if "cik" in matched:
        def normalized_cik(value: object) -> str | None:
            if value is None or pd.isna(value) or not str(value).strip():
                return None
            text = str(value).strip().removeprefix("CIK").removesuffix(".0")
            if not text.isascii() or not text.isdigit() or len(text) > 10:
                raise ValueError(f"invalid CIK: {value}")
            return text.zfill(10)

        # Each result already carries its source-universe ticker and CIK.
        # Exact ticker matches allow distinct share classes of the same issuer;
        # never infer an additional catalog ticker from CIK alone.
        for _, row in matched.iterrows():
            ticker = str(row["canonical_symbol"]).strip().upper()
            score_cik = normalized_cik(row["cik"])
            catalog_cik = normalized_cik(getattr(by_ticker[ticker], "cik", None))
            if score_cik and catalog_cik and score_cik != catalog_cik:
                raise ValueError(f"CIK conflict for {ticker}: catalog={catalog_cik}, score={score_cik}")
    return matched
