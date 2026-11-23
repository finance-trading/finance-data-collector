"""v3: re-base the T1 DCF batch to a standardized TTM-actuals base.

Policy (user decision 2026-11-21):
  - base  = standardized: growth Y1 = min(TTM revenue YoY, 30%) fading
            geometrically to max(4%, 0.4*g1); EBIT margin = TTM actual, flat;
            g = 2.0%.
  - bear  = the agent's original normalized base path (parsed from the report,
            re-validated by re-running the calculator within 6% of the old
            audit value, else the report is left untouched).
  - bull  = the agent's original bull path (same validation).
  - Cyclical/turnaround tickers (peak TTM margins or TTM EBIT margin < 5%)
    keep their reports unchanged (flat-peak margins are not defensible).

Regenerates standard-ticker reports with the unified template + history table
+ 3-scenario + base sensitivity + audit line; writes _summary.md via
scripts/audit_t1_dcf.py afterwards.
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
HELD_CYCLICAL = {"INTC", "LRCX", "MU", "TXN", "AMAT", "AMD", "COHR", "SNDK", "TSM"}
SKIP = {"GOOG"}  # mirrors GOOGL


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


FIVE = r"(\d+(?:\.\d+)?(?:[ ,/，/]\d+(?:\.\d+)?){4,}(?:\s*%)?)"
FLAT = r"(\d+(?:\.\d+)?)\s*%\s*(?:flat|平稳|水平)"
G5 = r"g\s*[=＝:：]?\s*(\d+(?:\.\d+)?)\s*%"


def parse_scenario_region(region: str) -> dict | None:
    """Extract {growth[5], margin[5], g} from the text after a scenario label."""

    m = re.search(FIVE, region)
    if m:
        growth = [float(x.rstrip("%")) for x in re.split(r"[ ,/，]", m.group(1))][:5]
        rest = region[m.end():]
    else:
        return None
    mm = re.search(FIVE, rest)
    if mm:
        margin = [float(x.rstrip("%")) for x in re.split(r"[ ,/，]", mm.group(1))][:5]
        rest2 = rest[mm.end():]
    else:
        mf = re.search(FLAT, rest)
        if not mf:
            return None
        margin = [float(mf.group(1))] * 5
        rest2 = rest[mf.end():]
    mg = re.search(G5, rest2)
    if not mg:
        mg = re.search(r"\|\s*(\d+(?:\.\d+)?)\s*%\s*\|", rest2)
    if not mg:
        return None
    g = float(mg.group(1))
    if len(growth) != 5 or len(margin) != 5:
        return None
    return {"growth": growth, "margin": margin, "g": g}


def parse_scenarios(text: str) -> dict[str, dict | None]:
    """Find each scenario label and parse its following region."""

    out: dict[str, dict | None] = {}
    for label in ("bear", "base", "bull"):
        found = None
        for m in re.finditer(rf"\b{label}\b", text, flags=re.IGNORECASE):
            region = text[m.end(): m.end() + 420]
            parsed = parse_scenario_region(region)
            if parsed:
                found = parsed
                break
        out[label] = found
    return out


def run_calc(calc, ticker: str, sc: dict, label: str) -> dict:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        calc.main([
            "--pack", str(REPORTS / "_data" / f"{ticker}.json"), "--base", "ttm", "--label", label,
            "--growth", ",".join(f"{x:.1f}" for x in sc["growth"]),
            "--margin", ",".join(f"{x:.1f}" for x in sc["margin"]),
            "--g", f"{sc['g']:.1f}",
        ])
    return json.loads(buf.getvalue())


def audit_line(path: Path) -> dict | None:
    m = re.search(r"<!--\s*audit:\s*bear=(-?[\d.]+)\s+base=(-?[\d.]+)\s+bull=(-?[\d.]+)\s+price=([\d.]+)", path.read_text())
    if not m:
        return None
    return {"bear": float(m.group(1)), "base": float(m.group(2)), "bull": float(m.group(3)), "price": float(m.group(4))}


def hist_block(ticker: str) -> str:
    """Rebuild the annual-history table from the pack (same as group outputs)."""

    pack = json.loads((REPORTS / "_data" / f"{ticker}.json").read_text())
    rows = []
    labels = {"revenue": "Total Revenue", "operating_income": "Operating Income", "net_income": "Net Income",
              "cfo": "Operating Cash Flow", "capex": "Capital Expenditure", "dda": "Depreciation And Amortization"}
    ends = sorted({x["end"] for m in labels for x in pack["annuals"][m] if x["value"] is not None}, reverse=True)[:5]
    for end in ends:
        cells = []
        for metric in ("revenue", "operating_income", "net_income", "cfo", "capex", "dda"):
            row = next((x for x in pack["annuals"][metric] if x["end"] == end), None)
            v = row["value"] if row else None
            if metric == "capex" and v is not None:
                v = abs(v)
            cells.append(f"{v/1e9:.2f}" if v is not None else "—")
        rows.append(f"| {end} | " + " | ".join(cells) + " |")
    return "\n".join([
        "## 历史年度数据（$B；源行标签 yfinance annual pack，缺失以 — 标注）",
        "| Fiscal year-end | Revenue | EBIT | Net income | CFO | Capex(abs) | D&A |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *rows,
        "来源：`Total Revenue`/`Operating Income`/`Net Income`/`Operating Cash Flow`/`Capital Expenditure`/`Depreciation And Amortization`；capex 按绝对值。",
    ])


def write_report(ticker: str, bear: dict, base: dict, bull: dict, pack: dict, calc_results: dict) -> None:
    ttm = pack["ttm"]
    price = calc_results["base"]["result"]["price_now"]
    name = pack.get("info", {}).get("longName") or ticker
    fx = FX.get(ticker)
    fx_note = f"（按报告币种计算，FX 假设 1 {pack['info'].get('currency', 'EUR/TWD')} = {'1.15' if ticker == 'SAP' else '0.0305'} USD，沿用 v2 报告口径）" if fx else ""
    L = [f"# {ticker} — {name} DCF 估值报告（v3：TTM 实际口径 base）", ""]
    L += [
        "## 1. 基本信息",
        f"- **报告日期**：2026-11-21；**现价**：${price}{fx_note}",
        f"- **基期**：TTM（截至 {ttm.get('as_of_quarter')}）；**股本**：{calc_results['base']['inputs']['shares']:,.0f}（{calc_results['base']['assumptions'].get('shares','')}）",
        f"- **Beta**：{calc_results['base']['inputs']['beta_used']:.3f}（yfinance info，政策截断）",
        f"- **TTM Revenue / EBIT**：${(ttm.get('revenue') or 0)/1e9:.1f}B / ${(ttm.get('operating_income') or 0)/1e9:.1f}B（yfinance 季度加总；ΔNWC≈0）",
        "",
        hist_block(ticker),
        "",
        "## 2. 计算流程",
        "### Base 情景五年预测（$B，TTM 起算，margin 按 TTM 实际持平）",
    ]
    proj = calc_results["base"]["projection"]
    L += ["| 年 | Revenue | 增速 | EBIT margin | FCF |", "|---|---:|---:|---:|---:|"]
    for i in range(5):
        L.append(f"| Y{i+1} | {proj['revenue_path'][i+1]/1e9:.1f} | {proj['growth_pct'][i]:.1f}% | {proj['margin_pct'][i]:.1f}% | {proj['fcf_path'][i]/1e9:.1f} |")
    L += [
        "",
        "- **bear** = v2 agent 归一化 base 路径（增速 " + ",".join(f"{x:.1f}" for x in bear["growth"]) + f"%；margin " + ",".join(f"{x:.1f}" for x in bear["margin"]) + f"%；g={bear['g']:.1f}%）",
        "- **base** = 标准化 TTM 实际口径（增速 " + ",".join(f"{x:.1f}" for x in base["growth"]) + f"%；margin TTM 实际 " + f"{base['margin'][0]:.1f}%" + " 持平；g=2.0%）",
        "- **bull** = v2 agent 原 bull 路径（增速 " + ",".join(f"{x:.1f}" for x in bull["growth"]) + f"%；margin " + ",".join(f"{x:.1f}" for x in bull["margin"]) + f"%；g={bull['g']:.1f}%）",
        "",
        "## 3. 三情景估值",
        "| 情景 | 内在价值/股 | vs 现价 |",
        "|---|---:|---:|",
    ]
    for lbl in ("bear", "base", "bull"):
        v = calc_results[lbl]["result"]["intrinsic_per_share"] * fx if fx else calc_results[lbl]["result"]["intrinsic_per_share"]
        L.append(f"| {lbl} | ${v:,.2f} | {(v/price-1)*100:+.1f}% |")
    L += ["", "### Base 情景敏感性（每股；WACC±1% × g±0.5%）"]
    grid = calc_results["base"]["sensitivity_per_share"]
    gkeys = sorted({k for wk in grid for k in grid[wk]}, key=lambda s: float(s.replace("g", "").replace("%", "").strip()))
    L.append("| WACC ↓ / g → | " + " | ".join(gk for gk in gkeys) + " |")
    L.append("|---|" + "---:|" * len(gkeys))
    for wk in grid:
        L.append(f"| {wk} | " + " | ".join(f"{grid[wk][gk]:,.2f}" for gk in gkeys) + " |")
    tvpct = calc_results["base"]["projection"]["tv_pct_of_ev"]
    L += [
        f"",
        f"Base TV/EV={tvpct*100:.0f}%；负 FCF/负权益情景下该比例仅作诊断。",
        "",
        "## 4. 参数来源与方法",
        f"- WACC：{calc_results['base']['assumptions'].get('wacc')}；Rf {calc_results['base']['assumptions'].get('rf')}；ERP {calc_results['base']['assumptions'].get('erp')}",
        f"- 税率：{calc_results['base']['assumptions'].get('tax')}",
        f"- D&A/capex：{calc_results['base']['assumptions'].get('da')}；{calc_results['base']['assumptions'].get('capex')}",
        "- TTM 基期：yfinance quarterly 最近四季加总 + 最新季度时点（现金/债务/股本）；历史年度数据见上表。",
        "- 方法：5 年显式预测 + Gordon 永续；UFCF=EBIT×(1−t)+D&A−Capex（ΔNWC≈0）；Re=Rf+β×ERP；TV=FCF₆/(WACC−g)。",
        "",
        "## 5. 结论",
    ]
    bv = calc_results["bear"]["result"]["intrinsic_per_share"] * (fx or 1)
    mv = calc_results["base"]["result"]["intrinsic_per_share"] * (fx or 1)
    uv = calc_results["bull"]["result"]["intrinsic_per_share"] * (fx or 1)
    L.append(f"区间 **${bv:,.2f}（bear）— ${uv:,.2f}（bull）/股**，base **${mv:,.2f}**，现价 ${price}{fx_note}。主要敏感变量：WACC、g、margin 持续性。模型输出，非投资建议。")
    L += ["", f"<!-- audit: bear={bv:.2f} base={mv:.2f} bull={uv:.2f} price={price} currency=USD -->"]
    (REPORTS / f"{ticker}.md").write_text("\n".join(L) + "\n")


def main() -> int:
    calc = load_calc()
    standard, held, failed = [], [], []
    for t in T1:
        if t in SKIP:
            continue
        pack = json.loads((REPORTS / "_data" / f"{t}.json").read_text())
        ttm = pack.get("ttm") or {}
        margin = (ttm.get("operating_income") or 0) / (ttm.get("revenue") or 1) * 100 if ttm.get("revenue") else -1
        if t in HELD_CYCLICAL or margin < 5.0:
            held.append(t)
            continue
        text = (REPORTS / f"{t}.md").read_text()
        old = audit_line(REPORTS / f"{t}.md")
        parsed = parse_scenarios(text)
        if not all(parsed.values()):
            failed.append((t, "parse-missing"))
            continue
        # validate parsed old base & bull against old audit values
        ok = True
        fx = FX.get(t, 1.0)
        for lbl, expected in (("base", old["base"]), ("bull", old["bull"])):
            if parsed[lbl] is None:
                ok = False
                break
            res = run_calc(calc, t, parsed[lbl], lbl)
            got = res["result"]["intrinsic_per_share"] * fx
            if expected != 0 and abs(got - expected) / abs(expected) > 0.06:
                ok = False
                break
        if not ok:
            failed.append((t, f"validate (base/bull vs old audit)"))
            continue
        yoy = ttm_yoy_rev(pack, t) or 0.0
        g1 = min(max(yoy, 4.0), 30.0)
        g5 = max(4.0, 0.4 * g1)
        step = (g5 - g1) / 4
        growth = [g1 + step * i for i in range(5)]
        m_flat = round(margin, 1)
        base_sc = {"growth": growth, "margin": [m_flat] * 5, "g": 2.0}
        bear_sc, bull_sc = parsed["base"], parsed["bull"]
        results = {"bear": run_calc(calc, t, bear_sc, "bear"), "base": run_calc(calc, t, base_sc, "base"), "bull": run_calc(calc, t, bull_sc, "bull")}
        write_report(t, bear_sc, base_sc, bull_sc, pack, results)
        standard.append(t)
        bv = results["base"]["result"]["intrinsic_per_share"] * fx
        print(f"{t:5} old-base {old['base']:>9.2f} -> new-base {bv:>9.2f}  (bear {results['bear']['result']['intrinsic_per_share']*fx:.2f}, bull {results['bull']['result']['intrinsic_per_share']*fx:.2f})")
    print(f"\nstandard(regen): {len(standard)}; held(unchanged): {held}; failed(untouched): {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
