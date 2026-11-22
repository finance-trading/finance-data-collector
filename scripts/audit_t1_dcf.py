"""Audit + summary for the Tier-1 DCF report batch.

Checks every T1 report exists, parses the pasted calculator JSON block,
recomputes discount/premium from intrinsic-vs-price, and writes
``reports/tier1-dcf/_summary.md`` (one line per company + batch stats).

Run:  uv run python scripts/audit_t1_dcf.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fdc.data_files import PROJECT_ROOT

T1 = "AAPL ALAB AMAT AMD AMZN ANET APH APP ASML AVGO CDNS COHR COST CRM CRWD CSCO ETN FTNT GEV GOOG GOOGL IBM INTC LIN LRCX META MSFT MU NEE NET NFLX NOW NVDA ORCL PANW PLTR SAP SHOP SNDK SPOT TSLA TSM TXN UBER V".split()
REPORTS = PROJECT_ROOT / "reports" / "tier1-dcf"


def parse_report(path: Path) -> dict:
    text = path.read_text()
    out = {"intrinsic": None, "price": None, "bear": None, "base": None, "bull": None, "has_sections": True}
    # v2 machine-readable line (authoritative when present)
    m = re.search(r"<!--\s*audit:\s*bear=([-\d.]+)\s+base=([-\d.]+)\s+bull=([-\d.]+)\s+price=([-\d.]+)", text)
    if m:
        out["bear"], out["base"], out["bull"], out["price"] = (float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)))
        out["intrinsic"] = out["base"]
        return out
    # v1 fallbacks below
    # prefer the pasted calculator JSON block
    m = re.search(r'"intrinsic_per_share"\s*:\s*(-?[\d.]+)', text)
    if m:
        out["intrinsic"] = float(m.group(1))
    m2 = re.search(r'"price_now"\s*:\s*(-?[\d.]+)', text)
    if m2:
        out["price"] = float(m2.group(1))
    # fallback: parse the 结论 section, tolerating markdown bold/spacing
    tail = text.split("## 结论")[-1] if "## 结论" in text else text
    if out["intrinsic"] is None:
        # Foreign-currency reports state the comparable USD result after FX;
        # prefer that converted figure over the local-currency intermediate.
        fx = re.search(r"按\s*FX\s*换算[^$]*\$\s*([\d,]+\.?\d*)\s*/\s*股", tail, flags=re.I)
        if fx:
            out["intrinsic"] = float(fx.group(1).replace(",", ""))
        else:
            m3 = re.search(r"内在价值[^0-9\-]{0,40}(-?[\d,]+\.?\d*)\s*(?:USD|EUR|TWD)?\s*/\s*股", tail)
            if m3:
                out["intrinsic"] = float(m3.group(1).replace(",", ""))
    if out["price"] is None:
        m4 = re.search(r"现价[^0-9\-]{0,40}\$?(-?[\d,]+\.?\d*)", tail)
        if m4:
            out["price"] = float(m4.group(1).replace(",", ""))
    # GOOG is an intentional pointer report, not a full DCF
    if path.name != "GOOG.md":
        for section in ("基本信息", "计算流程", "参数来源", "公式", "敏感性", "结论"):
            if section not in text:
                out["has_sections"] = False
                break
    return out


def main() -> int:
    rows = []
    for ticker in T1:
        path = REPORTS / f"{ticker}.md"
        if not path.exists():
            rows.append({"ticker": ticker, "missing": True})
            continue
        info = parse_report(path)
        intrinsic, price = info["intrinsic"], info["price"]
        rows.append({"ticker": ticker, "intrinsic": intrinsic, "price": price,
                     "bear": info["bear"], "base": info["base"], "bull": info["bull"],
                     "missing": False, "structure_ok": info["has_sections"]})

    present = [r for r in rows if not r["missing"]]
    missing = [r["ticker"] for r in rows if r["missing"]]
    bad_structure = [r["ticker"] for r in present if not r["structure_ok"]]
    no_numbers = [r["ticker"] for r in present if r["intrinsic"] is None or r["price"] is None]

    def classify(r: dict) -> str:
        price, base = r["price"], r["intrinsic"]
        if r["bear"] is not None and r["bull"] is not None:
            if price < r["bear"]:
                return "偏便宜（低于 bear 情景）"
            if price < base:
                return "偏便宜（bear~base 区间）"
            if price <= r["bull"]:
                return "大致合理（base~bull 区间）"
            return "偏贵（高于 bull 情景）"
        return "偏贵" if price > base else "偏便宜"

    rows_sorted = sorted([r for r in present if r["intrinsic"] is not None], key=lambda r: r["intrinsic"] or 0, reverse=True)
    lines = [
        "# T1 DCF 批量估值汇总（dcf-valuation skill；v2 = TTM 基期 + bear/base/bull 三情景，政策见 _brief.md / _brief_v2.md）",
        "",
        f"- 批次：{len(present)}/{len(T1)} 份报告已生成（缺：{', '.join(missing) or '无'}）",
        f"- 结构不完整：{', '.join(bad_structure) or '无'}；无法解析数字：{', '.join(no_numbers) or '无'}",
        "- 数据：yfinance 年度三表 + 季度 TTM 基期 + funnel 价格快照（as-of 2026-11-20）+ ^TNX Rf；统一 ERP 5.0%、g≤2.5%、税率截断 [12%,30%]、周期股正常化 FCF",
        "",
        "| ticker | bear/股 | base/股 | bull/股 | 现价/股 | 现价定位 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for r in rows_sorted:
        b = f"${r['bear']:.2f}" if r["bear"] is not None else "—"
        u = f"${r['bull']:.2f}" if r["bull"] is not None else "—"
        lines.append(f"| {r['ticker']} | {b} | ${r['intrinsic']:.2f} | {u} | ${r['price']:.2f} | {classify(r)} |")
    counts = {}
    for r in present:
        if r["intrinsic"] is not None:
            counts[classify(r)] = counts.get(classify(r), 0) + 1
    lines = [f"- 现价定位分布：" + "；".join(f"{k} {v} 家" for k, v in sorted(counts.items())), *lines[1:]]
    (REPORTS / "_summary.md").write_text("\n".join(lines) + "\n")
    print(f"reports {len(present)}/{len(T1)}; missing={missing}; bad_structure={bad_structure}; no_numbers={no_numbers}")
    print("distribution:", counts)
    print("wrote", REPORTS / "_summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
