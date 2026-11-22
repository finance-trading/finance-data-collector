"""External annual facts for the quality scorer: yfinance first, SEC gap-fill.

``fdc.quality_score.calculate_quality_scores`` consumes an annual-facts table
keyed by CIK. The checked-in source is ``data/company_quality/
edgartools_annual_facts_*.csv.gz`` (SEC XBRL parsed by edgartools). This module
builds the *same* table but pulls the "basic" financial lines from Yahoo Finance
first, and only falls back to the SEC/edgartools rows for the
``(cik, metric, period_end)`` combinations yfinance does not cover.

The output is drop-in: feed it to ``calculate_quality_scores`` with
``rating_cutoff`` set to the fetch date. External facts are "known" at fetch
time, so their ``filing_date`` is the fetch date, and the scorer's point-in-time
filter (``end <= cutoff & filing <= cutoff``) only keeps them when
``cutoff >= fetch_date``.

Finviz is intentionally not a layer here: yfinance already returns every line
this scorer needs (revenue, op income, net income, CFO, capex, interest, D&A,
assets, cash, debt), so Finviz would add nothing for these lines. Finviz stays
the source for the valuation quick-metrics, which ``fdc.quotes`` already handles.

Usage:
    uv run python -m fdc.quality_facts_external            # build + write CSV
    uv run python -m fdc.quality_facts_external --score    # also emit scores
    uv run python -m fdc.quality_facts_external --tickers AAPL,MSFT --dry-run
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import yfinance as yf

from fdc.catalog import load_catalog
from fdc.data_files import DATA_ROOT
from fdc.quotes import apply_proxy
from fdc.quality_score import calculate_quality_scores, match_catalog_companies, norm_cik

logger = logging.getLogger(__name__)

QUALITY_DIR = DATA_ROOT / "company_quality"
DEFAULT_FACTS_GZ = QUALITY_DIR / "edgartools_annual_facts_2026-10-05.csv.gz"
DEFAULT_UNIVERSE_GZ = QUALITY_DIR / "peer_universe_2026-09.csv.gz"
DEFAULT_RATING_CUTOFF = date(2026, 9, 30)

#: The full column set of the edgartools facts CSV; we emit exactly these so the
#: external table is schema-identical and diff-able against the SEC source.
FACT_COLUMNS = [
    "cik", "concept", "label", "value", "numeric_value", "unit", "period_type",
    "period_start", "period_end", "fiscal_year", "fiscal_period", "accession",
    "filing_date", "form_type", "statement_type", "taxonomy", "scale",
    "data_quality", "is_audited", "confidence_score", "period_days",
    "period_shape", "metric",
]

#: metric -> (statement attr, yfinance row label, concept string).
#: Duration lines: ``period_start``/``period_end`` are the fiscal-year bounds;
#: the scorer only needs the span to land in [330, 400] days, so we emit a
#: synthetic 365-day span ending at the fiscal-year end.
_DURATION = {
    "revenue": ("income_stmt", "Total Revenue", "us-gaap:Revenues"),
    "operating_income": ("income_stmt", "Operating Income", "us-gaap:OperatingIncomeLoss"),
    "net_income": ("income_stmt", "Net Income", "us-gaap:NetIncomeLoss"),
    "cfo": ("cashflow", "Operating Cash Flow", "us-gaap:NetCashProvidedByUsedInOperatingActivities"),
    "capex": ("cashflow", "Capital Expenditure", "us-gaap:PaymentsForPropertyPlantAndEquipment"),
    "interest_expense": ("income_stmt", "Interest Expense", "us-gaap:InterestExpense"),
    "depreciation_amortization": ("cashflow", "Depreciation And Amortization", "us-gaap:DepreciationAmortizationAndDepletion"),
}
#: metric -> (statement attr, yfinance row label, concept tag).
#: Instant lines: the concept tag must match a preferred tag in the scorer's
#: ``instant_series`` / ``debt_series`` priority lists (all rank 0 here).
_INSTANT = {
    "assets": ("balance_sheet", "Total Assets", "Assets"),
    "cash": ("balance_sheet", "Cash And Cash Equivalents", "CashAndCashEquivalentsAtCarryingValue"),
    "debt": ("balance_sheet", "Total Debt", "DebtLongtermAndShorttermCombinedAmount"),
}
_STATEMENT_TYPES = {"income_stmt": "income", "cashflow": "cashflow", "balance_sheet": "balance"}


def load_universe(path: Path = DEFAULT_UNIVERSE_GZ) -> pd.DataFrame:
    """The peer universe: one row per ticker with cik + canonical_symbol."""

    frame = pd.read_csv(path)
    required = {"cik", "canonical_symbol"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"universe missing columns: {sorted(missing)}")
    frame["cik"] = norm_cik(frame["cik"])
    frame["canonical_symbol"] = frame["canonical_symbol"].astype(str).str.strip().str.upper()
    return frame


def load_sec_facts(path: Path = DEFAULT_FACTS_GZ) -> pd.DataFrame:
    """The checked-in SEC/edgartools annual facts used only as a gap-filler."""

    frame = pd.read_csv(path)
    required = {"cik", "metric", "period_type", "period_end", "numeric_value"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"sec facts missing columns: {sorted(missing)}")
    frame["cik"] = norm_cik(frame["cik"])
    return frame


def _cache_path(ticker: str, cache_dir: Path) -> Path:
    return cache_dir / f"{ticker.replace('^', '_').replace('|', '_')}.json"


def fetch_statements(
    ticker: str,
    cache_dir: Path,
    max_age_days: int = 30,
    retries: int = 3,
) -> dict[str, dict[str, dict[str, float]]]:
    """Return ``{statement_attr: {fiscal_end_iso: {row_label: value}}}``.

    Fetches the three annual statements from yfinance (routed through the
    configured proxy) and caches them as JSON so a re-run does not re-hit Yahoo.
    A cache entry younger than ``max_age_days`` is reused. On a total fetch
    failure (rate limit, unknown ticker) an empty dict is returned so callers
    fall back to the SEC rows for that issuer.
    """

    cache = _cache_path(ticker, cache_dir)
    if cache.exists():
        record = json.loads(cache.read_text())
        fetched = datetime.fromisoformat(record["fetched_at"])
        if (datetime.now(timezone.utc) - fetched) < timedelta(days=max_age_days):
            return record["statements"]

    statements: dict[str, dict[str, dict[str, float]]] = {}
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            apply_proxy()
            handle = yf.Ticker(ticker)
            for attr in ("income_stmt", "cashflow", "balance_sheet"):
                frame = getattr(handle, attr)
                if frame is None or frame.empty:
                    statements[attr] = {}
                    continue
                # frame: index = row label, columns = fiscal-year-end dates.
                # Emit {end_iso: {row_label: value}} so consumers can look up a
                # label per fiscal year.
                statements[attr] = {
                    (col.date().isoformat() if hasattr(col, "date") else str(col)): {
                        str(index): (None if pd.isna(val) else float(val))
                        for index, val in series.items()
                    }
                    for col, series in frame.items()
                }
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "ticker": ticker,
                "statements": statements,
            }))
            return statements
        except Exception as error:  # noqa: BLE001 - rate limit / network: retry then give up
            last_error = error
            if attempt < retries:
                time.sleep(min(2 ** attempt, 20))
    logger.warning("yahoo fetch failed for %s (%s); using SEC gap-fill", ticker, type(last_error).__name__)
    return {}


def statements_to_facts(
    ticker: str,
    cik: str,
    stmts: dict[str, dict[str, dict[str, float]]],
    fetch_date: date,
) -> list[dict[str, Any]]:
    """Expand cached yfinance statements into annual-facts rows.

    Each emitted row matches ``FACT_COLUMNS`` so it concatenates cleanly with the
    SEC table. Duration lines get a synthetic 365-day span ending at the
    fiscal-year end; instant lines get ``period_start == period_end``.
    """

    rows: list[dict[str, Any]] = []

    def base_row(metric: str, concept: str, period_type: str, end: date, value: float, attr: str) -> dict[str, Any]:
        start = end - timedelta(days=365) if period_type == "duration" else end
        return {
            "cik": cik,
            "concept": concept,
            "label": f"yahoo:{metric}",
            "value": repr(value),
            "numeric_value": value,
            "unit": "USD",
            "period_type": period_type,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "fiscal_year": str(end.year),
            "fiscal_period": "FY",
            "accession": f"external-yfinance:{cik}:{metric}:{end.isoformat()}",
            "filing_date": fetch_date.isoformat(),
            "form_type": "EXT",
            "statement_type": _STATEMENT_TYPES[attr],
            "taxonomy": "yfinance",
            "scale": "",
            "data_quality": "medium",
            "is_audited": "False",
            "confidence_score": "0.8",
            "period_days": "365" if period_type == "duration" else "0",
            "period_shape": "annual",
            "metric": metric,
        }

    for metric, (attr, label, concept) in _DURATION.items():
        for end_iso, values in stmts.get(attr, {}).items():
            value = values.get(label)
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            rows.append(base_row(metric, concept, "duration", date.fromisoformat(end_iso), value, attr))
    for metric, (attr, label, tag) in _INSTANT.items():
        for end_iso, values in stmts.get(attr, {}).items():
            value = values.get(label)
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            rows.append(base_row(metric, f"us-gaap:{tag}", "instant", date.fromisoformat(end_iso), value, attr))
    return rows


def build_external_facts(
    universe: pd.DataFrame,
    sec_facts: pd.DataFrame,
    cache_dir: Path = QUALITY_DIR / "yahoo_cache",
    fetch_date: date | None = None,
    max_age_days: int = 30,
    tickers: Iterable[str] | None = None,
    concurrency: int = 5,
) -> pd.DataFrame:
    """Build the merged external+SEC annual-facts table.

    For every universe ticker, pull the yfinance statements (cached); emit
    external rows for each covered ``(cik, metric, period_end)``; then keep only
    the SEC rows for the combinations yfinance did *not* cover, so the two
    sources never double-count a fiscal year.
    """

    fetch_date = fetch_date or date.today()
    universe = universe.copy()
    if tickers is not None:
        wanted = {t.upper() for t in tickers}
        universe = universe[universe["canonical_symbol"].isin(wanted)]
    if universe.empty:
        raise ValueError("no universe tickers selected")

    cache_dir.mkdir(parents=True, exist_ok=True)
    stmts_by_ticker: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(fetch_statements, row.canonical_symbol, cache_dir, max_age_days): row.canonical_symbol
                   for row in universe.itertuples(index=False)}
        for future in as_completed(futures):
            stmts_by_ticker[futures[future]] = future.result()

    external: list[dict[str, Any]] = []
    covered: set[tuple[str, str, str]] = set()
    for row in universe.itertuples(index=False):
        # cik is already zero-padded by load_universe; itertuples yields a scalar.
        cik = str(row.cik).zfill(10)
        rows = statements_to_facts(row.canonical_symbol, cik, stmts_by_ticker.get(row.canonical_symbol, {}), fetch_date)
        external.extend(rows)
        for item in rows:
            covered.add((cik, item["metric"], item["period_end"]))

    sec = sec_facts.copy()
    sec["cik"] = norm_cik(sec["cik"])
    # Restrict the gap-filler to the selected universe so unselected issuers
    # (and their rows) never leak into the merged table.
    sec = sec[sec["cik"].isin(set(universe["cik"]))]
    sec["period_end"] = pd.to_datetime(sec["period_end"]).dt.date.astype(str)
    sec["metric"] = sec["metric"].astype(str).str.strip()
    sec["key"] = list(zip(sec["cik"], sec["metric"], sec["period_end"]))
    gaps = sec[~sec["key"].isin(covered)].drop(columns=["key"])

    merged = pd.concat([pd.DataFrame(external), gaps], ignore_index=True)
    merged = merged[FACT_COLUMNS]
    if merged.empty:
        raise ValueError("no external or sec facts produced")
    return merged


def build_scores(facts: pd.DataFrame, universe: pd.DataFrame, rating_cutoff: date, catalog: Any | None = None) -> pd.DataFrame:
    """Run the scorer on merged facts; optionally restrict to catalog tickers."""

    scores = calculate_quality_scores(facts, universe, rating_cutoff)
    if catalog is not None:
        scores = match_catalog_companies(scores, catalog)
    return scores


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, default=DEFAULT_FACTS_GZ, help="SEC/edgartools gap-fill CSV (gz)")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE_GZ, help="peer universe CSV (gz)")
    parser.add_argument("--tickers", default="", help="comma-separated tickers to restrict the build")
    parser.add_argument("--cutoff", type=lambda value: date.fromisoformat(value), default=DEFAULT_RATING_CUTOFF,
                        help="rating_cutoff; for external facts use the fetch date, not the seed cutoff")
    parser.add_argument("--out", type=Path, default=None, help="output facts CSV (gz); default derived from date")
    parser.add_argument("--score", action="store_true", help="also compute + write catalog-matched scores")
    parser.add_argument("--catalog", type=Path, default=None, help="catalog JSON for --score")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--max-age-days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="build in memory, print coverage, write nothing")
    args = parser.parse_args(argv)

    universe = load_universe(args.universe)
    sec = load_sec_facts(args.facts)
    tickers = [t for t in args.tickers.split(",") if t.strip()] or None
    fetch_date = date.today()
    facts = build_external_facts(
        universe, sec, tickers=tickers, fetch_date=fetch_date,
        concurrency=args.concurrency, max_age_days=args.max_age_days,
    )

    ext = facts[facts["accession"].str.startswith("external-")]
    logger.info(
        "facts: %d total (%d yahoo, %d sec-gap) across %d tickers",
        len(facts), len(ext), len(facts) - len(ext), facts["cik"].nunique(),
    )
    if args.dry_run:
        print(facts.groupby("metric").size().to_string())
        return 0

    out = args.out or QUALITY_DIR / f"external_annual_facts_{fetch_date.isoformat()}.csv.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    facts.to_csv(out, index=False, compression="gzip")
    logger.info("wrote %s", out)

    if args.score:
        # External facts are "known" at fetch time, so the point-in-time cutoff
        # must be at least the fetch date or the scorer's PIT filter drops them.
        cutoff = max(args.cutoff, fetch_date)
        scores = build_scores(facts, universe, cutoff, load_catalog(args.catalog))
        score_out = out.with_name(out.stem + ".scores.csv.gz")
        scores.to_csv(score_out, index=False, compression="gzip")
        logger.info("wrote %s (%d rows, cutoff %s)", score_out, len(scores), cutoff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
