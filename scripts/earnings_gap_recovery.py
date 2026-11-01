"""Download and reproduce the S&P 500 earnings-gap recovery study.

The recovery calculation uses only split-adjusted daily Close. Open remains
part of the event filter, and High is retained in the raw snapshot for
auditability but neither is used by the recovery rule. The script has two modes:

    uv run python scripts/earnings_gap_recovery.py download
    uv run python scripts/earnings_gap_recovery.py calculate

The legacy snapshot directory is ``data/research/earnings_gap_recovery``;
``download-current`` and ``calculate-current`` use its ``current`` child so
current-constituent and legacy winner samples cannot overwrite one another.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

DEFAULT_SCREEN_REPORT = Path(
    "docs/research/sp500-10y-total-return-screen-2026-09-25.md"
)
DEFAULT_DATA_DIR = Path("data/research/earnings_gap_recovery")
DEFAULT_CURRENT_DATA_DIR = DEFAULT_DATA_DIR / "current"
DEFAULT_SPY_HOLDINGS_URL = (
    "https://www.ssga.com/us/en/intermediary/library-content/products/"
    "fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
)
DEFAULT_CUTOFF = pd.Timestamp("2026-09-25")
DEFAULT_START = pd.Timestamp("2016-09-22")
TIMEZONE = "America/New_York"
MONTHS = tuple(range(1, 13))


@dataclass(frozen=True)
class WindowMetric:
    observed: bool
    recovered: bool | None
    max_close: float | None
    excess: float | None
    recovery_trading_days: int | None
    terminal_close: float | None
    terminal_excess: float | None
    max_drawdown_pct: float | None
    pre_recovery_min_close: float | None
    pre_recovery_min_excess_pct: float | None
    fixed_close: float | None = None
    fixed_excess: float | None = None
    fixed_date: pd.Timestamp | None = None
    max_close_trading_days: int | None = None
    max_close_date: pd.Timestamp | None = None


@dataclass(frozen=True)
class SummaryMetric:
    month: int
    recovered: int
    observed: int
    rate: float
    average_excess: float | None
    median_excess: float | None
    recovered_average_excess: float | None
    recovered_median_excess: float | None
    right_censored: int


def event_window_metrics(
    prices: pd.DataFrame,
    reaction_date: pd.Timestamp,
    target_close: float,
    max_months: int = 12,
    cutoff: pd.Timestamp = DEFAULT_CUTOFF,
) -> dict[int, WindowMetric]:
    """Calculate fixed-horizon and cumulative path metrics for one event.

    ``prices`` must have a timezone-naive DatetimeIndex and Open/Close columns.
    Each month uses the last available Close on or before the calendar-month
    deadline as ``fixed_close``/``fixed_excess``. The comparison is strict:
    equality with the target is not recovery. ``max_close`` remains the
    cumulative path maximum for recovery-speed and overshoot analysis.
    """

    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices must have a DatetimeIndex")
    cutoff = pd.Timestamp(cutoff).normalize()
    reaction_date = pd.Timestamp(reaction_date).normalize()
    result: dict[int, WindowMetric] = {}
    for month in range(1, max_months + 1):
        deadline = (reaction_date + pd.DateOffset(months=month)).normalize()
        if deadline > cutoff:
            result[month] = WindowMetric(
                False, None, None, None, None, None, None, None, None, None
            )
            continue
        window = prices[
            (prices.index >= reaction_date) & (prices.index.normalize() <= deadline)
        ][["Close"]].dropna(how="any")
        if window.empty:
            result[month] = WindowMetric(
                False, None, None, None, None, None, None, None, None, None
            )
            continue
        closes = window["Close"].astype(float)
        target = float(target_close)
        max_close = float(closes.max())
        max_close_position = int(closes.to_numpy().argmax())
        excess = max_close / target - 1.0
        recovery_positions = [position for position, close in enumerate(closes) if close > target]
        recovery_trading_days = recovery_positions[0] if recovery_positions else None
        recovered = recovery_trading_days is not None
        terminal_close = float(closes.iloc[-1])
        terminal_excess = terminal_close / target - 1.0
        running_max = closes.cummax()
        max_drawdown_pct = float(((closes / running_max - 1.0).min()) * 100.0)
        pre_recovery_closes = (
            closes.iloc[:recovery_trading_days]
            if recovery_trading_days is not None
            else closes
        )
        pre_recovery_min_close = (
            float(pre_recovery_closes.min()) if not pre_recovery_closes.empty else None
        )
        pre_recovery_min_excess_pct = (
            pre_recovery_min_close / target * 100.0 - 100.0
            if pre_recovery_min_close is not None
            else None
        )
        result[month] = WindowMetric(
            True,
            recovered,
            max_close,
            excess,
            recovery_trading_days,
            terminal_close,
            terminal_excess,
            max_drawdown_pct,
            pre_recovery_min_close,
            pre_recovery_min_excess_pct,
            terminal_close,
            terminal_excess,
            pd.Timestamp(closes.index[-1]),
            max_close_position,
            pd.Timestamp(closes.index[max_close_position]),
        )
    return result


def _excess_values(values: Iterable[object]) -> list[float]:
    """Accept WindowMetric values or ``(excess, observed)`` test tuples."""

    output: list[float] = []
    for value in values:
        if isinstance(value, WindowMetric):
            excess = (
                value.fixed_excess
                if value.fixed_excess is not None
                else value.excess
            ) if value.observed else None
        elif isinstance(value, tuple) and len(value) >= 2:
            excess, observed = value[0], value[1]
            if not observed:
                excess = None
        else:
            raise TypeError("metrics must contain WindowMetric or (excess, observed)")
        if excess is not None:
            output.append(float(excess))
    return output


def summarize_metrics(metrics: dict[int, Iterable[object]]) -> dict[int, SummaryMetric]:
    """Summarize observed/recovered events and excess percentages."""

    summary: dict[int, SummaryMetric] = {}
    for month, values in metrics.items():
        excesses = _excess_values(values)
        recovered_excesses = [value for value in excesses if value > 0]
        observed = len(excesses)
        recovered = len(recovered_excesses)
        summary[month] = SummaryMetric(
            month=month,
            recovered=recovered,
            observed=observed,
            rate=(recovered / observed * 100.0) if observed else float("nan"),
            average_excess=(sum(excesses) / observed * 100.0) if observed else None,
            median_excess=(float(pd.Series(excesses).median()) * 100.0) if observed else None,
            recovered_average_excess=(
                sum(recovered_excesses) / recovered * 100.0 if recovered else None
            ),
            recovered_median_excess=(
                float(pd.Series(recovered_excesses).median()) * 100.0
                if recovered
                else None
            ),
            right_censored=0,
        )
    return summary


def _tickers_from_report(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    block = text.split("## 完整入选名单（135 个）", 1)[1].split("## `UNAVAILABLE`", 1)[0]
    companies: list[dict[str, str]] = []
    for line in block.splitlines():
        match = re.match(r"^\|\s*\d+\s*\|\s*([A-Z.]+)\s*\|\s*([^|]+)", line)
        if match:
            companies.append({"ticker": match.group(1), "name": match.group(2).strip()})
    if len(companies) != 135:
        raise ValueError(f"expected 135 screen winners, found {len(companies)}")
    return companies


def parse_spy_holdings(path: Path) -> pd.DataFrame:
    """Parse a State Street SPY holdings workbook into current constituents.

    The workbook includes cash and occasional non-standard residual rows. Only
    rows with a ticker, excluding the documented residual identifiers, are
    treated as equity constituents.
    """

    frame = pd.read_excel(path, sheet_name="holdings", skiprows=4)
    required = {"Name", "Ticker"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"SPY holdings missing columns: {sorted(missing)}")
    frame = frame[frame["Ticker"].notna()].copy()
    frame["ticker"] = frame["Ticker"].astype(str).str.strip()
    frame = frame[~frame["ticker"].isin({"-", "2602335D"})]
    frame = frame[frame["ticker"].str.fullmatch(r"[A-Z][A-Z0-9.\-]*")]
    result = frame.rename(columns={"Name": "name"})[["ticker", "name"]]
    result["name"] = result["name"].astype(str).str.strip()
    result = result.drop_duplicates("ticker", keep="first").reset_index(drop=True)
    if result.empty:
        raise ValueError("SPY holdings contained no equity constituents")
    return result


def _download_earnings(ticker: str) -> pd.DataFrame:
    import yfinance as yf

    for attempt in range(3):
        try:
            return yf.Ticker(ticker.replace(".", "-")).get_earnings_dates(limit=100)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def download_snapshot(
    output_dir: Path = DEFAULT_DATA_DIR,
    screen_report: Path = DEFAULT_SCREEN_REPORT,
    start: pd.Timestamp = DEFAULT_START,
    cutoff: pd.Timestamp = DEFAULT_CUTOFF,
    companies: list[dict[str, str]] | None = None,
    universe_source: str | None = None,
) -> None:
    """Download and persist the raw earnings and OHLC snapshot."""

    import yfinance as yf

    output_dir.mkdir(parents=True, exist_ok=True)
    companies = companies or _tickers_from_report(screen_report)
    pd.DataFrame(companies).to_csv(output_dir / "universe.csv", index=False)

    earnings_rows: list[dict[str, object]] = []
    earnings_failures: list[dict[str, str]] = []
    for company in companies:
        try:
            frame = _download_earnings(company["ticker"])
        except Exception as exc:  # noqa: BLE001 - preserve per-ticker coverage
            earnings_failures.append(
                {
                    "ticker": company["ticker"],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            continue
        if frame is None or frame.empty:
            continue
        frame = frame.copy()
        frame.index = pd.to_datetime(frame.index, utc=True)
        lower = start.tz_localize("UTC")
        upper = (cutoff + pd.Timedelta(days=1)).tz_localize("UTC")
        frame = frame[(frame.index >= lower) & (frame.index < upper)]
        for timestamp, row in frame.iterrows():
            earnings_rows.append(
                {
                    "ticker": company["ticker"],
                    "earnings_datetime_utc": timestamp.isoformat(),
                    "eps_estimate": row.get("EPS Estimate"),
                    "reported_eps": row.get("Reported EPS"),
                    "surprise_pct": row.get("Surprise(%)"),
                    "source": "Yahoo Finance earnings calendar via yfinance",
                }
            )
    earnings = pd.DataFrame(
        earnings_rows,
        columns=[
            "ticker",
            "earnings_datetime_utc",
            "eps_estimate",
            "reported_eps",
            "surprise_pct",
            "source",
        ],
    ).drop_duplicates(
        subset=["ticker", "earnings_datetime_utc"]
    )
    earnings.to_csv(output_dir / "earnings_events.csv", index=False)

    tickers = [company["ticker"] for company in companies]
    prices: list[pd.DataFrame] = []
    for offset in range(0, len(tickers), 40):
        chunk = tickers[offset : offset + 40]
        symbols = [ticker.replace(".", "-") for ticker in chunk]
        frame = yf.download(
            symbols,
            start=start.strftime("%Y-%m-%d"),
            end=(cutoff + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            auto_adjust=False,
            actions=False,
            repair=False,
            group_by="ticker",
            threads=True,
            progress=False,
        )
        for ticker, symbol in zip(chunk, symbols):
            columns = frame[symbol] if len(symbols) > 1 else frame
            columns = columns.reset_index().rename(columns={"Date": "date"})
            columns.insert(0, "ticker", ticker)
            prices.append(columns)
    pd.concat(prices, ignore_index=True).to_csv(
        output_dir / "prices.csv.gz", index=False, compression="gzip"
    )

    metadata = {
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "screen_report": str(screen_report) if universe_source is None else None,
        "universe_source": universe_source or str(screen_report),
        "start": start.date().isoformat(),
        "cutoff": cutoff.date().isoformat(),
        "tickers": len(companies),
        "earnings_events_after_dedupe": int(len(earnings)),
        "earnings_download_failures": earnings_failures,
        "price_source": "Yahoo Finance chart via yfinance",
        "price_parameters": {
            "auto_adjust": False,
            "actions": False,
            "repair": False,
            "fields": ["Open", "High", "Low", "Close", "Adj Close", "Volume"],
        },
        "event_rule": "04:00-09:30 premarket; >=16:00 after-hours; other times UNKNOWN",
        "recovery_rule": (
            "fixed-horizon X_H = C_H / P_SEC - 1 using the last available Close "
            "on or before reaction date plus H calendar months; path recovery "
            "retained as strict max(Close) > P_SEC"
        ),
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )


def download_current_snapshot(
    output_dir: Path = DEFAULT_CURRENT_DATA_DIR,
    start: pd.Timestamp = DEFAULT_START,
    cutoff: pd.Timestamp = DEFAULT_CUTOFF,
    holdings_url: str = DEFAULT_SPY_HOLDINGS_URL,
) -> None:
    """Download a current S&P 500 proxy snapshot from State Street SPY holdings."""

    import httpx

    output_dir.mkdir(parents=True, exist_ok=True)
    holdings_path = output_dir / "spy_holdings.xlsx"
    response = httpx.get(holdings_url, follow_redirects=True, timeout=60.0)
    response.raise_for_status()
    holdings_path.write_bytes(response.content)
    companies = parse_spy_holdings(holdings_path).to_dict("records")
    download_snapshot(
        output_dir=output_dir,
        start=start,
        cutoff=cutoff,
        companies=companies,
        universe_source=(
            f"State Street SPY holdings workbook: {holdings_url}; "
            f"downloaded {pd.Timestamp.now(tz='UTC').isoformat()}"
        ),
    )
    download_benchmark(output_dir=output_dir, start=start, cutoff=cutoff)


def download_benchmark(
    output_dir: Path = DEFAULT_CURRENT_DATA_DIR,
    start: pd.Timestamp = DEFAULT_START,
    cutoff: pd.Timestamp = DEFAULT_CUTOFF,
    symbol: str = "SPY",
) -> None:
    """Download an adjusted-price benchmark used for relative event returns."""

    import yfinance as yf

    output_dir.mkdir(parents=True, exist_ok=True)
    frame = yf.download(
        symbol,
        start=start.strftime("%Y-%m-%d"),
        end=(cutoff + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        auto_adjust=False,
        actions=False,
        repair=False,
        group_by="column",
        threads=False,
        progress=False,
    )
    if frame is None or frame.empty:
        raise ValueError(f"benchmark download returned no rows for {symbol}")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.reset_index().rename(columns={"Date": "date"})
    frame.to_csv(output_dir / "benchmark_prices.csv", index=False)
    metadata_path = output_dir / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["benchmark"] = {
            "symbol": symbol,
            "source": "Yahoo Finance chart via yfinance",
            "price_file": "benchmark_prices.csv",
            "return_rule": "adjusted-open to adjusted-close total return",
        }
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )


def _load_prices(data_dir: Path) -> dict[str, pd.DataFrame]:
    raw = pd.read_csv(data_dir / "prices.csv.gz", parse_dates=["date"])
    prices: dict[str, pd.DataFrame] = {}
    for ticker, frame in raw.groupby("ticker", sort=False):
        prices[str(ticker)] = frame.set_index("date").sort_index()
    return prices


def total_return_from_adjusted_open(
    prices: pd.DataFrame,
    buy_date: pd.Timestamp,
    terminal_date: pd.Timestamp,
) -> float | None:
    """Return total return from a raw open using Yahoo's adjusted-close factor."""

    required = {"Open", "Close", "Adj Close"}
    if not required.issubset(prices.columns):
        return None
    buy_date = pd.Timestamp(buy_date).normalize()
    terminal_date = pd.Timestamp(terminal_date).normalize()
    if buy_date not in prices.index or terminal_date not in prices.index:
        return None
    buy = prices.loc[buy_date]
    terminal = prices.loc[terminal_date]
    values = [buy["Open"], buy["Close"], buy["Adj Close"], terminal["Adj Close"]]
    if any(pd.isna(value) or float(value) <= 0 for value in values):
        return None
    adjusted_open = float(buy["Open"]) * float(buy["Adj Close"]) / float(buy["Close"])
    return float(terminal["Adj Close"]) / adjusted_open - 1.0


