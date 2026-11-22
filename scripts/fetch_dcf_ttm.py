"""Add a TTM (trailing-twelve-month) base section to every Tier-1 DCF pack.

Quarterly statements from yfinance (proxy-routed, cached under
``data/company_quality/yahoo_cache_q/``) are summed over the last four
quarters for income/cash-flow lines and taken at the latest quarter for
balance-sheet lines, then written into each pack's ``"ttm"`` key. Also
computes TTM-revenue YoY when eight quarters are available, so a stale
annual base (e.g. NVDA fiscal year ending Jan-31) can be replaced by the
most current trailing base.

Usage:  uv run python scripts/fetch_dcf_ttm.py [--tickers AAPL,NVDA]
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fdc.data_files import PROJECT_ROOT
from fdc.quotes import apply_proxy

REPORTS_DIR = PROJECT_ROOT / "reports" / "tier1-dcf"
DATA_DIR = REPORTS_DIR / "_data"
Q_CACHE = PROJECT_ROOT / "data" / "company_quality" / "yahoo_cache_q"

# metric -> (statement attr, yfinance row label); quarterly statement attrs per
# yfinance 1.7.0 (quarterly_income_stmt / quarterly_cash_flow / quarterly_balance_sheet).
SUM_ROWS = {
    "revenue": ("income", "Total Revenue"),
    "operating_income": ("income", "Operating Income"),
    "net_income": ("income", "Net Income"),
    "interest_expense": ("income", "Interest Expense"),
    "pretax_income": ("income", "Pretax Income"),
    "income_tax": ("income", "Tax Provision"),
    "dda": ("cashflow", "Depreciation And Amortization"),
    "capex": ("cashflow", "Capital Expenditure"),
}
# point-in-time quantities: take the latest quarter, never sum over the year.
POINT_ROWS = {
    "cash": ("balance", "Cash And Cash Equivalents"),
    "total_debt": ("balance", "Total Debt"),
    "total_assets": ("balance", "Total Assets"),
    "diluted_shares": ("income", "Diluted Average Shares"),
}
Q_ATTRS = {"income": "quarterly_income_stmt", "cashflow": "quarterly_cash_flow", "balance": "quarterly_balance_sheet"}


def t1_tickers() -> list[str]:
    rows = json.loads((PROJECT_ROOT / "data" / "generated" / "funnel.json").read_text())["rows"]
    return [r["ticker"] for r in rows if r.get("tier") == 1]


def fetch_quarterly(ticker: str, retries: int = 3) -> dict[str, dict[str, dict[str, float]]]:
    """{attr: {quarter_end_iso: {row_label: value}}} with cache + proxy + retries."""

    import yfinance as yf

    cache = Q_CACHE / f"{ticker}.json"
    if cache.exists():
        record = json.loads(cache.read_text())
        if datetime.fromisoformat(record["fetched_at"]) > datetime.now(timezone.utc) - timedelta(days=30):
            return record["quarterly"]

    statements: dict[str, dict[str, dict[str, float]]] = {}
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            apply_proxy()
            handle = yf.Ticker(ticker)
            for attr, qattr in Q_ATTRS.items():
                frame = getattr(handle, qattr)
                if frame is None or frame.empty:
                    statements[attr] = {}
                    continue
                statements[attr] = {
                    col.date().isoformat() if hasattr(col, "date") else str(col): {
                        str(index): (None if val is None else (float(val) if val == val else None))
                        for index, val in series.items()
                    }
                    for col, series in frame.items()
                }
            Q_CACHE.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "ticker": ticker, "quarterly": statements}))
            return statements
        except Exception as error:  # noqa: BLE001 - rate limit / network
            last_error = error
            if attempt < retries:
                time.sleep(min(2 ** attempt, 20))
    print(f"WARNING {ticker}: quarterly fetch failed ({type(last_error).__name__}); no ttm section")
    return {}


def _sum_last4(stmts: dict, end_keys: list[str], label: str, attr: str) -> float | None:
    """Sum the latest four non-null quarterly values for a metric.

    Individual yfinance rows can be blank for one quarter even though adjacent
    quarters are available (e.g. an API refresh boundary). Select four actual
    quarter observations rather than letting one null invalidate TTM.
    """

    values = [stmts.get(attr, {}).get(end, {}).get(label) for end in end_keys]
    values = [v for v in values if v is not None]
    return sum(values[:4]) if len(values) >= 4 else None


def _latest_value(stmts: dict, end_keys: list[str], label: str, attr: str) -> float | None:
    for end in end_keys:
        value = stmts.get(attr, {}).get(end, {}).get(label)
        if value is not None:
            return value
    return None


def build_ttm(ticker: str, stmts: dict) -> dict:
    if not stmts:
        return {}
    # quarter-ends per statement are aligned; union them and keep the common tail.
    all_ends = sorted(set(end for attr in stmts for end in stmts[attr]), reverse=True)
    common = [e for e in all_ends if all(e in stmts.get(attr, {}) for attr in stmts if stmts[attr])]
    if not common:
        return {}
    last4 = common[:4]
    last8 = common[:8]
    ttm: dict = {
        "as_of_quarter": last4[0],
        "quarters": last4,
        "note": "sum of last 4 yfinance quarterly periods; balance-sheet lines = latest quarter point-in-time",
    }
    for metric, (attr, label) in {**SUM_ROWS, **POINT_ROWS}.items():
        if metric in POINT_ROWS:
            ttm[metric] = _latest_value(stmts, last4, label, attr)
        else:
            ttm[metric] = _sum_last4(stmts, last4, label, attr)
    if len(last8) >= 8:
        rev_ttm_now = _sum_last4(stmts, last4, "Total Revenue", "income_stmt")
        rev_ttm_prior = _sum_last4(stmts, last8[4:8], "Total Revenue", "income_stmt")
        if rev_ttm_now and rev_ttm_prior:
            ttm["ttm_revenue_yoy_pct"] = round((rev_ttm_now / rev_ttm_prior - 1) * 100, 1)
    else:
        ttm["ttm_revenue_yoy_pct"] = None
    return ttm


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default="")
    args = parser.parse_args(argv)
    tickers = [t.upper() for t in args.tickers.split(",") if t.strip()] or t1_tickers()

    updated = 0
    for ticker in tickers:
        pack_path = DATA_DIR / f"{ticker}.json"
        pack = json.loads(pack_path.read_text())
        pack["ttm"] = build_ttm(ticker, fetch_quarterly(ticker))
        pack_path.write_text(json.dumps(pack, indent=1))
        t = pack["ttm"]
        if t:
            rev = t.get("revenue")
            yoy = t.get("ttm_revenue_yoy_pct")
            print(f"{ticker}: ttm as of {t['as_of_quarter']}, rev {rev/1e9 if rev else 0:.1f}B ({yoy}% yoy)")
            updated += 1
        else:
            print(f"{ticker}: NO ttm (fetch failed)")
    print(f"\nupdated {updated}/{len(tickers)} packs with ttm section")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
