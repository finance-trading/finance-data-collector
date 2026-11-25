"""Keyless and free-tier fallback fetchers for market index closes.

The primary source is Yahoo Finance (via yfinance, routed through the Clash
proxy when it is up).  When Yahoo is unavailable — a 429 on direct egress or
the proxy stopped — these fallbacks keep the dashboard populated:

* **Binance** (keyless)  — daily closes for the crypto indices.
* **TwelveData** (free key) — daily closes for the non-crypto indices.

Both fail soft: a miss returns ``None`` so the caller keeps the previously
stored value instead of overwriting it with nothing.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request

from fdc.config import get_settings
from fdc.data_files import PROJECT_ROOT

logger = logging.getLogger(__name__)

#: A browser User-Agent: the public endpoints reject the default Python UA.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_SOURCES_PATH = PROJECT_ROOT / "config" / "market_sources.json"


def _load_sources() -> dict:
    """Alias overrides from config, or an empty map when absent/malformed."""
    try:
        payload = json.loads(_SOURCES_PATH.read_text())
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _get(url: str, timeout: float = 15.0) -> bytes:
    # Keyless public endpoints: force direct egress. The process carries a
    # Clash proxy (HTTPS_PROXY) that is often stopped; routing these through
    # it would just fail with "connection refused", so use an explicit no-proxy
    # opener regardless of the configured proxy.
    request = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return response.read()


def binance_daily_closes(
    symbol: str, days: int = 30, fetch=_get,
) -> list[float] | None:
    """Daily closes for a crypto symbol from Binance klines (keyless).

    ``BTC-USD`` → ``BTCUSDT`` by default; a per-symbol alias can be overridden
    in ``config/market_sources.json`` under ``crypto_binance``.
    """
    alias = _load_sources().get("crypto_binance", {}).get(symbol) or symbol.replace("-USD", "USDT")
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={urllib.parse.quote(alias)}&interval=1d&limit={int(days)}"
    )
    try:
        rows = json.loads(fetch(url))
        closes = [float(row[4]) for row in rows if isinstance(row, list) and len(row) > 4]
        return closes or None
    except Exception:
        logger.warning("Binance fallback failed for %s", alias, exc_info=True)
        return None


def twelvedata_daily_closes(
    symbol: str,
    days: int = 30,
    fetch=_get,
    api_key: str | None = None,
) -> list[float] | None:
    """Daily closes from TwelveData's free tier for a non-crypto symbol.

    Returns ``None`` without a configured key so the caller can keep the last
    stored value.  ``symbol`` may be mapped to a TwelveData alias via
    ``config/market_sources.json`` under ``twelvedata_symbols``.
    """
    key = api_key or get_settings().twelvedata_api_key
    if not key:
        return None
    alias = _load_sources().get("twelvedata_symbols", {}).get(symbol) or symbol
    url = (
        "https://api.twelvedata.com/time_series?symbol="
        f"{urllib.parse.quote(alias)}&interval=1day&outputsize={int(days)}"
        f"&apikey={urllib.parse.quote(key)}"
    )
    try:
        payload = json.loads(fetch(url))
        values = payload.get("values") or []
        closes = [float(v["close"]) for v in values if v.get("close") not in (None, "")]
        if not closes:
            logger.warning("TwelveData returned no closes for %s (%s)", alias, payload.get("status"))
            return None
        return closes
    except Exception:
        logger.warning("TwelveData fallback failed for %s", alias, exc_info=True)
        return None


#: Plain ticker (US ETF/stock): safe to send to TwelveData as-is.
_PLAIN_TICKER = re.compile(r"^[A-Z]{1,5}$")


def fallback_closes(
    symbol: str, category: str, days: int = 30, fetch=_get,
) -> list[float] | None:
    """Keyless/free-tier closes for a symbol, or None when no source applies.

    Crypto resolves to Binance (no key needed); every other category resolves
    to TwelveData (free key, inactive until ``FDC_TWELVEDATA_API_KEY`` is set).
    TwelveData only gets plain tickers and explicitly aliased symbols: for an
    unknown Yahoo-style symbol it may fuzzy-resolve to an unrelated instrument
    (CL=F returned natural-gas closes before the WTI alias existed).
    """
    if category == "crypto":
        return binance_daily_closes(symbol, days, fetch)
    aliases = _load_sources().get("twelvedata_symbols", {})
    if symbol not in aliases and not _PLAIN_TICKER.match(symbol):
        return None
    return twelvedata_daily_closes(symbol, days, fetch)
