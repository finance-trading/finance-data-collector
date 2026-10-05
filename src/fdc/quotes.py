"""Fetch latest close prices for the AI company universe and cache them locally.

Reads ``data/ai_companies.json`` for tickers, downloads the last five
trading days from Yahoo Finance via yfinance, and writes
``data/generated/quotes.json`` for the read API.  Skips when the file is
already from today — pass ``--force`` to override.

Usage:
    uv run python -m fdc.quotes           # daily refresh (idempotent)
    uv run python -m fdc.quotes --force   # always re-fetch
"""

from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any

import yfinance as yf

from fdc.data_files import CATALOG_PATH, QUOTES_PATH

logger = logging.getLogger(__name__)


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
            and datetime.fromisoformat(gen).date() == date.today()
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


def fetch_quotes() -> dict[str, Any]:
    """Fetch last close and previous close for every ticker in the catalog.

    Uses a single batched yfinance download (threaded); missing and delisted
    tickers are silently dropped.  Returns a payload suitable for
    ``quotes.json``.
    """
    tickers = _load_tickers()
    logger.info("fetching quotes for %d tickers", len(tickers))

    try:
        data = yf.download(
            tickers,
            period="5d",
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
            change_pct = (
                round((price - prev) / prev * 100, 2)
                if prev is not None and prev != 0
                else None
            )
            quotes[tk] = {
                "price": price,
                "previous_close": prev,
                "change_pct": change_pct,
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


def write_quotes(force: bool = False) -> str | None:
    """Generate quotes.json.  Returns the JSON path on write, None when skipped."""
    if already_refreshed_today(force):
        logger.info("quotes already refreshed today — pass --force to override")
        return None

    payload = fetch_quotes()
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
    args = parser.parse_args()
    result = write_quotes(force=args.force)
    if result is None:
        print("Already up-to-date — nothing fetched.")  # noqa: T201
    else:
        print(f"Wrote {result}")  # noqa: T201


if __name__ == "__main__":
    main()