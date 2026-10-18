"""Fetch latest close prices for the AI company universe and cache them locally.

Reads ``data/ai_companies.json`` for tickers, downloads two years of daily
history from Yahoo Finance via yfinance, and writes
``data/generated/quotes.json`` for the read API.  Skips when the file is
already from today — pass ``--force`` to override.

Usage:
    uv run python -m fdc.quotes           # daily refresh (idempotent)
    uv run python -m fdc.quotes --force   # always re-fetch
    uv run python -m fdc.quotes --check   # probe Yahoo/proxy with one ticker
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any

import yfinance as yf
from yfinance.config import YfConfig
from requests import Session
from bs4 import BeautifulSoup

from fdc.config import get_settings
from fdc.data_files import CATALOG_PATH, QUOTES_PATH

logger = logging.getLogger(__name__)


def _redact(proxy: str) -> str:
    """Strip any userinfo so credentials never reach the logs."""

    scheme, _, rest = proxy.partition("://")
    if "@" in rest:
        rest = rest.rsplit("@", 1)[1]
    return f"{scheme}://{rest}" if scheme else rest


def apply_proxy() -> str | None:
    """Route yfinance through the configured proxy, if there is one.

    yfinance talks to Yahoo over curl_cffi, which ignores ``HTTPS_PROXY``, so
    its own network config is the only supported hook.  Yahoo's ATS edge
    answers datacenter egress with HTTP 429 before any request reaches the
    API; a proxy is the only way to change the source address.
    """

    proxy = get_settings().resolved_quotes_proxy
    YfConfig.network.proxy = proxy
    if proxy:
        logger.info("routing Yahoo Finance through proxy %s", _redact(proxy))
    return proxy


def _load_tickers() -> list[str]:
    """Return sorted, unique tickers from the AI company catalog."""
    payload = json.loads(CATALOG_PATH.read_text())
    return sorted({company["ticker"].upper() for company in payload["companies"]})


def already_refreshed_today(force: bool = False) -> bool:
    """Return True when quotes.json is from today and `force` is False."""
    if force or not QUOTES_PATH.exists():
        return False
    try:
        payload = json.loads(QUOTES_PATH.read_text())
        gen = payload.get("generated_at")
        return (
            isinstance(gen, str)
            and datetime.fromisoformat(gen).astimezone().date() == date.today()
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        return False


def _market_caps(tickers: list[str], workers: int = 16) -> dict[str, int]:
    """Return market cap in USD per ticker; absent keys mean unavailable.

    ``yf.download`` does not expose market cap, and yfinance has no batched
    accessor, so this fetches ``fast_info`` per ticker in a small thread pool.
    Roughly 9s for the 227-ticker universe — acceptable for a daily job.
    """

    def cap(ticker: str) -> tuple[str, int | None]:
        try:
            value = yf.Ticker(ticker).fast_info["marketCap"]
        except Exception:
            return ticker, None
        try:
            return ticker, round(float(value)) if value else None
        except (TypeError, ValueError):
            return ticker, None

    caps: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for ticker, value in pool.map(cap, tickers):
            if value is not None:
                caps[ticker] = value
    return caps


def _pct_change(price: float, base: float | None) -> float | None:
    """Return the percentage move from `base` to `price`, or None if unusable."""

    if base is None or base == 0:
        return None
    return round((price - base) / base * 100, 2)


def _drawdown_from_high(price: float, high: float | None) -> float | None:
    """Return the percentage drawdown from a period high to `price`."""

    if high is None or high <= 0:
        return None
    return round((price / high - 1) * 100, 2)


def _rise_from_low(price: float, low: float | None) -> float | None:
    """Return the percentage rise from a period low to `price`."""

    if low is None or low <= 0:
        return None
    return round((price / low - 1) * 100, 2)


FINVIZ_QUOTE_URL = "https://finviz.com/quote.ashx?t={ticker}"
# Valuation metrics live in Finviz's "snapshot" table as label/value cell pairs.
FINVIZ_LABEL_TO_KEY = {
    "P/E": "pe",
    "EPS (ttm)": "eps_ttm",
    "Forward P/E": "forward_pe",
    "EPS next Y": "forward_eps",
}


def _parse_finviz_metrics(html: str) -> dict[str, float]:
    """Return numeric Finviz snapshot metrics from one quote page.

    Finviz renders the snapshot table with a plain label cell followed by a
    value cell, so a linear scan keeps the parser immune to layout shifts and
    avoids CSS-class coupling. Missing or dash placeholders are simply absent
    from the result — callers treat absent keys as unavailable.
    """

    soup = BeautifulSoup(html, "html.parser")
    cells: list[str] = []
    for table in soup.find_all("table", class_=re.compile(r"snapshot-table2")):
        cells.extend(cell.get_text(strip=True) for cell in table.find_all("td"))
    if not cells:
        return {}
    metrics: dict[str, float] = {}
    for label, key in FINVIZ_LABEL_TO_KEY.items():
        if label not in cells:
            continue
        index = cells.index(label)
        if index + 1 >= len(cells):
            continue
        raw = cells[index + 1]
        try:
            metrics[key] = float(raw.replace(",", "").replace("%", ""))
        except ValueError:
            continue
    return metrics


def _finviz_metrics(
    tickers: list[str], workers: int = 8, retries: int = 2
) -> dict[str, dict[str, float]]:
    """Return Finviz valuation metrics per ticker; absent keys are unavailable.

    Finviz serves a static snapshot page per quote; 227 pages through a small
    thread pool with browser-style headers stay well inside polite request
    volume for a once-daily job. A failed page drops only that ticker's
    metrics, never the whole refresh.
    """

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

    def fetch(ticker: str) -> tuple[str, dict[str, float]]:
        session = Session()
        try:
            for attempt in range(retries + 1):
                try:
                    response = session.get(
                        FINVIZ_QUOTE_URL.format(ticker=ticker), headers=headers, timeout=15
                    )
                    response.raise_for_status()
                    values = _parse_finviz_metrics(response.text)
                    if values:
                        return ticker, values
                except Exception:
                    pass
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
            return ticker, {}
        except Exception:
            return ticker, {}
        finally:
            session.close()

    metrics: dict[str, dict[str, float]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for ticker, values in pool.map(fetch, tickers):
            if values:
                metrics[ticker] = values
    return metrics


def _close_before(closes: Any, weeks: int) -> float | None:
    """Return the last close on or before `weeks` before the latest session.

    Using a calendar offset rather than a row offset keeps the 52-week figure
    correct across weekends and holidays; the closest prior session stands in
    for a missing trading day.
    """

    target = closes.index[-1] - timedelta(weeks=weeks)
    prior = closes.loc[:target]
    if prior.empty:
        return None
    return round(float(prior.iloc[-1]), 2)


def _period_high(closes: Any, weeks: int) -> float | None:
    """Return the high since the calendar-period start, or None if incomplete."""

    if closes.empty:
        return None
    target = closes.index[-1] - timedelta(weeks=weeks)
    if closes.index[0] > target:
        return None
    window = closes.loc[target:]
    return round(float(window.max()), 2) if not window.empty else None


def _period_low(closes: Any, weeks: int) -> float | None:
    """Return the low since the calendar-period start, or None if incomplete."""

    if closes.empty:
        return None
    target = closes.index[-1] - timedelta(weeks=weeks)
    if closes.index[0] > target:
        return None
    window = closes.loc[target:]
    return round(float(window.min()), 2) if not window.empty else None


def fetch_quotes() -> dict[str, Any]:
    """Fetch last close and trailing returns for every ticker in the catalog.

    Uses a single batched yfinance download (threaded); missing and delisted
    tickers are silently dropped.  Returns a payload suitable for
    ``quotes.json``.
    """
    tickers = _load_tickers()
    apply_proxy()
    logger.info("fetching quotes for %d tickers", len(tickers))

    try:
        data = yf.download(
            tickers,
            # Two years, not one: the 52-week baseline is looked up by calendar
            # date, and a single year leaves too little slack for a holiday-heavy
            # tape. Still one batched request, just more rows.
            period="2y",
            interval="1d",
            group_by="ticker",
            threads=True,
            auto_adjust=True,
            progress=False,
            prepost=False,
        )
    except Exception:
        logger.exception("yfinance download failed")
        raise

    caps = _market_caps(tickers)
    logger.info("%d tickers have market cap data", len(caps))

    valuation = _finviz_metrics(tickers)
    logger.info("%d tickers have Finviz valuation data", len(valuation))

    quotes: dict[str, dict[str, float | int | None]] = {}
    for tk in tickers:
        try:
            if tk not in data.columns.get_level_values(0):
                continue
            closes = data[tk]["Close"].dropna()
            if closes.empty:
                continue
            price = round(float(closes.iloc[-1]), 2)
            prev = (
                round(float(closes.iloc[-2]), 2) if len(closes) >= 2 else None
            )
            # 1W and 52W are drawdowns from the highest close in each period.
            week_high = (
                round(float(closes.iloc[-5:].max()), 2) if len(closes) >= 5 else None
            )
            week_low = (
                round(float(closes.iloc[-5:].min()), 2) if len(closes) >= 5 else None
            )
            year_high = _period_high(closes, 52)
            year_low = _period_low(closes, 52)
            quotes[tk] = {
                "price": price,
                "previous_close": prev,
                "change_pct": _pct_change(price, prev),
                "week_change_pct": _drawdown_from_high(price, week_high),
                "week_rise_pct": _rise_from_low(price, week_low),
                "change_52w_pct": _drawdown_from_high(price, year_high),
                "rise_52w_pct": _rise_from_low(price, year_low),
                "market_cap": caps.get(tk),
                "pe": valuation.get(tk, {}).get("pe"),
                "eps_ttm": valuation.get(tk, {}).get("eps_ttm"),
                "forward_pe": valuation.get(tk, {}).get("forward_pe"),
                "forward_eps": valuation.get(tk, {}).get("forward_eps"),
            }
        except Exception:
            logger.warning("skipping ticker %s (no usable close data)", tk)

    logger.info("%d tickers have quote data", len(quotes))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "quotes": quotes,
    }

def _has_quotes(payload: dict[str, Any]) -> bool:
    return bool(payload.get("quotes"))


def refresh_valuation_metrics() -> str:
    """Fetch Finviz valuation metrics and merge into the existing cache.

    Yahoo rate limits make a full quote refresh unreliable during market
    hours, while Finviz metrics are the piece users usually need sooner.
    This keeps prices and trailing returns exactly as cached and rewrites
    only the four valuation fields. Returns the cache path.
    """

    if not QUOTES_PATH.exists():
        raise RuntimeError("quotes.json does not exist yet — run a full refresh first")
    payload = json.loads(QUOTES_PATH.read_text())
    quotes: dict[str, dict[str, Any]] = payload.get("quotes", {})
    valuation = _finviz_metrics(sorted(quotes))
    merged = 0
    for tk, values in valuation.items():
        quotes[tk].update(values)
        merged += 1
    payload["valuation_refreshed_at"] = datetime.now(timezone.utc).isoformat()
    QUOTES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    logger.info("merged valuation metrics for %d tickers into %s", merged, QUOTES_PATH)
    return str(QUOTES_PATH)


def _cached_quotes_exist() -> bool:
    """Return True when the on-disk cache already holds usable quotes."""

    try:
        payload = json.loads(QUOTES_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return _has_quotes(payload)


def check_connection(ticker: str = "AAPL") -> bool:
    """Probe Yahoo with a single ticker and report whether the route works.

    Used to validate a proxy node before committing to a full universe fetch.
    Prints a human-readable verdict; returns True only when rows came back.
    """

    proxy = apply_proxy()
    print(f"Proxy: {_redact(proxy) if proxy else 'none (direct)'}")
    try:
        frame = yf.download(
            ticker,
            period="5d",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as exc:  # noqa: BLE001 - the point is to report anything
        print(f"FAIL {ticker}: {type(exc).__name__}: {exc}")
        return False

    rows = 0 if frame is None else len(frame)
    if rows == 0:
        print(
            f"FAIL {ticker}: no rows. Yahoo's edge usually answers 429 when it "
            "blocks the source IP — switch proxy node."
        )
        return False

    # yfinance keeps a (Price, Ticker) column MultiIndex even for one ticker.
    close = frame["Close"]
    if hasattr(close, "columns"):
        close = close.iloc[:, -1]
    close = close.dropna()
    latest = f", last close {close.iloc[-1]:.2f}" if not close.empty else ""
    print(f"OK {ticker}: {rows} rows{latest}")
    return True


def write_quotes(force: bool = False) -> str | None:
    """Generate quotes.json.  Returns the JSON path on write, None when skipped.

    Raises ``RuntimeError`` when the fetch comes back empty and a previous cache
    exists: a blocked or unroutable network must not destroy good data.
    """

    if already_refreshed_today(force):
        logger.info("quotes already refreshed today — pass --force to override")
        return None

    payload = fetch_quotes()
    if not _has_quotes(payload) and _cached_quotes_exist():
        logger.error("fetch returned no quotes — keeping the existing cache")
        raise RuntimeError(
            "Yahoo Finance fetch returned no quotes; existing quotes.json kept"
        )

    path = QUOTES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    logger.info("wrote %d quotes to %s", len(payload["quotes"]), path)
    return str(path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description="Fetch latest close prices for AI company universe"
    )
    parser.add_argument(
        "--force", action="store_true", help="re-fetch even if already refreshed today"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="probe Yahoo with one ticker and exit; validates the proxy route",
    )
    parser.add_argument(
        "--metrics-only",
        action="store_true",
        help="refresh Finviz valuation metrics only, keeping cached prices intact",
    )
    args = parser.parse_args()
    if args.check:
        raise SystemExit(0 if check_connection() else 1)
    if args.metrics_only:
        print(f"Wrote {refresh_valuation_metrics()}")  # noqa: T201
        return
    try:
        result = write_quotes(force=args.force)
    except RuntimeError as exc:
        print(f"Refresh failed: {exc}")  # noqa: T201
        raise SystemExit(1) from exc
    if result is None:
        print("Already up-to-date — nothing fetched.")  # noqa: T201
    else:
        print(f"Wrote {result}")  # noqa: T201


if __name__ == "__main__":
    main()