def calculate_snapshot(
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path | None = None,
    cutoff: pd.Timestamp = DEFAULT_CUTOFF,
) -> pd.DataFrame:
    """Calculate and save event-level and monthly summary CSVs offline."""

    output_dir = output_dir or data_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    universe = pd.read_csv(data_dir / "universe.csv")
    earnings = pd.read_csv(data_dir / "earnings_events.csv")
    prices = _load_prices(data_dir)
    benchmark: pd.DataFrame | None = None
    benchmark_path = data_dir / "benchmark_prices.csv"
    if benchmark_path.exists():
        benchmark = pd.read_csv(benchmark_path, parse_dates=["date"])
        benchmark = benchmark.set_index("date").sort_index()
    cutoff = pd.Timestamp(cutoff).normalize()
    event_rows: list[dict[str, object]] = []
    for row in earnings.to_dict("records"):
        ticker = str(row["ticker"])
        price = prices.get(ticker)
        if price is None:
            continue
        timestamp = pd.Timestamp(row["earnings_datetime_utc"], tz="UTC").tz_convert(TIMEZONE)
        event_date = pd.Timestamp(timestamp.date())
        minutes = timestamp.hour * 60 + timestamp.minute
        if not (240 <= minutes < 570 or minutes >= 960):
            continue
        if minutes < 570:
            candidates = price.index[price.index.normalize() >= event_date]
        else:
            candidates = price.index[price.index.normalize() > event_date]
        if len(candidates) == 0:
            continue
        reaction_date = candidates[0]
        position = price.index.get_loc(reaction_date)
        if position == 0:
            continue
        previous_date = price.index[position - 1]
        previous_close = float(price.loc[previous_date, "Close"])
        reaction_open = float(price.loc[reaction_date, "Open"])
        gap = reaction_open / previous_close - 1.0
        if gap > -0.05:
            continue
        buy_date = price.index[position + 1] if position + 1 < len(price.index) else None
        buy_open = (
            float(price.loc[buy_date, "Open"])
            if buy_date is not None and not pd.isna(price.loc[buy_date, "Open"])
            else None
        )
        metrics = event_window_metrics(
            price,
            reaction_date,
            previous_close,
            max_months=12,
            cutoff=cutoff,
        )
        result = {
            "ticker": ticker,
            "earnings_datetime_utc": row["earnings_datetime_utc"],
            "reaction_date": reaction_date.date().isoformat(),
            "previous_date": previous_date.date().isoformat(),
            "previous_close": previous_close,
            "reaction_open": reaction_open,
            "gap_pct": gap * 100.0,
            "simulated_buy_date": (
                buy_date.date().isoformat() if buy_date is not None else None
            ),
            "simulated_buy_open": buy_open,
        }
        for month, metric in metrics.items():
            deadline = (reaction_date + pd.DateOffset(months=month)).normalize()
            window = price[
                (price.index >= reaction_date) & (price.index.normalize() <= deadline)
            ][["Close"]].dropna(how="any")
            terminal_date = window.index[-1] if not window.empty else None
            actual_return = (
                total_return_from_adjusted_open(price, buy_date, terminal_date)
                if buy_date is not None and terminal_date is not None
                else None
            )
            benchmark_return = (
                total_return_from_adjusted_open(benchmark, buy_date, terminal_date)
                if benchmark is not None and buy_date is not None and terminal_date is not None
                else None
            )
            result[f"m{month}_observed"] = metric.observed
            result[f"m{month}_recovered"] = metric.recovered
            result[f"m{month}_max_close"] = metric.max_close
            result[f"m{month}_max_close_excess_pct"] = (
                metric.excess * 100.0 if metric.excess is not None else None
            )
            result[f"m{month}_max_close_trading_days"] = metric.max_close_trading_days
            result[f"m{month}_max_close_date"] = (
                metric.max_close_date.date().isoformat()
                if metric.max_close_date is not None
                else None
            )
            result[f"m{month}_fixed_close"] = metric.fixed_close
            result[f"m{month}_fixed_date"] = (
                metric.fixed_date.date().isoformat()
                if metric.fixed_date is not None
                else None
            )
            result[f"m{month}_x_h_pct"] = (
                metric.fixed_excess * 100.0
                if metric.fixed_excess is not None
                else None
            )
            result[f"m{month}_excess_pct"] = (
                metric.fixed_excess * 100.0
                if metric.fixed_excess is not None
                else None
            )
            result[f"m{month}_recovery_trading_days"] = metric.recovery_trading_days
            result[f"m{month}_terminal_close"] = metric.terminal_close
            result[f"m{month}_terminal_date"] = (
                terminal_date.date().isoformat() if terminal_date is not None else None
            )
            result[f"m{month}_terminal_recovered"] = (
                metric.terminal_close > previous_close
                if metric.terminal_close is not None
                else None
            )
            result[f"m{month}_terminal_excess_pct"] = (
                metric.terminal_excess * 100.0
                if metric.terminal_excess is not None
                else None
            )
            result[f"m{month}_max_drawdown_pct"] = metric.max_drawdown_pct
            result[f"m{month}_pre_recovery_min_close"] = metric.pre_recovery_min_close
            result[f"m{month}_pre_recovery_min_excess_pct"] = (
                metric.pre_recovery_min_excess_pct
            )
            result[f"m{month}_actual_return_pct"] = (
                actual_return * 100.0 if actual_return is not None else None
            )
            result[f"m{month}_benchmark_return_pct"] = (
                benchmark_return * 100.0 if benchmark_return is not None else None
            )
            result[f"m{month}_relative_return_pct"] = (
                (actual_return - benchmark_return) * 100.0
                if actual_return is not None and benchmark_return is not None
                else None
            )
        event_rows.append(result)

    event_frame = pd.DataFrame(event_rows)
    event_frame.to_csv(output_dir / "event_metrics.csv", index=False)
    summaries: list[dict[str, object]] = []
    valid_events = int(len(event_frame))
    valid_companies = int(event_frame["ticker"].nunique()) if valid_events else 0
    for month in MONTHS:
        observed = event_frame[event_frame[f"m{month}_observed"] == True]  # noqa: E712
        x_h = pd.to_numeric(observed[f"m{month}_x_h_pct"], errors="coerce").dropna()
        recovered = observed[observed[f"m{month}_recovered"] == True]  # noqa: E712
        recovered_excesses = pd.to_numeric(
            recovered[f"m{month}_max_close_excess_pct"], errors="coerce"
        ).dropna()
        terminal_recovered = observed[
            observed[f"m{month}_terminal_recovered"] == True  # noqa: E712
        ]
        recovery_days = observed[f"m{month}_recovery_trading_days"].dropna()
        terminal_excesses = pd.to_numeric(
            observed[f"m{month}_terminal_excess_pct"], errors="coerce"
        ).dropna()
        max_close_excesses = pd.to_numeric(
            observed[f"m{month}_max_close_excess_pct"], errors="coerce"
        ).dropna()
        max_close_days = pd.to_numeric(
            observed[f"m{month}_max_close_trading_days"], errors="coerce"
        ).dropna()
        actual_returns = observed[f"m{month}_actual_return_pct"].dropna()
        benchmark_returns = observed[f"m{month}_benchmark_return_pct"].dropna()
        relative_returns = observed[f"m{month}_relative_return_pct"].dropna()
        drawdowns = observed[f"m{month}_max_drawdown_pct"].dropna()
        pre_recovery_excesses = observed[
            f"m{month}_pre_recovery_min_excess_pct"
        ].dropna()

        def quantile(values: pd.Series, probability: float) -> float | None:
            return float(values.quantile(probability)) if len(values) else None

        x_h_positive = x_h[x_h > 0]
        x_h_non_positive = x_h[x_h <= 0]
        worst_decile_size = math.ceil(len(x_h) * 0.10) if len(x_h) else 0
        unrecovered_max_close = max_close_excesses[max_close_excesses <= 0]

        def positive_quantile(probability: float) -> float | None:
            return quantile(x_h_positive, probability)

        def bucket_count(condition: pd.Series) -> int:
            return int(condition.sum())

        summaries.append(
            {
                "month": month,
                "valid_events": valid_events,
                "valid_companies": valid_companies,
                "observed_events": int(len(observed)),
                "observed_companies": int(observed["ticker"].nunique())
                if len(observed)
                else 0,
                "recovered": int(len(recovered)),
                "observed": int(len(observed)),
                "recovery_rate_pct": (
                    len(recovered) / len(observed) * 100 if len(observed) else None
                ),
                "average_excess_pct": x_h.mean() if len(x_h) else None,
                "median_excess_pct": x_h.median() if len(x_h) else None,
                "recovered_average_excess_pct": (
                    recovered_excesses.mean() if len(recovered_excesses) else None
                ),
                "recovered_median_excess_pct": (
                    recovered_excesses.median() if len(recovered_excesses) else None
                ),
                "terminal_recovered": int(len(terminal_recovered)),
                "terminal_recovery_rate_pct": (
                    len(terminal_recovered) / len(observed) * 100
                    if len(observed)
                    else None
                ),
                "fixed_point_recovered": int(len(terminal_recovered)),
                "fixed_point_recovery_rate_pct": (
                    len(terminal_recovered) / len(observed) * 100
                    if len(observed)
                    else None
                ),
                "positive_x_h_count": int(len(x_h_positive)),
                "positive_x_h_rate_pct": (
                    len(x_h_positive) / len(x_h) * 100 if len(x_h) else None
                ),
                "x_h_average_pct": x_h.mean() if len(x_h) else None,
                "x_h_median_pct": x_h.median() if len(x_h) else None,
                "x_h_p10_pct": quantile(x_h, 0.10),
                "x_h_p25_pct": quantile(x_h, 0.25),
                "x_h_p75_pct": quantile(x_h, 0.75),
                "x_h_p90_pct": quantile(x_h, 0.90),
                "positive_x_h_average_pct": (
                    x_h_positive.mean() if len(x_h_positive) else None
                ),
                "positive_x_h_median_pct": (
                    x_h_positive.median() if len(x_h_positive) else None
                ),
                "positive_x_h_p10_pct": positive_quantile(0.10),
                "positive_x_h_p25_pct": positive_quantile(0.25),
                "positive_x_h_p75_pct": positive_quantile(0.75),
                "positive_x_h_p90_pct": positive_quantile(0.90),
                "unrecovered_x_h_count": int(len(x_h_non_positive)),
                "unrecovered_x_h_average_gap_pct": (
                    -x_h_non_positive.mean() if len(x_h_non_positive) else None
                ),
                "unrecovered_x_h_median_gap_pct": (
                    -x_h_non_positive.median() if len(x_h_non_positive) else None
                ),
                "worst_decile_average_x_h_pct": (
                    x_h.nsmallest(worst_decile_size).mean()
                    if worst_decile_size
                    else None
                ),
                "recovery_trading_days_median": (
                    recovery_days.median() if len(recovery_days) else None
                ),
                "recovery_trading_days_p25": quantile(recovery_days, 0.25),
                "recovery_trading_days_p75": quantile(recovery_days, 0.75),
                "excess_p10_pct": quantile(x_h, 0.10),
                "excess_p25_pct": quantile(x_h, 0.25),
                "excess_p75_pct": quantile(x_h, 0.75),
                "excess_p90_pct": quantile(x_h, 0.90),
                "max_close_average_excess_pct": (
                    max_close_excesses.mean() if len(max_close_excesses) else None
                ),
                "max_close_median_excess_pct": (
                    max_close_excesses.median() if len(max_close_excesses) else None
                ),
                "max_close_excess_p10_pct": quantile(max_close_excesses, 0.10),
                "max_close_excess_p25_pct": quantile(max_close_excesses, 0.25),
                "max_close_excess_p75_pct": quantile(max_close_excesses, 0.75),
                "max_close_excess_p90_pct": quantile(max_close_excesses, 0.90),
                "max_close_trading_days_median": (
                    max_close_days.median() if len(max_close_days) else None
                ),
                "never_recovered_max_close_count": int(len(unrecovered_max_close)),
                "never_recovered_max_close_gap_pct": (
                    -unrecovered_max_close.mean() if len(unrecovered_max_close) else None
                ),
                "terminal_average_excess_pct": (
                    terminal_excesses.mean() if len(terminal_excesses) else None
                ),
                "terminal_median_excess_pct": (
                    terminal_excesses.median() if len(terminal_excesses) else None
                ),
                "terminal_excess_p10_pct": quantile(terminal_excesses, 0.10),
                "terminal_excess_p25_pct": quantile(terminal_excesses, 0.25),
                "terminal_excess_p75_pct": quantile(terminal_excesses, 0.75),
                "terminal_excess_p90_pct": quantile(terminal_excesses, 0.90),
                "terminal_positive_count": int(len(x_h_positive)),
                "terminal_positive_rate_pct": (
                    len(x_h_positive) / len(x_h) * 100
                    if len(x_h)
                    else None
                ),
                "terminal_positive_average_pct": (
                    x_h_positive.mean() if len(x_h_positive) else None
                ),
                "terminal_positive_median_pct": (
                    x_h_positive.median() if len(x_h_positive) else None
                ),
                "terminal_positive_p10_pct": positive_quantile(0.10),
                "terminal_positive_p25_pct": positive_quantile(0.25),
                "terminal_positive_p75_pct": positive_quantile(0.75),
                "terminal_positive_p90_pct": positive_quantile(0.90),
                "terminal_non_positive_count": int(len(x_h_non_positive)),
                "terminal_non_positive_average_pct": (
                    x_h_non_positive.mean() if len(x_h_non_positive) else None
                ),
                "terminal_worst_decile_average_pct": (
                    x_h.nsmallest(worst_decile_size).mean()
                    if worst_decile_size
                    else None
                ),
                "terminal_positive_0_5_count": bucket_count(
                    (x_h > 0) & (x_h <= 5)
                ),
                "terminal_positive_5_10_count": bucket_count(
                    (x_h > 5) & (x_h <= 10)
                ),
                "terminal_positive_10_20_count": bucket_count(
                    (x_h > 10) & (x_h <= 20)
                ),
                "terminal_positive_20_plus_count": bucket_count(x_h > 20),
                "positive_0_5_count": bucket_count((x_h > 0) & (x_h <= 5)),
                "positive_5_10_count": bucket_count((x_h > 5) & (x_h <= 10)),
                "positive_10_20_count": bucket_count((x_h > 10) & (x_h <= 20)),
                "positive_20_plus_count": bucket_count(x_h > 20),
                "terminal_non_positive_0_to_minus_5_count": bucket_count(
                    (x_h <= 0) & (x_h > -5)
                ),
                "terminal_non_positive_minus_5_to_minus_10_count": bucket_count(
                    (x_h <= -5) & (x_h > -10)
                ),
                "terminal_non_positive_minus_10_to_minus_20_count": bucket_count(
                    (x_h <= -10) & (x_h > -20)
                ),
                "terminal_non_positive_minus_20_plus_count": bucket_count(
                    x_h <= -20
                ),
                "negative_0_5_gap_count": bucket_count((x_h <= 0) & (x_h > -5)),
                "negative_5_10_gap_count": bucket_count((x_h <= -5) & (x_h > -10)),
                "negative_10_20_gap_count": bucket_count(
                    (x_h <= -10) & (x_h > -20)
                ),
                "negative_20_plus_gap_count": bucket_count(x_h <= -20),
                "actual_return_observed": int(len(actual_returns)),
                "actual_return_average_pct": (
                    actual_returns.mean() if len(actual_returns) else None
                ),
                "actual_return_median_pct": (
                    actual_returns.median() if len(actual_returns) else None
                ),
                "actual_return_p10_pct": quantile(actual_returns, 0.10),
                "actual_return_p25_pct": quantile(actual_returns, 0.25),
                "actual_return_p75_pct": quantile(actual_returns, 0.75),
                "actual_return_p90_pct": quantile(actual_returns, 0.90),
                "benchmark_return_observed": int(len(benchmark_returns)),
                "benchmark_return_average_pct": (
                    benchmark_returns.mean() if len(benchmark_returns) else None
                ),
                "relative_return_observed": int(len(relative_returns)),
                "relative_return_average_pct": (
                    relative_returns.mean() if len(relative_returns) else None
                ),
                "relative_return_median_pct": (
                    relative_returns.median() if len(relative_returns) else None
                ),
                "relative_return_p10_pct": quantile(relative_returns, 0.10),
                "relative_return_p25_pct": quantile(relative_returns, 0.25),
                "relative_return_p75_pct": quantile(relative_returns, 0.75),
                "relative_return_p90_pct": quantile(relative_returns, 0.90),
                "max_drawdown_average_pct": (
                    drawdowns.mean() if len(drawdowns) else None
                ),
                "max_drawdown_median_pct": (
                    drawdowns.median() if len(drawdowns) else None
                ),
                "pre_recovery_min_excess_median_pct": (
                    pre_recovery_excesses.median()
                    if len(pre_recovery_excesses)
                    else None
                ),
                "right_censored": int(len(event_frame) - len(observed)),
            }
        )
    summary_frame = pd.DataFrame(summaries)
    summary_frame.to_csv(output_dir / "monthly_summary.csv", index=False)
    source_metadata: dict[str, object] = {}
    metadata_path = data_dir / "metadata.json"
    if metadata_path.exists():
        source_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    (output_dir / "calculation_metadata.json").write_text(
        json.dumps(
            {
                "cutoff": cutoff.date().isoformat(),
                "universe_rows": int(len(universe)),
                "low_open_events": int(len(event_frame)),
                "sample_label": (
                    "current_sp500_proxy"
                    if "State Street SPY holdings"
                    in str(source_metadata.get("universe_source", ""))
                    else "custom_or_legacy_universe"
                ),
                "universe_source": source_metadata.get("universe_source"),
                "actual_buy_return": (
                    "next_trading_day_open_to_adjusted_close_total_return"
                ),
                "benchmark_relative_return": (
                    "SPY_adjusted_open_to_adjusted_close"
                    if benchmark is not None
                    else "NOT_AVAILABLE"
                ),
                "recovery_rule": (
                    "fixed point: C_H / P_SEC - 1 using the last available Close "
                    "on or before reaction date plus H calendar months; "
                    "window path: strict max(Close) > P_SEC"
                ),
                "window_rule": (
                    "reaction date through reaction date plus calendar months, inclusive"
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary_frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "download",
            "download-current",
            "download-benchmark",
            "calculate",
            "calculate-current",
            "all",
            "all-current",
        ],
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--screen-report", type=Path, default=DEFAULT_SCREEN_REPORT)
    args = parser.parse_args()
    if args.command in {"download", "all"}:
        download_snapshot(args.data_dir, args.screen_report)
    if args.command in {"download-current", "all-current"}:
        download_current_snapshot(args.data_dir / "current")
    if args.command == "download-benchmark":
        download_benchmark(args.data_dir / "current")
    if args.command in {"calculate", "calculate-current", "all", "all-current"}:
        calculate_snapshot(
            args.data_dir / "current"
            if args.command in {"calculate-current", "all-current"}
            else args.data_dir
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
