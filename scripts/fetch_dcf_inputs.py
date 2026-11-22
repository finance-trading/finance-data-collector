"""One-off DCF input packs for the Tier-1 roster (goal: tier1 DCF reports).

Writes per-ticker JSON packs under ``reports/tier1-dcf/_data/`` and a shared
``_meta.json`` (risk-free snapshot, policy constants, row-label map).

Sources, so each report can cite them:
- annuals/instants: yfinance annual statements (cached in
  data/company_quality/yahoo_cache/, proxy-routed), 5 latest fiscal years.
- price snapshot: data/generated/funnel.json (Yahoo quotes, as-of its date).
- beta / shares / sector: yfinance ``.info`` (cached in _data/info_cache/).

Run:  uv run python scripts/fetch_dcf_inputs.py [--tickers AAPL,MSFT]
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fdc.data_files import PROJECT_ROOT
from fdc.quotes import apply_proxy
from fdc.quality_facts_external import fetch_statements

REPORTS_DIR = PROJECT_ROOT / "reports" / "tier1-dcf"
DATA_DIR = REPORTS_DIR / "_data"
INFO_CACHE = DATA_DIR / "info_cache"
FUNNEL_PATH = PROJECT_ROOT / "data" / "generated" / "funnel.json"

# clean-metric -> (statement attr, yfinance row label)
DERIVED = {
    "revenue": ("income_stmt", "Total Revenue"),
    "operating_income": ("income_stmt", "Operating Income"),
    "net_income": ("income_stmt", "Net Income"),
    "interest_expense": ("income_stmt", "Interest Expense"),
    "pretax_income": ("income_stmt", "Pretax Income"),
    "income_tax": ("income_stmt", "Tax Provision"),
    "cfo": ("cashflow", "Operating Cash Flow"),
    "capex": ("cashflow", "Capital Expenditure"),
    "dda": ("cashflow", "Depreciation And Amortization"),
    "diluted_shares": ("income_stmt", "Diluted Average Shares"),
    "total_assets": ("balance_sheet", "Total Assets"),
    "cash": ("balance_sheet", "Cash And Cash Equivalents"),
    "total_debt": ("balance_sheet", "Total Debt"),
}
INFO_FIELDS = ("beta", "sharesOutstanding", "sector", "industry", "currency", "longName")


def t1_tickers(path: Path = FUNNEL_PATH) -> list[str]:
    rows = json.loads(path.read_text())["rows"]
    return [r["ticker"] for r in rows if r.get("tier") == 1]


def price_snapshot(ticker: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    row = next((r for r in rows if r["ticker"] == ticker), {})
    return {k: row.get(k) for k in ("price", "market_cap", "pe", "forward_pe", "high_52w", "low_52w", "position_52w_pct")}


def get_info(ticker: str, retries: int = 2) -> dict[str, Any]:
    """yfinance .info fields, cached; tolerate total failure (fields -> None)."""

    import yfinance as yf

    cache = INFO_CACHE / f"{ticker}.json"
    if cache.exists():
        record = json.loads(cache.read_text())
        if datetime.fromisoformat(record["fetched_at"]) > datetime.now(timezone.utc) - _td(days=30):
            return record["info"]
    for attempt in range(retries + 1):
        try:
            apply_proxy()
            info = yf.Ticker(ticker).info or {}
            picked = {k: info.get(k) for k in INFO_FIELDS}
            INFO_CACHE.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "info": picked}))
            return picked
        except Exception:
            if attempt < retries:
                time.sleep(2 ** attempt)
    return {k: None for k in INFO_FIELDS}


def _td(days: int):
    from datetime import timedelta

    return timedelta(days=days)


def derived_series(stmts: dict[str, dict[str, dict[str, float]]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for metric, (attr, label) in DERIVED.items():
        rows = []
        for end_iso in sorted(stmts.get(attr, {}), reverse=True)[:6]:
            value = stmts[attr][end_iso].get(label)
            rows.append({"end": end_iso, "value": value, "row_label": label, "statement": attr})
        out[metric] = rows
    return out


def risk_free_snapshot() -> dict[str, Any]:
    """10Y UST yield via ^TNX (yfinance quotes it in percent, e.g. 42.3 => 4.23%)."""

    try:
        import yfinance as yf

        apply_proxy()
        price = float(yf.Ticker("^TNX").fast_info["last_price"])
        # ^TNX quotes the 10Y UST yield in percent points (4.91 == 4.91%).
        return {"rf_10y_pct": round(price, 4), "rf_10y_decimal": round(price / 100, 6), "source": "yfinance ^TNX last price", "fetched_at": datetime.now(timezone.utc).isoformat()}
    except Exception as error:  # noqa: BLE001
        return {"rf_10y_pct": None, "rf_10y_decimal": None, "source": f"fetch failed ({type(error).__name__}); use 4.50% and note it", "fetched_at": datetime.now(timezone.utc).isoformat()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default="")
    args = parser.parse_args(argv)

    rows = json.loads(FUNNEL_PATH.read_text())["rows"]
    tickers = [t.upper() for t in args.tickers.split(",") if t.strip()] or t1_tickers()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    written, failed = 0, []
    for ticker in tickers:
        stmts = fetch_statements(ticker, PROJECT_ROOT / "data" / "company_quality" / "yahoo_cache")
        pack = {
            "ticker": ticker,
            "cik": next((r.get("cik") for r in rows if r["ticker"] == ticker), None),
            "price_snapshot": price_snapshot(ticker, rows),
            "info": get_info(ticker),
            "annuals": derived_series(stmts),
        }
        out = DATA_DIR / f"{ticker}.json"
        out.write_text(json.dumps(pack, indent=1))
        written += 1
        missing = [m for m, s in pack["annuals"].items() if not s or s[0]["value"] is None]
        print(f"{ticker}: ok (missing-current: {missing or 'none'})")
        if not stmts:
            failed.append(ticker)

    meta = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "risk_free": risk_free_snapshot(),
        "erp_policy_pct": 5.0,
        "terminal_growth_policy_pct": 2.5,
        "tax_rate_policy": "actual effective tax rate (income_tax / pretax_income) of latest FY, clamped to [12%, 30%]",
        "wacc_policy": "net-cash => WACC = Re only; else Rd = latest FY interest_expense / total_debt (floor 2%), Tc = tax rate above",
        "derived_labels": DERIVED,
        "yahoo_note": "yfinance statements are in reporting currency unless converted; fiscal years may not end 12-31",
    }
    (DATA_DIR / "_meta.json").write_text(json.dumps(meta, indent=1))
    print(f"\nwrote {written}/{len(tickers)} packs; yahoo-failed: {failed or 'none'}; meta: {DATA_DIR / '_meta.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
