"""Fetch latest close prices for the AI company universe and cache them in the database.

Reads ``data/ai_companies.json`` for tickers, downloads two years of daily
history from Yahoo Finance via yfinance, and writes the quotes into the
SQLite ``latest_quote`` table via ``fdc.quote_store``.  Skips when the
database is already from today — pass ``--force`` to override.

Usage:
    uv run python -m fdc.quotes           # daily refresh (idempotent)
    uv run python -m fdc.quotes --force   # always re-fetch
    uv run python -m fdc.quotes --check   # probe Yahoo/proxy with one ticker
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import math
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import yfinance as yf
from bs4 import BeautifulSoup
from requests import Session
from yfinance.config import YfConfig

from fdc import quote_store
from fdc.config import get_settings
from fdc.data_files import CATALOG_PATH

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
    """Return True when the database quotes are from today and `force` is False."""
    if force:
        return False
    try:
        payload = quote_store.load_payload()
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


YAHOO_VALUATION_FIELD = {
    "trailingPE": "pe",
    "epsTrailingTwelveMonths": "eps_ttm",
    "forwardPE": "forward_pe",
    "epsForward": "forward_eps",
}


def _yahoo_valuation(
    tickers: list[str], *, workers: int = 16, retries: int = 2
) -> dict[str, dict[str, float]]:
    """Return Yahoo valuation metrics per ticker; empty dict means unavailable.

    ``yf.download`` does not expose P/E or EPS, so each ticker is probed
    through ``Ticker.info`` in a thread pool (same shape as ``_market_caps``).
    A failed page drops only that ticker's metrics, never the whole refresh.
    """

    def fetch(ticker: str) -> tuple[str, dict[str, float]]:
        for attempt in range(retries + 1):
            try:
                info = yf.Ticker(ticker).info
                values = {
                    key: round(float(info[name]), 2)
                    for name, key in YAHOO_VALUATION_FIELD.items()
                    if info.get(name) is not None
                    and math.isfinite(float(info[name]))
                }
                if values:
                    return ticker, values
            except Exception:
                pass
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
        return ticker, {}

    results: dict[str, dict[str, float]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for ticker, values in pool.map(fetch, tickers):
            if values:
                results[ticker] = values
    return results


def _valuation(
    tickers: list[str],
) -> dict[str, dict[str, float]]:
    """Yahoo valuation first, then the official Finviz API, HTML scraping last.

    The API needs a Finviz Elite token (``FDC_FINVIZ_API_KEY``) but returns
    every ticker in one CSV request, so it is tried before the throttled
    per-ticker page scraping. Each stage only fills tickers (and fields) the
    previous ones left empty.
    """

    valuation = _yahoo_valuation(tickers)
    missing = sorted(tk for tk in tickers if not valuation.get(tk))
    token = get_settings().resolved_finviz_api_key
    if missing and token:
        api_metrics = _finviz_api_metrics(missing, token)
        for tk, values in api_metrics.items():
            merged = valuation.setdefault(tk, {})
            for key, value in values.items():
                merged.setdefault(key, value)
        if api_metrics:
            logger.info("finviz api filled %d tickers", len(api_metrics))
        missing = sorted(tk for tk in tickers if not valuation.get(tk))
    if missing:
        logger.info(
            "valuation sources missing %d tickers — finviz html fallback", len(missing)
        )
        valuation.update(_finviz_metrics(missing))
    return valuation


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

# Official Elite export endpoint; the valuation view (v=121) already carries
# exactly the four columns this collector needs, keyed by header text.
FINVIZ_EXPORT_URL = "https://elite.finviz.com/export.ashx"
FINVIZ_VALUATION_VIEW = "121"
FINVIZ_API_CHUNK_SIZE = 50

FINVIZ_API_HEADER_TO_KEY = {
    "p/e": "pe",
    "fwd p/e": "forward_pe",
    "forward p/e": "forward_pe",
    "eps (ttm)": "eps_ttm",
    "eps ttm": "eps_ttm",
    "eps": "eps_ttm",
    "eps next y": "forward_eps",
    "eps est. next y": "forward_eps",
    "eps estimate next year": "forward_eps",
    "eps next year": "forward_eps",
}


def _parse_finviz_api_metrics(csv_text: str) -> dict[str, dict[str, float]]:
    """Return valuation metrics per ticker from one Elite export CSV.

    Headers drift between Finviz views and plans, so matching is by normalized
    header text with several known spellings per metric. Missing cells and
    dash placeholders stay absent — callers treat absent keys as unavailable.
    """

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        return {}
    columns = {}
    for header in reader.fieldnames:
        key = FINVIZ_API_HEADER_TO_KEY.get(header.strip().lower())
        if key and key not in columns.values():
            columns[header] = key
    if "Ticker" not in reader.fieldnames or not columns:
        return {}
    metrics: dict[str, dict[str, float]] = {}
    for row in reader:
        ticker = (row.get("Ticker") or "").strip().upper()
        if not ticker:
            continue
        values: dict[str, float] = {}
        for header, key in columns.items():
            raw = (row.get(header) or "").strip()
            try:
                number = float(raw.replace(",", "").replace("%", ""))
            except ValueError:
                continue
            if math.isfinite(number):
                values[key] = round(number, 2)
        if values:
            metrics[ticker] = values
    return metrics


def _finviz_api_metrics(
    tickers: list[str],
    token: str,
    *,
    chunk_size: int = FINVIZ_API_CHUNK_SIZE,
) -> dict[str, dict[str, float]]:
    """Return valuation metrics via the official Finviz Elite export API.

    One CSV request per ``chunk_size`` tickers — the export endpoint accepts a
    ``t=`` ticker list, so the whole universe fits in a handful of requests
    instead of one throttled scrape per ticker. A failed chunk drops only its
    own tickers, never the whole refresh.
    """

    session = Session()
    try:
        metrics: dict[str, dict[str, float]] = {}
        for start in range(0, len(tickers), chunk_size):
            chunk = tickers[start : start + chunk_size]
            try:
                response = session.get(
                    FINVIZ_EXPORT_URL,
                    params={
                        "v": FINVIZ_VALUATION_VIEW,
                        "ft": "4",
                        "t": ",".join(chunk),
                        "auth": token,
                    },
                    timeout=30,
                )
                response.raise_for_status()
                metrics.update(_parse_finviz_api_metrics(response.text))
            except Exception:
                logger.warning(
                    "finviz api export failed for tickers %d-%d",
                    start,
                    start + len(chunk),
                )
        return metrics
    finally:
        session.close()


class _Throttle:
    """Serialize request starts with a minimum spacing; safe across threads.

    Finviz rate limits aggressive scraping, so every request start hands out
    a timestamp at least ``interval`` (plus jitter) after the previous one.
    Spacing is assigned before sleeping so concurrent callers queue up behind
    a single schedule instead of firing after a shared wake-up.
    """

    def __init__(
        self,
        interval: float,
        jitter: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = interval
        self._jitter = jitter
        self._clock = clock
        self._sleeper = sleeper
        self._last = float("-inf")
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            spacing = self._interval + (
                random.uniform(0, self._jitter) if self._jitter > 0 else 0.0
            )
            start = max(self._clock(), self._last + spacing)
            self._last = start
            delay = start - self._clock()
        if delay > 0:
            self._sleeper(delay)


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
    tickers: list[str],
    *,
    workers: int = 3,
    retries: int = 2,
    min_interval: float = 1.1,
    jitter: float = 0.5,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> dict[str, dict[str, float]]:
    """Return Finviz valuation metrics per ticker; absent keys are unavailable.

    Finviz serves a static snapshot page per quote, but rate limits aggressive
    scraping: every request start is spaced at least ``min_interval`` seconds
    apart (plus ``jitter``) through a shared throttle, and a failed page drops
    only that ticker's metrics, never the whole refresh.
    """

    clock = clock or time.monotonic
    sleeper = sleeper or time.sleep
    throttle = _Throttle(min_interval, jitter, clock, sleeper)

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

    def fetch(ticker: str) -> tuple[str, dict[str, float]]:
        session = Session()
        try:
            for attempt in range(retries + 1):
                try:
                    throttle.wait()
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
                    sleeper(1.5 * (attempt + 1))
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
    tickers are silently dropped.  Returns a payload suitable for the
    quote store.
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

    valuation = _valuation(tickers)
    logger.info("%d tickers have valuation data", len(valuation))

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
            # 1W, 1M, and 52W are drawdowns from the highest close in each period.
            week_high = (
                round(float(closes.iloc[-5:].max()), 2) if len(closes) >= 5 else None
            )
            week_low = (
                round(float(closes.iloc[-5:].min()), 2) if len(closes) >= 5 else None
            )
            month_high = _period_high(closes, 4)
            month_low = _period_low(closes, 4)
            year_high = _period_high(closes, 52)
            year_low = _period_low(closes, 52)
            quotes[tk] = {
                "price": price,
                "previous_close": prev,
                "change_pct": _pct_change(price, prev),
                "week_change_pct": _drawdown_from_high(price, week_high),
                "week_rise_pct": _rise_from_low(price, week_low),
                "month_change_pct": _drawdown_from_high(price, month_high),
                "month_rise_pct": _rise_from_low(price, month_low),
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
    """Fetch valuation metrics (Yahoo, Finviz fallback) and merge into cache.

    Yahoo rate limits make a full quote refresh unreliable during market
    hours, while the four valuation fields are the piece users usually need
    sooner. This keeps prices and trailing returns exactly as cached and
    rewrites only the four valuation fields. Returns a summary string.
    """

    payload = quote_store.load_payload()
    if not payload.get("quotes"):
        raise RuntimeError("database has no quotes yet — run a full refresh first")
    quotes: dict[str, dict[str, Any]] = payload["quotes"]
    valuation = _valuation(sorted(quotes))
    merged = 0
    for tk, values in valuation.items():
        quotes[tk].update(values)
        merged += 1
    payload["valuation_refreshed_at"] = datetime.now(timezone.utc).isoformat()
    quote_store.save_payload(payload)
    logger.info("merged valuation metrics for %d tickers into database", merged)
    return f"{merged} valuation rows (database)"


def _cached_quotes_exist() -> bool:
    """Return True when the database already holds usable quotes."""
    try:
        return _has_quotes(quote_store.load_payload())
    except (OSError, json.JSONDecodeError):
        return False


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
    """Refresh quotes into the database.  Returns a summary string, None when skipped.

    Raises ``RuntimeError`` when the fetch comes back empty and previous quotes
    exist: a blocked or unroutable network must not destroy good data.
    """

    if already_refreshed_today(force):
        logger.info("quotes already refreshed today — pass --force to override")
        return None

    payload = fetch_quotes()
    if not _has_quotes(payload) and _cached_quotes_exist():
        logger.error("fetch returned no quotes — keeping the existing database rows")
        raise RuntimeError(
            "Yahoo Finance fetch returned no quotes; existing database quotes kept"
        )

    previous = quote_store.load_payload()
    if previous and _has_quotes(payload):
        # Tickers transiently dropped by the fetch (rate-limit, glitch) keep
        # their cached prices, but P/E and EPS are only ever live values, so
        # reset them to None — the UI shows "—".
        for ticker, old in previous.get("quotes", {}).items():
            if ticker not in payload["quotes"]:
                quote = dict(old)
                for key in ("pe", "eps_ttm", "forward_pe", "forward_eps"):
                    quote[key] = None
                payload["quotes"][ticker] = quote
    quote_store.save_payload(payload)
    logger.info("wrote %d quotes to database", len(payload["quotes"]))
    return f"{len(payload['quotes'])} quotes (database)"


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
        help="refresh valuation metrics (Yahoo, Finviz fallback) only, "
        "keeping cached prices intact",
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
