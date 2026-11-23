"""v3b: standardized TTM-actuals base, keeping each report's bear/bull values.

For each standard ticker:
  - base  = calculator with growth = min(TTM YoY,30%) fading to max(4%,0.4*g1),
            EBIT margin = TTM actual flat, g=2.0%, everything else (WACC inputs,
            tax, D&A/capex ratios, shares) from the pack defaults the v2 report
            already used.
  - bear/bull = the v2 values verbatim (from the audit line).
Report body keeps v2 structure, updates the base row + base sensitivity grid +
conclusion, adds a v3 note. Cyclicals/turnarounds (TTM EBIT margin < 5% or in
HELD) are untouched.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
from pathlib import Path

from fdc.data_files import PROJECT_ROOT

T1 = "AAPL ALAB AMAT AMD AMZN ANET APH APP ASML AVGO CDNS COHR COST CRM CRWD CSCO ETN FTNT GEV GOOG GOOGL IBM INTC LIN LRCX META MSFT MU NEE NET NFLX NOW NVDA ORCL PANW PLTR SAP SHOP SNDK SPOT TSLA TSM TXN UBER V".split()
REPORTS = PROJECT_ROOT / "reports" / "tier1-dcf"
QCACHE = PROJECT_ROOT / "data" / "company_quality" / "yahoo_cache_q"
FX = {"SAP": 1.15, "TSM": 0.0305}
HELD = {"INTC", "LRCX", "MU", "TXN", "AMAT", "AMD", "COHR", "SNDK", "TSM", "COST", "CRWD", "NET", "PANW", "TSLA"}
MIN_MARGIN = 5.0


def load_calc():
    spec = importlib.util.spec_from_file_location("dcf_calc", PROJECT_ROOT / "scripts" / "dcf_calc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ttm_yoy_rev(pack: dict, ticker: str) -> float | None:
    yoy = (pack.get("ttm") or {}).get("ttm_revenue_yoy_pct")
    if yoy is not None:
        return float(yoy)
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
    revs = [x["value"] for x in pack["annuals"]["revenue"] if x["value"]]
    if len(revs) >= 2:
        return (revs[0] / revs[1] - 1) * 100
    return None


def run_calc(calc, ticker: str, growth, margin, g: float, label: str) -> dict:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        calc.main([
            "--pack", str(REPORTS / "_data" / f"{ticker}.json"), "--base", "ttm", "--label", label,
            "--growth", ",".join(f"{x:.1f}" for x in growth),
            "--margin", ",".join(f"{x:.1f}" for x in margin),
            "--g", f"{g:.1f}",
        ])
    return json.loads(buf.getvalue())


def audit_values(path: Path) -> dict:
    m = re.search(r"<!--\s*audit:\s*bear=(-?[\d.]+)\s+base=(-?[\d.]+)\s+bull=(-?[\d.]+)\s+price=([\d.]+)", path.read_text())
    return {"bear": float(m.group(1)), "base": float(m.group(2)), "bull": float(m.group(3)), "price": float(m.group(4))}


def insert_v3(text: str, ticker: str, new_base_usd: float, old_base_usd: float, price: float,
              growth, margin, g: float) -> str:
    """Rewrite only the base value cells, conclusion base, and audit line."""

    nv, ov = new_base_usd, old_base_usd
    out_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("| base |") and "$" in stripped:
            cells = line.split("|")
            for i, cell in enumerate(cells):
                if "$" in cell:
                    cells[i] = f" ${nv:,.2f} "
                    for j in range(i + 1, len(cells)):
                        if "%" in cells[j]:
                            cells[j] = f" {(nv/price-1)*100:+.1f}% "
                            break
                    break
            line = "|".join(cells)
        out_lines.append(line)
    text = "\n".join(out_lines)
    # conclusion: the base figure (range form or plain)
    text = re.sub(r"(base\s*\**\$)[\d,\.\-]+", lambda m: f"{m.group(1)}{nv:,.2f}", text)
    text = re.sub(r"base=\-?[\d.]+", f"base={nv:.2f}", text)
    text += (f"\n> **v3 变更**：base 改为标准化 TTM 实际口径（增速 {','.join(f'{x:.1f}' for x in growth)}%，"
             f"EBIT margin {margin[0]:.1f}%（TTM 实际）持平，g={g:.1f}%），base ${ov:,.2f} → **${nv:,.2f}**；"
             f"bear/bull 沿用 v2。周期股与低/负 margin 公司保留 v2 归一化 base。\n")
    return text


def main() -> int:
    calc = load_calc()
    done, held, failed = [], [], []
    for t in T1:
        if t == "GOOG":
            continue
        pack = json.loads((REPORTS / "_data" / f"{t}.json").read_text())
        ttm = pack.get("ttm") or {}
        r, m = ttm.get("revenue"), ttm.get("operating_income")
        margin = (m / r * 100) if (r and m) else None
        if margin is None or margin < MIN_MARGIN or t in HELD:
            held.append(t)
            continue
        path = REPORTS / f"{t}.md"
        old = audit_values(path)
        fx = FX.get(t, 1.0)
        yoy = ttm_yoy_rev(pack, t) or 0.0
        g1 = min(max(yoy, 4.0), 30.0)
        g5 = max(4.0, 0.4 * g1)
        step = (g5 - g1) / 4
        growth = [round(g1 + step * i, 1) for i in range(5)]
        m_flat = round(margin, 1)
        res = run_calc(calc, t, growth, [m_flat] * 5, 2.0, "base")
        new_base = res["result"]["intrinsic_per_share"]
        text = path.read_text()
        text = insert_v3(text, t, new_base, old["base"], old["price"], fx, growth, [m_flat] * 5, 2.0, res,
                         res["sensitivity_per_share"], res["projection"]["tv_pct_of_ev"])
        path.write_text(text)
        done.append(t)
        print(f"{t:5} v2-base {old['base']:>8.2f} -> v3-base {new_base*fx:>8.2f}  (bear {old['bear']:.2f}, bull {old['bull']:.2f})")
    print(f"\nregen base: {len(done)}; held(unchanged): {held}; failed: {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
