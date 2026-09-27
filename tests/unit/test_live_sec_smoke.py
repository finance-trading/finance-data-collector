from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "live_sec_smoke.py"


def load_live_sec_smoke():
    spec = importlib.util.spec_from_file_location("live_sec_smoke", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps(
            {
                "0": {
                    "cik_str": 789019,
                    "ticker": "MSFT",
                    "title": "MICROSOFT CORP",
                }
            }
        ).encode()


def test_live_sec_smoke_skips_without_explicit_opt_in():
    live_sec_smoke = load_live_sec_smoke()
    messages = []

    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("live request must not run without explicit opt-in")

    result = live_sec_smoke.run_smoke(
        {},
        opener=unexpected_request,
        emit=messages.append,
    )

    assert result == 0
    assert messages == [
        "SKIPPED: set FDC_RUN_LIVE_SEC_SMOKE=1 to allow one attributed SEC request"
    ]


def test_live_sec_smoke_sends_configured_contact_user_agent():
    live_sec_smoke = load_live_sec_smoke()
    messages = []
    observed = {}

    def opener(request, *, timeout):
        observed["url"] = request.full_url
        observed["user_agent"] = request.get_header("User-agent")
        observed["timeout"] = timeout
        return FakeResponse()

    result = live_sec_smoke.run_smoke(
        {
            "FDC_RUN_LIVE_SEC_SMOKE": "1",
            "FDC_SEC_USER_AGENT": "Finance Data Collector ops@firm.test",
        },
        opener=opener,
        emit=messages.append,
    )

    assert result == 0
    assert observed == {
        "url": "https://www.sec.gov/files/company_tickers.json",
        "user_agent": "Finance Data Collector ops@firm.test",
        "timeout": 15.0,
    }
    assert messages == ["PASS: SEC returned a company ticker payload containing MSFT"]
