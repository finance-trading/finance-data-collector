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
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any

import yfinance as yf
from yfinance.config import YfConfig

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
            # "This week" is the last five trading sessions.
            week_base = (
                round(float(closes.iloc[-6]), 2) if len(closes) >= 6 else None
            )
            quotes[tk] = {
                "price": price,
                "previous_close": prev,
                "change_pct": _pct_change(price, prev),
                "week_change_pct": _pct_change(price, week_base),
                "change_52w_pct": _pct_change(price, _close_before(closes, 52)),
                "market_cap": caps.get(tk),
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
    args = parser.parse_args()
    if args.check:
        raise SystemExit(0 if check_connection() else 1)
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