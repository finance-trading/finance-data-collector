"""Hard eligibility gates for the versioned CQ_V2 definition."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class V2GateResult:
    status: str
    gates: dict[str, bool | None]
    metrics: dict[str, float | int | None]
    unknown_reasons: list[str]


def _missing(frame: pd.DataFrame, column: str) -> bool:
    return column not in frame or pd.to_numeric(frame[column], errors="coerce").isna().any()


def evaluate_v2_hard_gates(annual: pd.DataFrame, *, cash: float | None, debt: float | None) -> V2GateResult:
    """Evaluate the documented five-year hard gates using latest annual data."""
    gates: dict[str, bool | None] = {}
    metrics: dict[str, float | int | None] = {}
    unknown: list[str] = []
    if len(annual) != 5:
        return V2GateResult("UNKNOWN", {}, {"annual_year_count": len(annual)}, ["missing_five_year_window"])

    required = ("operating_income", "net_income", "cfo")
    missing = [name for name in required if _missing(annual, name)]
    if missing:
        return V2GateResult("UNKNOWN", {}, {"annual_year_count": len(annual)}, [f"missing_{name}" for name in missing])
    values = annual.copy()
    for name in ("operating_income", "net_income", "cfo", "interest_expense", "depreciation_amortization"):
        if name in values:
            values[name] = pd.to_numeric(values[name], errors="coerce")

    op = values["operating_income"]
    cfo = values["cfo"]
    ni = values["net_income"]
    metrics.update({
        "annual_year_count": 5,
        "positive_operating_income_years": int((op > 0).sum()),
        "positive_cfo_years": int((cfo > 0).sum()),
        "cumulative_net_income": float(ni.sum()),
        "cumulative_cfo": float(cfo.sum()),
    })
    gates["operating_income_continuity"] = metrics["positive_operating_income_years"] >= 4
    gates["cfo_continuity"] = metrics["positive_cfo_years"] >= 4
    gates["latest_operating_income_positive"] = bool(op.iloc[-1] > 0)
    gates["latest_cfo_positive"] = bool(cfo.iloc[-1] > 0)
    gates["cumulative_net_income_positive"] = metrics["cumulative_net_income"] > 0
    gates["cumulative_cfo_support"] = (
        metrics["cumulative_net_income"] > 0
        and metrics["cumulative_cfo"] >= 0.8 * metrics["cumulative_net_income"]
    )

    if cash is None or debt is None or pd.isna(cash) or pd.isna(debt):
        unknown.append("missing_net_debt")
    else:
        net_debt = float(debt) - float(cash)
        metrics["net_debt"] = net_debt
        if net_debt <= 0:
            metrics["net_debt_ebitda"] = 0.0
            gates["net_debt_ebitda"] = True
        elif "depreciation_amortization" not in values or pd.isna(values["depreciation_amortization"].iloc[-1]):
            unknown.append("missing_depreciation_amortization")
        else:
            ebitda = float(op.iloc[-1] + values["depreciation_amortization"].iloc[-1])
            metrics["latest_ebitda"] = ebitda
            if ebitda <= 0:
                metrics["net_debt_ebitda"] = None
                gates["net_debt_ebitda"] = False
            else:
                leverage = net_debt / ebitda
                metrics["net_debt_ebitda"] = leverage
                gates["net_debt_ebitda"] = leverage <= 3.0

    if "interest_expense" not in values or pd.isna(values["interest_expense"].iloc[-1]):
        if debt is not None and cash is not None and float(debt) == 0 and float(cash) >= 0:
            gates["interest_coverage"] = True
        else:
            unknown.append("missing_interest_expense")
    else:
        interest = abs(float(values["interest_expense"].iloc[-1]))
        if interest == 0 and debt is not None and float(debt) <= 0:
            gates["interest_coverage"] = True
            metrics["interest_coverage"] = float("inf")
        elif interest == 0:
            gates["interest_coverage"] = False
            metrics["interest_coverage"] = None
        else:
            coverage = float(op.iloc[-1]) / interest
            metrics["interest_coverage"] = coverage
            gates["interest_coverage"] = coverage >= 4.0

    if unknown:
        return V2GateResult("UNKNOWN", gates, metrics, sorted(set(unknown)))
    status = "QUALIFIED" if all(value is True for value in gates.values()) else "NOT_QUALIFIED"
    return V2GateResult(status, gates, metrics, [])
