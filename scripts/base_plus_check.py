"""Standardized 'base+' counterfactual vs each report's agent-set base.

Same batch policy (WACC/tax/shares/g=2.0), but two standardized levers:
  growth  = min(TTM revenue YoY, 30%) fading geometrically to max(4%, 0.4*g1)
  margin  = TTM EBIT margin held flat (no agent downward normalization)
Cyclicals/turnarounds (TTM EBIT margin < 5%) keep the agent's base (excluded).
SAP/TSM values are converted with the FX assumption stated in their reports.

Run: uv run python scripts/base_plus_check.py
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from fdc.data_files import PROJECT_ROOT

T1 = "AAPL ALAB AMAT AMD AMZN ANET APH APP ASML AVGO CDNS COHR COST CRM CRWD CSCO ETN FTNT GEV GOOG GOOGL IBM INTC LIN LRCX META MSFT MU NEE NET NFLX NOW NVDA ORCL PANW PLTR SAP SHOP SNDK SPOT TSLA TSM TXN UBER V".split()
REPORTS = PROJECT_ROOT / "reports" / "tier1-dcf"
QCACHE = PROJECT_ROOT / "data" / "company_quality" / "yahoo_cache_q"
FX = {"SAP": 1.15, "TSM": 0.0305}  # per each report's stated assumption (USD per reporting currency)
SKIP = {"GOOG"}  # same entity as GOOGL
# Cyclical / memory / semi-equipment names whose TTM EBIT margin is a PEAK:
# a flat-peak-margin "base+" would be indefensible, so keep the agent's
# normalized base for these (per batch policy 7).
CYCLICAL_HOLD = {"INTC", "LRCX", "MU", "TXN", "AMAT", "AMD", "COHR"}


def load_calc():
    spec = importlib.util.spec_from_file_location("dcf_calc", PROJECT_ROOT / "scripts" / "dcf_calc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ttm_yoy_rev(ticker: str) -> float | None:
    pack = json.loads((REPORTS / "_data" / f"{ticker}.json").read_text())
    yoy = pack.get("ttm", {}).get("ttm_revenue_yoy_pct")
    if yoy is not None:
        return float(yoy)
    # recompute from quarterly income cache when 8 quarters exist
    try:
        q = json.loads((QCACHE / f"{ticker}.json").read_text())["quarterly"]["income"]
        ends = sorted(q, reverse=True)
        if len(ends) >= 8:
            def s4(keys):
                vals = [q[e].get("Total Revenue") for e in keys]
                return sum(vals) if all(v is not None for v in vals) else None

            now, prior = s4(ends[:4]), s4(ends[4:8])
            if now and prior:
                return (now / prior - 1) * 100
    except Exception:
        pass
    # fallback: latest two annual revenues
    revs = [x["value"] for x in pack["annuals"]["revenue"] if x["value"]]
    if len(revs) >= 2:
        return (revs[0] / revs[1] - 1) * 100
    return None


def main() -> int:
    calc = load_calc()
    out = []
    for t in T1:
        if t in SKIP:
            continue
        pack = json.loads((REPORTS / "_data" / f"{t}.json").read_text())
        ttm = pack.get("ttm", {})
        m = ttm.get("operating_income")
        r = ttm.get("revenue")
        if not m or not r:
            out.append((t, None, None, "no-ttm"))
            continue
        margin = m / r * 100
        if t in CYCLICAL_HOLD or margin < 5.0:
            out.append((t, None, None, f"cyclical/turnaround (TTM margin {margin:.0f}%) — keep agent base"))
            continue
        g1 = min(max(ttm_yoy_rev(t) or 0.0, 4.0), 30.0)
        g5 = max(4.0, 0.4 * g1)
        step = (g5 - g1) / 4
        growth = [g1 + step * i for i in range(5)]
        y, p = (REPORTS / f"{t}.md").read_text(), None
        am = re.search(r"<!--\s*audit:\s*bear=[-\d.]+\s+base=(-?[\d.]+)\s+bull=[-\d.]+\s+price=([\d.]+)\s+currency=(\w+)", y)
        # agent-base in the audit line is already in its stated currency (USD);
        # our computed `plus` is in the pack's reporting currency, so convert
        # only the `plus` side with FX (SAP EUR, TSM TWD).
        agent_base = float(am.group(1)) if am else None
        price = float(am.group(2)) if am else pack["price_snapshot"].get("price")
        fx = FX.get(t, 1.0)
        import io, contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            calc.main([
                "--pack", str(REPORTS / "_data" / f"{t}.json"), "--base", "ttm", "--label", "base+",
                "--growth", ",".join(f"{x:.1f}" for x in growth),
                "--margin", ",".join(f"{margin:.1f}" for _ in range(5)),
                "--g", "2.0",
            ])
        plus = float(json.loads(buf.getvalue())["result"]["intrinsic_per_share"]) * fx
        out.append((t, agent_base, plus, f"g1 {g1:.0f}%→g5 {g5:.0f}%, margin {margin:.0f}% flat (yoy {ttm_yoy_rev(t)})"))
    out.sort(key=lambda x: x[1] is None)
    print(f"{'T':6} {'agent-base':>10} {'base+':>10} {'Δ%':>8}  note")
    flipped, improved, flat, worse = 0, 0, 0, 0
    for t, ab, bp, note in out:
        if ab is None:
            print(f"{t:6} {'-':>10} {'-':>10} {'-':>8}  {note}")
            continue
        d = (bp / ab - 1) * 100
        print(f"{t:6} {ab:>10.2f} {bp:>10.2f} {d:>+7.1f}%  {note}")
        if d > 15:
            improved += 1
        elif d < -15:
            worse += 1
        else:
            flat += 1
    print(f"\nbase+ vs agent-base: improved>15%: {improved}, within±15%: {flat}, worse>15%: {worse}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
