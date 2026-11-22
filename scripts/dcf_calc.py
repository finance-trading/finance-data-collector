"""Shared DCF calculator for the Tier-1 batch (see reports/tier1-dcf/_brief.md).

Reads a per-ticker input pack + assumption flags, computes the full model
(FCF projection, WACC, Gordon terminal value, equity value, per-share, 3x3
sensitivity) and prints a JSON result block the report writer pastes in.

Usage:
    uv run python scripts/dcf_calc.py --pack reports/tier1-dcf/_data/AAPL.json \
        --growth 8,7,6,5,4 --margin 34,35,35,36,36 \
        [--da-pct 2,2,2,2,2] [--capex-pct 4,4,4,4,4] \
        [--tax 0.15] [--beta 1.09] [--rf 4.91] [--erp 5.0] [--g 2.0] \
        [--rd-pct 0.04] [--no-leverage]

Defaults follow the batch policy in _meta.json; anything defaulted is flagged in
the output under "assumptions" so the report can cite it as a parameter source.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

POLICY_TAX_RANGE = (0.12, 0.30)
POLICY_BETA_RANGE = (0.3, 2.0)
POLICY_MAX_G = 2.5


def _latest(annuals: dict, metric: str) -> tuple[str, float] | None:
    rows = annuals.get(metric, [])
    for row in rows:  # already sorted desc by end
        if row.get("value") is not None:
            return row["end"], float(row["value"])
    return None


def _pct_list(values: str, n: int, name: str) -> list[float]:
    parts = [float(v) for v in values.split(",") if v.strip() != ""]
    if len(parts) != n:
        raise SystemExit(f"{name}: need {n} comma-separated values, got {len(parts)}")
    return parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--meta", default=None, help="default: sibling _meta.json of the pack")
    parser.add_argument("--growth", default="", help="5 revenue growth rates %/yr, e.g. 8,7,6,5,4")
    parser.add_argument("--margin", default="", help="5 EBIT margins % of revenue, e.g. 30,31,32,33,33")
    parser.add_argument("--da-pct", default="", help="5 D&A % of revenue (default: repeat base-year ratio)")
    parser.add_argument("--capex-pct", default="", help="5 capex % of revenue (default: repeat base-year ratio)")
    parser.add_argument("--tax", type=float, default=None, help="tax rate (default: base-year effective, clamped)")
    parser.add_argument("--beta", type=float, default=None)
    parser.add_argument("--shares", type=float, default=None, help="override diluted shares in the same unit as pack financials")
    parser.add_argument("--rf", type=float, default=None, help="%% (default: _meta risk_free)")
    parser.add_argument("--erp", type=float, default=None, help="%% (default: _meta 5.0)")
    parser.add_argument("--g", type=float, default=2.0, help="terminal growth %% (default 2.0, max 2.5)")
    parser.add_argument("--rd-pct", type=float, default=None, help="cost of debt %% (default: interest/debt, floor 2%%)")
    parser.add_argument("--no-leverage", action="store_true", help="discount at Re only; add net cash to EV")
    parser.add_argument("--base", choices=("annual", "ttm"), default="annual",
                        help="annual = latest fiscal year (default); ttm = trailing four quarters from pack['ttm']")
    parser.add_argument("--label", default="", help="scenario label carried into the result JSON (bear/base/bull)")
    args = parser.parse_args(argv)

    pack = json.loads(Path(args.pack).read_text())
    meta = json.loads(Path(args.meta).read_text()) if args.meta else json.loads(
        (Path(args.pack).parent / "_meta.json").read_text()
    )
    annuals, info, price = pack["annuals"], pack["info"], pack["price_snapshot"]
    assumptions: dict[str, str] = {}

    # --- base year: latest fiscal year, or the TTM block when requested ---
    ttm = pack.get("ttm") or {}
    if args.base == "ttm":
        if not ttm.get("revenue") or not ttm.get("operating_income"):
            raise SystemExit("pack has no TTM block; fetch it with scripts/fetch_dcf_ttm.py")
        base_year = f"TTM {ttm.get('as_of_quarter')}"
        rev0 = float(ttm["revenue"])
        op0 = float(ttm["operating_income"])
        da0 = ttm.get("dda") or 0.0
        capex0 = abs(ttm.get("capex") or 0.0)
        cash = ttm.get("cash") or 0.0
        debt = ttm.get("total_debt") or 0.0
        tax_rows_val = ttm.get("income_tax")
        pretax_val = ttm.get("pretax_income")
        shares = ttm.get("diluted_shares") or info.get("sharesOutstanding")
        tax_rows, pretax_rows = (base_year, tax_rows_val), (base_year, pretax_val)
        assumptions["base"] = f"TTM (4 quarters ending {ttm.get('as_of_quarter')}); annual base would be {_latest(annuals, 'revenue')[0] if _latest(annuals, 'revenue') else 'n/a'}"
    else:
        base_rev = _latest(annuals, "revenue")
        base_op = _latest(annuals, "operating_income")
        if not base_rev or not base_op:
            raise SystemExit("pack missing base-year revenue/operating_income")
        base_year, rev0, op0 = base_rev[0], base_rev[1], base_op[1]
        da0 = (_latest(annuals, "dda") or (None, 0.0))[1]
        capex0 = abs((_latest(annuals, "capex") or (None, 0.0))[1])
        cash = (_latest(annuals, "cash") or (None, 0.0))[1]
        debt = (_latest(annuals, "total_debt") or (None, 0.0))[1]
        tax_rows, pretax_rows = _latest(annuals, "income_tax"), _latest(annuals, "pretax_income")
        shares = (_latest(annuals, "diluted_shares") or (None, None))[1] or info.get("sharesOutstanding")
        assumptions["base"] = f"annual fiscal year ending {base_year}"
    if shares is None:
        raise SystemExit("no diluted shares in pack and no info.sharesOutstanding")
    if args.shares is not None:
        shares = args.shares
        assumptions["shares"] = f"explicit --shares override {shares:,.0f} (TTM/annual diluted-shares conflict documented by agent)"
    elif args.base == "ttm" and not (pack.get("ttm") or {}).get("diluted_shares"):
        assumptions["shares"] = f"TTM diluted shares unavailable; info.sharesOutstanding fallback {shares:,.0f}"
    elif args.base == "ttm":
        assumptions["shares"] = f"TTM latest-quarter diluted shares {shares:,.0f}"
    else:
        assumptions["shares"] = f"annual diluted shares / info fallback {shares:,.0f}"
    mcap = float(price["market_cap"])

    # --- tax rate per policy ---
    if args.tax is not None:
        tax = args.tax
        assumptions["tax"] = f"override {args.tax:.1%}"
    elif tax_rows and pretax_rows and tax_rows[1] is not None and pretax_rows[1] and pretax_rows[1] > 0:
        tax = min(max(tax_rows[1] / pretax_rows[1], *POLICY_TAX_RANGE[:1]), POLICY_TAX_RANGE[1])
        assumptions["tax"] = f"base-year effective rate ({tax_rows[1]:.0f}/{pretax_rows[1]:.0f}) clamped to {POLICY_TAX_RANGE[0]:.0%}-{POLICY_TAX_RANGE[1]:.0%}"
    else:
        tax = 0.21
        assumptions["tax"] = "21% statutory fallback (no pretax income in pack)"

    # --- WACC inputs per policy ---
    rf = args.rf if args.rf is not None else (meta.get("risk_free") or {}).get("rf_10y_pct")
    if rf is None:
        rf, assumptions["rf"] = 4.5, "4.50% fallback (meta fetch failed)"
    else:
        assumptions["rf"] = f"{rf:.2f}% = 10Y UST ({meta.get('risk_free', {}).get('source', '_meta.json')})"
    erp = args.erp if args.erp is not None else meta.get("erp_policy_pct", 5.0)
    assumptions["erp"] = f"{erp:.1f}% (batch policy)"
    beta = args.beta if args.beta is not None else (info.get("beta") or 1.0)
    beta_clamped = min(max(beta, *POLICY_BETA_RANGE[:1]), POLICY_BETA_RANGE[1])
    assumptions["beta"] = f"{beta_clamped:.2f} from yfinance info" + (" (clamped)" if beta != beta_clamped else "")
    re_ = rf / 100 + beta_clamped * erp / 100

    net_cash = cash - debt
    levered = net_cash < 0 and not args.no_leverage
    if args.no_leverage:
        assumptions["leverage"] = "Re-only discounting forced (--no-leverage)"
    if not levered:
        wacc, d_ = re_, 0.0
        assumptions["wacc"] = f"WACC=Re={re_:.2%} (net cash {net_cash/1e9:.1f}B or forced)"
    else:
        interest = ttm.get("interest_expense") if args.base == "ttm" else (_latest(annuals, "interest_expense") or (None, 0.0))[1]
        rd = args.rd_pct / 100 if args.rd_pct is not None else max(float(interest or 0.0) / debt if debt else 0.0, 0.02)
        d_ = debt
        wacc = mcap / (mcap + d_) * re_ + d_ / (mcap + d_) * rd * (1 - tax)
        assumptions["wacc"] = f"CAPM Re={re_:.2%}, Rd={rd:.2%} (interest/debt floor 2%), E/V={mcap/(mcap+d_):.1%}, tax={tax:.0%}"
    g = min(args.g, POLICY_MAX_G) / 100
    assumptions["g"] = f"{g:.2%} terminal growth"

    # --- 5-year explicit projection ---
    growth = _pct_list(args.growth, 5, "growth") if args.growth else None
    margin = _pct_list(args.margin, 5, "margin") if args.margin else None
    base_margin = op0 / rev0
    margin = margin or [base_margin * 100] * 5
    base_da = da0 / rev0 * 100
    base_capex = capex0 / rev0 * 100
    da_pct = _pct_list(args.da_pct, 5, "da-pct") if args.da_pct else [base_da] * 5
    capex_pct = _pct_list(args.capex_pct, 5, "capex-pct") if args.capex_pct else [base_capex] * 5
    if growth is None:
        growth = [max((rev0 / _latest(annuals, "revenue")[1]) ** 0 - 1, 0) * 100] * 5  # not used; replaced below
        growth = [0.0] * 5
        assumptions["growth"] = "0% (NO --growth given; flat revenue — supply explicit growth!)"
    else:
        assumptions["growth"] = f"explicit: {growth}%"
    assumptions["margin"] = f"explicit {margin}% (base EBIT margin {base_margin:.1%})" if args.margin else f"flat base EBIT margin {base_margin:.1%}"
    assumptions["da"] = f"{da_pct}% of revenue (base {base_da:.1f}%)" if args.da_pct else f"flat base D&A {base_da:.1f}% of revenue"
    assumptions["capex"] = f"{capex_pct}% of revenue (base {base_capex:.1f}%)" if args.capex_pct else f"flat base capex {base_capex:.1f}% of revenue"

    def run(growth_: list[float], wacc_: float, g_: float) -> dict:
        rev, fcf = rev0, []
        for i in range(5):
            rev *= 1 + growth_[i] / 100
            ebit = rev * margin[i] / 100
            fcf.append(ebit * (1 - tax) + rev * da_pct[i] / 100 - rev * capex_pct[i] / 100)
        pv = sum(fcf[t] / (1 + wacc_) ** (t + 1) for t in range(5))
        tv = fcf[-1] * (1 + g_) / (wacc_ - g_)
        ev = pv + tv / (1 + wacc_) ** 5
        equity = ev + net_cash
        return {"fcf": fcf, "revenue": [rev0] + list(_accumulate(rev0, growth_))[:5], "pv": pv, "tv": tv, "ev": ev, "equity": equity, "per_share": equity / shares}

    def _accumulate(start: float, growth_: list[float]):
        out, v = [], start
        for rate in growth_:
            v *= 1 + rate / 100
            out.append(v)
        return out

    base = run(growth, wacc, g)
    grid = {f"WACC {w:.1%}": {} for w in (wacc - 0.01, wacc, wacc + 0.01)}
    for w_off in (-0.01, 0.0, 0.01):
        for g_off in (-0.005, 0.0, 0.005):
            cell = run(growth, wacc + w_off, max(g + g_off, 0.0))
            grid[f"WACC {(wacc + w_off):.1%}"][f"g {(g + g_off):.1%}"] = round(cell["per_share"], 2)

    result = {
        "label": args.label or "base",
        "ticker": pack["ticker"],
        "base_year": base_year,
        "currency_note": pack.get("currency_note", ""),
        "inputs": {
            "revenue_base": rev0, "ebit_margin_base": round(base_margin, 4), "da_base": da0, "capex_base": capex0,
            "cash": cash, "debt": debt, "net_cash": net_cash, "market_cap": mcap, "shares": shares,
            "price": price.get("price"), "beta_used": beta_clamped, "re_pct": round(re_, 4), "wacc_pct": round(wacc * 100, 3),
        },
        "projection": {
            "growth_pct": growth, "margin_pct": margin, "da_pct": [round(x, 3) for x in da_pct], "capex_pct": [round(x, 3) for x in capex_pct],
            "revenue_path": [round(x, 0) for x in base["revenue"]],
            "fcf_path": [round(x, 0) for x in base["fcf"]],
            "pv_of_fcf": round(base["pv"], 0), "terminal_value": round(base["tv"], 0),
            "tv_pct_of_ev": round(base["tv"] / (base["pv"] + base["tv"]), 3) if (base["pv"] + base["tv"]) else None,
        },
        "result": {"enterprise_value": round(base["ev"], 0), "equity_value": round(base["equity"], 0),
                   "intrinsic_per_share": round(base["per_share"], 2),
                   "price_now": price.get("price"),
                   "upside_pct": round((base["per_share"] / price["price"] - 1) * 100, 1) if price.get("price") else None},
        "sensitivity_per_share": grid,
        "assumptions": assumptions,
    }
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
