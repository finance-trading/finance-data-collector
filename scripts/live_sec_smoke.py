"""Opt-in, attributed connectivity smoke check against one public SEC file."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
OPT_IN_VALUES = {"1", "true", "yes"}
CONTACT_PATTERN = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")


def _is_enabled(environ: Mapping[str, str]) -> bool:
    return environ.get("FDC_RUN_LIVE_SEC_SMOKE", "").strip().lower() in OPT_IN_VALUES


def _contact_user_agent(environ: Mapping[str, str]) -> str | None:
    user_agent = environ.get("FDC_SEC_USER_AGENT", "").strip()
    if not user_agent or CONTACT_PATTERN.search(user_agent) is None:
        return None
    return user_agent


def run_smoke(
    environ: Mapping[str, str],
    *,
    opener: Callable[..., Any] = urlopen,
    emit: Callable[[str], None] = print,
) -> int:
    """Make at most one SEC request, and only after explicit environment opt-in."""

    if not _is_enabled(environ):
        emit(
            "SKIPPED: set FDC_RUN_LIVE_SEC_SMOKE=1 to allow one attributed SEC request"
        )
        return 0

    user_agent = _contact_user_agent(environ)
    if user_agent is None:
        emit("SKIPPED: FDC_SEC_USER_AGENT must include a monitored contact email")
        return 0

    request = Request(
        SEC_TICKERS_URL,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": user_agent,
        },
    )
    try:
        with opener(request, timeout=15.0) as response:
            if response.status != 200:
                emit(f"FAILED: SEC returned HTTP {response.status}")
                return 1
            payload = json.loads(response.read(2_000_000))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
        emit(f"FAILED: SEC request did not produce valid JSON ({type(error).__name__})")
        return 1

    if not isinstance(payload, dict) or not any(
        isinstance(company, dict) and company.get("ticker") == "MSFT"
        for company in payload.values()
    ):
        emit("FAILED: SEC ticker payload did not contain the expected MSFT record")
        return 1

    emit("PASS: SEC returned a company ticker payload containing MSFT")
    return 0


def main() -> int:
    """Run from the process environment without printing the contact identity."""

    return run_smoke(os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
