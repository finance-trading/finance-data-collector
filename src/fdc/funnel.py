"""AI value-chain company funnel: auto-tier inside each layer, then export.

Each of the six AI value-chain layers (power, silicon, infra, model, app, edge)
gets its own three-tier funnel.  Companies compete only inside their layer, so a
small power name is not pushed to the bottom by mega-cap software:

    T1 核心   top 20% by market cap   deep dossier,     weekly + event
    T2 重要   20%–50%                 one-page card,    monthly + earnings
    T3 观察   bottom 50%              price/news scan,  quarterly

Market cap is the automatic proxy for importance.  Manual overrides in
``config/funnel_overrides.json`` always win, which is how ecosystem-critical but
smaller companies (EDA, optical interconnect, power) are promoted.

Tiers decide *how deeply* a company is covered; they do not authorize a buy.
The price band only decides when a covered name starts event research — the
four-layer screening rules still gate every action.

Usage:
    uv run python -m fdc.funnel              # write JSON + Excel + daily diff
    uv run python -m fdc.funnel --check      # alert only; non-zero on stale/missing quotes
    uv run python -m fdc.funnel --no-xlsx    # JSON + CSV only
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
import tempfile
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from fdc.ai_layers import load_universe
from fdc.data_files import GENERATED_DATA_DIR, PROJECT_ROOT, QUOTES_PATH, write_json_artifact

FUNNEL_PATH = GENERATED_DATA_DIR / "funnel.json"
OVERRIDES_PATH = PROJECT_ROOT / "config" / "funnel_overrides.json"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "ai-funnel"
XLSX_PATH = OUTPUT_DIR / "ai-chain-company-funnel.xlsx"
DAILY_CSV_PATH = OUTPUT_DIR / "daily-changes.csv"

TIER_NAMES = {1: "核心", 2: "重要", 3: "观察"}
TIER_SHARE = (0.20, 0.50)  # cumulative market-cap cutoffs inside one layer
TRIGGER_DRAWDOWN = {1: 15.0, 2: 20.0, 3: 30.0}
PRICE_ALERT_PCT = 5.0
DEFAULT_MAX_QUOTE_AGE_DAYS = 2
_OVERRIDE_LOCK = threading.Lock()

RESEARCH_DEPTH = {
    1: "完整 dossier：业务拆解、5 年财务、KPI、竞争格局、估值区间、证伪条件",
    2: "一页公司卡片 + 季度财报跟踪",
    3: "仅价格 / 市值 / 关键新闻扫描，不做独立估值",
}
UPDATE_CADENCE = {
    1: "每周 + 事件后 24h",
    2: "每月 + 财报后",
    3: "每季度",
}
TRIGGER_ACTION = {
    1: "回撤 ≥15% 启动事件研究；≥25% 且质量未坏进入行动候选",
    2: "回撤 ≥20% 启动研究，研究后决定是否升 T1",
    3: "回撤 ≥30% 升级审视，无独立行动资格",
}
TIER_ACTION = {1: "可进入 Layer 4 事件研究", 2: "研究后决定是否升级", 3: "无独立行动资格"}


def load_overrides(path: Path | str = OVERRIDES_PATH) -> dict[str, dict[str, Any]]:
    """Read manual tier overrides; a missing file means "auto only".

    Accepted shape::

        {"NVDA": {"tier": 1, "note": "生态核心"}, ...}

    Keys starting with ``_`` are documentation and ignored.  Invalid tiers fail
    loudly so a typo cannot silently fall back to the auto tier.
    """

    resolved = Path(path)
    if not resolved.exists():
        return {}
    payload = json.loads(resolved.read_text())
    overrides: dict[str, dict[str, Any]] = {}
    for raw_ticker, value in payload.items():
        if raw_ticker.startswith("_"):
            continue
        ticker = raw_ticker.upper()
        tier = value.get("tier") if isinstance(value, dict) else value
        if not isinstance(tier, int) or tier not in TIER_NAMES:
            raise ValueError(f"{ticker}: override tier must be 1, 2 or 3, got {tier!r}")
        overrides[ticker] = {"tier": tier, "note": (value.get("note") or "").strip()}
    return overrides


def _read_raw_overrides(path: Path | str = OVERRIDES_PATH) -> dict[str, Any]:
    """Raw overrides file (including ``_``-prefixed doc keys); ``{}`` when absent."""

    resolved = Path(path)
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text())


def _write_raw_overrides(raw: dict[str, Any], path: Path | str = OVERRIDES_PATH) -> None:
    """Rewrite the overrides file atomically, keeping unrelated keys intact."""

    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{resolved.name}.", dir=resolved.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(raw, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(name, resolved)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def upsert_override(
    ticker: str, tier: int, note: str = "", path: Path | str = OVERRIDES_PATH
) -> dict[str, Any]:
    """Write one company's manual tier; other keys (e.g. the ``_说明`` note) are kept."""

    if type(tier) is not int or tier not in TIER_NAMES:
        raise ValueError(f"override tier must be 1, 2 or 3, got {tier!r}")
    key = ticker.upper()
    with _OVERRIDE_LOCK:
        raw = _read_raw_overrides(path)
        raw[key] = {"tier": tier, "note": note.strip()}
        _write_raw_overrides(raw, path)
    return {"tier": tier, "note": note.strip()}


def remove_override(ticker: str, path: Path | str = OVERRIDES_PATH) -> bool:
    """Drop a manual tier so the company falls back to its auto tier. True if removed."""

    key = ticker.upper()
    with _OVERRIDE_LOCK:
        raw = _read_raw_overrides(path)
        if key not in raw:
            return False
        del raw[key]
        _write_raw_overrides(raw, path)
    return True


def auto_tier_map(
    companies: list[dict], quotes: dict[str, dict[str, Any]]
) -> dict[str, int]:
    """Assign T1/T2/T3 inside each layer by market cap, biggest first.

    Companies without a market cap sort last.  Ticker breaks ties so the output
    is stable across runs.  A layer always contributes at least one T1; layers
    with two or more companies also contribute at least one T2.
    """

    by_layer: dict[str, list[dict]] = defaultdict(list)
    for company in companies:
        by_layer[company["layer"]].append(company)

    result: dict[str, int] = {}
    for members in by_layer.values():
        ranked = sorted(
            members,
            key=lambda item: (
                -(quotes.get(item["ticker"].upper(), {}).get("market_cap") or -1),
                item["ticker"].upper(),
            ),
        )
        total = len(ranked)
        t1_end = max(1, round(total * TIER_SHARE[0]))
        t2_end = max(t1_end + (1 if total > t1_end else 0), math.ceil(total * TIER_SHARE[1]))
        for index, company in enumerate(ranked):
            tier = 1 if index < t1_end else 2 if index < t2_end else 3
            result[company["ticker"].upper()] = tier
    return result


def _quote_metrics(quote: dict[str, Any] | None) -> dict[str, Any]:
    """Price, size, valuation and 52-week position for one ticker.

    The quote file stores drawdown from the 52-week high and rise from the low,
    not the high/low themselves, so both are reconstructed from the percentage
    moves.  A missing or degenerate range yields ``None`` rather than an
    invented position.
    """

    quote = quote or {}
    price = quote.get("price")
    drawdown = quote.get("change_52w_pct")
    rise = quote.get("rise_52w_pct")
    high = low = position = None
    if price and drawdown is not None and rise is not None:
        high = price / (1 + drawdown / 100)
        low = price / (1 + rise / 100)
        if high > low:
            position = (price - low) / (high - low) * 100
    return {
        "price": price,
        "market_cap": quote.get("market_cap"),
        "pe": quote.get("pe"),
        "forward_pe": quote.get("forward_pe"),
        "change_pct": quote.get("change_pct"),
        "drawdown_52w_pct": drawdown,
        "rise_52w_pct": rise,
        "high_52w": round(high, 2) if high is not None else None,
        "low_52w": round(low, 2) if low is not None else None,
        "position_52w_pct": round(position, 1) if position is not None else None,
    }


def build_rows(
    companies: list[dict],
    layers: list[dict],
    quotes: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """One row per company, sorted by layer, tier, then market cap."""

    layer_index = {layer["id"]: index for index, layer in enumerate(layers)}
    layer_names = {layer["id"]: layer["name"] for layer in layers}
    auto = auto_tier_map(companies, quotes)

    rows: list[dict[str, Any]] = []
    for company in companies:
        ticker = company["ticker"].upper()
        auto_tier = auto[ticker]
        override = overrides.get(ticker)
        tier = override["tier"] if override else auto_tier
        metrics = _quote_metrics(quotes.get(ticker))
        rows.append(
            {
                "ticker": ticker,
                "name": company["name"],
                "layer": company["layer"],
                "layer_name": layer_names.get(company["layer"], company["layer"]),
                "segment": company["segment"],
                "auto_tier": auto_tier,
                "tier": tier,
                "tier_name": TIER_NAMES[tier],
                "source": "人工" if override else "自动",
                "note": override["note"] if override else "",
                **metrics,
            }
        )

    rows.sort(
        key=lambda row: (
            layer_index.get(row["layer"], 99),
            row["tier"],
            -(row["market_cap"] or -1),
            row["ticker"],
        )
    )
    return rows


def _price_range(values: list[float]) -> str:
    """Compact min–max string for a price list, or ``—`` when empty."""

    clean = [value for value in values if value is not None]
    if not clean:
        return "—"
    return f"${min(clean):,.2f}–${max(clean):,.2f}"


def tier_index(
    companies: list[dict],
    layers: list[dict],
    quotes: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """TICKER -> ``{tier, tier_name, source, note, auto_tier}`` for the whole universe.

    One resolution pass over every company, so the directory API can join a
    stable tier onto each row without recomputing per page or per filter.
    """

    rows = build_rows(companies, layers, quotes, overrides)
    return {
        row["ticker"]: {
            "tier": row["tier"],
            "tier_name": row["tier_name"],
            "source": row["source"],
            "note": row["note"],
            "auto_tier": row["auto_tier"],
        }
        for row in rows
    }


def tier_watch_items(tier: int | None) -> list[dict[str, Any]]:
    """Default ongoing-coverage matters for a tier, most-important first.

    These are the watch items seeded into a company the first time its research
    card is edited, when it has none of its own yet: research depth, update
    cadence, and the drawdown that starts event research.  All three come from
    the versioned funnel rules (RESEARCH_DEPTH / UPDATE_CADENCE / TRIGGER_ACTION).
    ``priority`` drives the P1/P2/P3 color; empty when the tier is unknown.
    """

    if tier is None or tier not in TIER_NAMES:
        return []
    seeded_at = datetime.now(timezone.utc).isoformat()
    return [
        {"text": RESEARCH_DEPTH[tier], "priority": 1, "created_at": seeded_at},
        {"text": UPDATE_CADENCE[tier], "priority": 2, "created_at": seeded_at},
        {"text": TRIGGER_ACTION[tier], "priority": 3, "created_at": seeded_at},
    ]


def summarize(rows: list[dict[str, Any]], layers: list[dict]) -> list[dict[str, Any]]:
    """Per-layer counts, price ranges and the largest names in each tier."""

    summary: list[dict[str, Any]] = []
    for layer in layers:
        members = [row for row in rows if row["layer"] == layer["id"]]
        entry: dict[str, Any] = {
            "layer": layer["id"],
            "layer_name": layer["name"],
            "total": len(members),
        }
        for tier in TIER_NAMES:
            tier_rows = [row for row in members if row["tier"] == tier]
            entry[f"t{tier}_count"] = len(tier_rows)
            entry[f"t{tier}_prices"] = _price_range([row["price"] for row in tier_rows])
            entry[f"t{tier}_leaders"] = ", ".join(row["ticker"] for row in tier_rows[:3])
        prices = [row["price"] for row in members]
        caps = [row["market_cap"] for row in members]
        entry["price_range"] = _price_range(prices)
        clean_caps = [cap for cap in caps if cap is not None]
        entry["median_market_cap"] = (
            round(statistics.median(clean_caps)) if clean_caps else None
        )
        summary.append(entry)
    return summary


def detect_changes(
    previous_rows: list[dict[str, Any]] | None, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compare today's funnel with the last snapshot.

    Reports new/dropped coverage, tier moves, missing quotes, daily price moves
    and drawdown crossings of a tier's research trigger.  The first run (no
    snapshot) returns an empty list.
    """

    if not previous_rows:
        return []
    before = {row["ticker"]: row for row in previous_rows}
    after = {row["ticker"]: row for row in rows}
    changes: list[dict[str, Any]] = []

    def add(ticker: str, kind: str, previous: Any, current: Any, note: str = "") -> None:
        row = after.get(ticker) or before.get(ticker) or {}
        changes.append(
            {
                "date": datetime.now(timezone.utc).date().isoformat(),
                "ticker": ticker,
                "layer": row.get("layer_name", ""),
                "kind": kind,
                "before": previous,
                "after": current,
                "note": note,
            }
        )

    for ticker in sorted(set(after) - set(before)):
        add(ticker, "新进覆盖", "", after[ticker]["tier_name"], after[ticker]["name"])
    for ticker in sorted(set(before) - set(after)):
        add(ticker, "移出覆盖", before[ticker]["tier_name"], "", before[ticker]["name"])

    for ticker in sorted(set(before) & set(after)):
        old, new = before[ticker], after[ticker]
        if old.get("tier") != new.get("tier"):
            add(
                ticker,
                "档位变化",
                old.get("tier_name", old.get("tier")),
                new.get("tier_name", new.get("tier")),
                "人工覆盖" if new.get("source") == "人工" else "市值变化",
            )
        elif old.get("auto_tier") != new.get("auto_tier"):
            add(
                ticker,
                "自动档位变化",
                old.get("auto_tier"),
                new.get("auto_tier"),
                "最终档位未变（人工覆盖或临界调整）",
            )

        if old.get("price") is not None and new.get("price") is None:
            add(ticker, "缺报价", old.get("price"), "", "本次无可用收盘价")
        old_change = old.get("change_pct")
        new_change = new.get("change_pct")
        if (
            new_change is not None
            and abs(new_change) >= PRICE_ALERT_PCT
            and (old_change is None or abs(old_change) < PRICE_ALERT_PCT)
        ):
            add(
                ticker, "价格异动", old_change, f"{new_change:+.2f}%",
                f"当日涨跌幅跨入 ±{PRICE_ALERT_PCT:g}%",
            )

        trigger = TRIGGER_DRAWDOWN.get(new.get("tier", 3))
        old_dd = old.get("drawdown_52w_pct")
        new_dd = new.get("drawdown_52w_pct")
        if (
            trigger is not None
            and new_dd is not None
            and old_dd is not None
            and old_dd > -trigger
            and new_dd <= -trigger
        ):
            add(
                ticker,
                "触发研究",
                f"{old_dd:.2f}%",
                f"{new_dd:.2f}%",
                f"{new['tier_name']}档回撤 ≥{trigger:g}%",
            )

    order = {kind: index for index, kind in enumerate(
        ["档位变化", "自动档位变化", "触发研究", "缺报价", "价格异动", "新进覆盖", "移出覆盖"]
    )}
    changes.sort(key=lambda item: (order.get(item["kind"], 99), item["ticker"]))
    return changes


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------

_HEADER_FILL = PatternFill("solid", fgColor="1F2937")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_TIER_FILLS = {
    1: PatternFill("solid", fgColor="FFF2CC"),
    2: PatternFill("solid", fgColor="E2EFDA"),
    3: PatternFill("solid", fgColor="F2F2F2"),
}
_MONEY = "#,##0"
_PRICE = "#,##0.00"
_PCT = "0.00"


def _header(ws: Worksheet, headers: list[str], widths: list[int] | None = None) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 28
    for index, width in enumerate(widths or [], start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def _definition_sheet(wb: Workbook, layers: list[dict]) -> None:
    ws = wb.active
    ws.title = "漏斗定义"
    _header(
        ws,
        ["档位", "定位", "自动分档（层内市值）", "研究深度", "更新频率", "价格触发带", "对应动作"],
        [14, 22, 24, 52, 20, 46, 34],
    )
    positions = {1: "层内不可替代 / 生态核心", 2: "层内重要参与者", 3: "层内其余公司"}
    shares = {1: "前 20%（至少 1 家）", 2: "20%–50%", 3: "后 50%"}
    for tier, name in TIER_NAMES.items():
        ws.append(
            [
                f"T{tier} {name}",
                positions[tier],
                shares[tier],
                RESEARCH_DEPTH[tier],
                UPDATE_CADENCE[tier],
                TRIGGER_ACTION[tier],
                TIER_ACTION[tier],
            ]
        )
        for cell in ws[ws.max_row]:
            if cell.column == 1:
                cell.fill = _TIER_FILLS[tier]

    ws.append([])
    notes = [
        ("自动规则", "层内市值降序：前20%→T1，20%–50%→T2，其余→T3；缺市值排最后。"),
        ("人工覆盖", "config/funnel_overrides.json 中的 tier 优先于自动档位；note 记录原因。"),
        ("股价区间", "展示当前价、52 周高/低（由回撤与低点涨幅反推）、回撤%、52 周分位%。"),
        ("边界", "档位只决定覆盖深度，不构成买入授权；买入仍须过四层筛选 Layer 2–4。"),
        ("数据来源", "ai_companies.json（universe）+ generated/quotes.json（价格/市值）。"),
    ]
    for label, text in notes:
        ws.append([label, text])
        ws.merge_cells(start_row=ws.max_row, start_column=2, end_row=ws.max_row, end_column=7)
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        ws.cell(row=ws.max_row, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    ws.append([])
    ws.append(["产业链层", "层摘要"])
    ws.merge_cells(start_row=ws.max_row, start_column=2, end_row=ws.max_row, end_column=7)
    for cell in ws[ws.max_row]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
    for layer in layers:
        ws.append([layer["name"], layer.get("summary", "")])
        ws.merge_cells(start_row=ws.max_row, start_column=2, end_row=ws.max_row, end_column=7)
        ws.cell(row=ws.max_row, column=2).alignment = Alignment(wrap_text=True, vertical="top")


def _summary_sheet(wb: Workbook, summary: list[dict[str, Any]]) -> None:
    ws = wb.create_sheet("分层汇总")
    _header(
        ws,
        [
            "产业链层", "T1 核心", "T2 重要", "T3 观察", "合计",
            "层股价区间", "层中位市值($M)",
            "T1 价格区间", "T2 价格区间", "T3 价格区间",
            "T1 代表", "T2 代表",
        ],
        [18, 9, 9, 9, 8, 26, 18, 26, 26, 26, 24, 30],
    )
    for entry in summary:
        ws.append(
            [
                entry["layer_name"], entry["t1_count"], entry["t2_count"], entry["t3_count"],
                entry["total"], entry["price_range"],
                (entry["median_market_cap"] or 0) / 1e6 if entry["median_market_cap"] else None,
                entry["t1_prices"], entry["t2_prices"], entry["t3_prices"],
                entry["t1_leaders"], entry["t2_leaders"],
            ]
        )
        row = ws.max_row
        ws.cell(row=row, column=7).number_format = _MONEY
    ws.append([])
    ws.append(["合计", sum(e["t1_count"] for e in summary), sum(e["t2_count"] for e in summary),
               sum(e["t3_count"] for e in summary), sum(e["total"] for e in summary)])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)


def _companies_sheet(wb: Workbook, rows: list[dict[str, Any]]) -> None:
    ws = wb.create_sheet("公司表")
    headers = [
        "产业链层", "档位", "代码", "公司", "细分环节", "档位来源", "备注",
        "市值($M)", "价格($)", "日涨跌%", "52周回撤%", "52周分位%",
        "52周高($)", "52周低($)", "PE", "Forward PE", "研究深度", "更新频率",
    ]
    _header(ws, headers, [18, 8, 9, 26, 22, 10, 22, 14, 11, 10, 12, 12, 12, 12, 9, 12, 46, 18])
    for row in rows:
        ws.append(
            [
                row["layer_name"], f"T{row['tier']} {row['tier_name']}", row["ticker"],
                row["name"], row["segment"], row["source"], row["note"],
                (row["market_cap"] / 1e6) if row["market_cap"] else None,
                row["price"], row["change_pct"], row["drawdown_52w_pct"],
                row["position_52w_pct"], row["high_52w"], row["low_52w"],
                row["pe"], row["forward_pe"], RESEARCH_DEPTH[row["tier"]],
                UPDATE_CADENCE[row["tier"]],
            ]
        )
        excel_row = ws.max_row
        ws.cell(row=excel_row, column=2).fill = _TIER_FILLS[row["tier"]]
        ws.cell(row=excel_row, column=8).number_format = _MONEY
        for column in (9, 13, 14, 15, 16):
            ws.cell(row=excel_row, column=column).number_format = _PRICE
        for column in (10, 11, 12):
            ws.cell(row=excel_row, column=column).number_format = _PCT
    ws.auto_filter.ref = f"A1:R{ws.max_row}"


def _overrides_sheet(
    wb: Workbook, overrides: dict[str, dict[str, Any]], rows: list[dict[str, Any]]
) -> None:
    ws = wb.create_sheet("人工覆盖")
    ws.column_dimensions["A"].width = 100
    instruction = '改 config/funnel_overrides.json，格式 "TICKER": {"tier":1|2|3,"note":"原因"}'
    ws["A1"] = instruction
    ws["A1"].font = Font(bold=True)
    ws.append([])
    headers = ["代码", "产业链层", "公司", "自动档位", "最终档位", "说明"]
    widths = [10, 18, 28, 10, 10, 40]
    _header(ws, headers, widths)
    by_ticker = {row["ticker"]: row for row in rows}
    for ticker in sorted(overrides):
        row = by_ticker.get(ticker, {})
        ws.append(
            [
                ticker, row.get("layer_name", ""), row.get("name", ""),
                f"T{row.get('auto_tier', '')}", f"T{overrides[ticker]['tier']}",
                overrides[ticker]["note"],
            ]
        )
    if not overrides:
        ws.append(["（当前无人工覆盖，全部使用自动档位）"])


def _changes_sheet(wb: Workbook, changes: list[dict[str, Any]]) -> None:
    ws = wb.create_sheet("每日变化")
    _header(ws, ["日期", "代码", "产业链层", "变化类型", "变化前", "变化后", "说明"],
            [12, 10, 18, 14, 14, 14, 40])
    for change in changes:
        ws.append([
            change["date"], change["ticker"], change["layer"], change["kind"],
            str(change["before"]), str(change["after"]), change["note"],
        ])
    if not changes:
        ws.append(["（本次无变化）"])


def write_excel(
    rows: list[dict[str, Any]],
    summary: list[dict[str, Any]],
    changes: list[dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
    layers: list[dict],
    path: Path | str = XLSX_PATH,
) -> Path:
    """Write the five-sheet workbook and return its path."""

    wb = Workbook()
    _definition_sheet(wb, layers)
    _summary_sheet(wb, summary)
    _companies_sheet(wb, rows)
    _overrides_sheet(wb, overrides, rows)
    _changes_sheet(wb, changes)
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    wb.save(resolved)
    return resolved


def write_daily_csv(changes: list[dict[str, Any]], path: Path | str = DAILY_CSV_PATH) -> Path:
    """Append-friendly daily change log; Excel opens the BOM-prefixed file cleanly."""

    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["date", "ticker", "layer", "kind", "before", "after", "note"]
        )
        writer.writeheader()
        writer.writerows(changes)
    return resolved


def quote_age_days(generated_at: str | None) -> float | None:
    """Age of the quote snapshot in days, or ``None`` when unparseable."""

    if not generated_at:
        return None
    try:
        stamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 86400


def build_payload(
    companies: list[dict],
    layers: list[dict],
    quotes: dict[str, dict[str, Any]],
    quotes_generated_at: str | None,
    overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the machine snapshot written to data/generated/funnel.json."""

    rows = build_rows(companies, layers, quotes, overrides)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "quotes_generated_at": quotes_generated_at,
        "source": "data/ai_companies.json + data/generated/quotes.json",
        "rules": {
            "tier_cutoffs": ["top 20% by market cap", "next 30%", "bottom 50%"],
            "trigger_drawdown_pct": TRIGGER_DRAWDOWN,
            "manual_overrides": str(OVERRIDES_PATH),
        },
        "stats": {
            "companies": len(rows),
            "layers": len(layers),
            "t1": sum(row["tier"] == 1 for row in rows),
            "t2": sum(row["tier"] == 2 for row in rows),
            "t3": sum(row["tier"] == 3 for row in rows),
            "manual": sum(row["source"] == "人工" for row in rows),
            "missing_price": sum(row["price"] is None for row in rows),
        },
        "summary": summarize(rows, layers),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Auto-tier the AI value chain into per-layer three-tier funnels."
    )
    parser.add_argument("--overrides", type=Path, default=OVERRIDES_PATH)
    parser.add_argument("--out", type=Path, default=FUNNEL_PATH, help="output JSON snapshot")
    parser.add_argument("--xlsx", type=Path, default=XLSX_PATH, help="output workbook")
    parser.add_argument("--no-xlsx", action="store_true", help="skip the workbook")
    parser.add_argument("--check", action="store_true", help="alert only; non-zero on stale data")
    parser.add_argument(
        "--max-age-days",
        type=float,
        default=DEFAULT_MAX_QUOTE_AGE_DAYS,
        help="quote snapshot older than this fails --check",
    )
    args = parser.parse_args(argv)

    companies, layers = load_universe()
    overrides = load_overrides(args.overrides)
    quotes_payload = json.loads(QUOTES_PATH.read_text()) if QUOTES_PATH.exists() else {}
    quotes = quotes_payload.get("quotes", {})
    quotes_generated_at = quotes_payload.get("generated_at")

    previous_rows: list[dict[str, Any]] | None = None
    if args.out.exists():
        try:
            previous_rows = json.loads(args.out.read_text()).get("rows")
        except (OSError, json.JSONDecodeError):
            previous_rows = None

    payload = build_payload(companies, layers, quotes, quotes_generated_at, overrides)
    changes = detect_changes(previous_rows, payload["rows"])
    excel_path = None
    if not args.check and not args.no_xlsx:
        excel_path = write_excel(
            payload["rows"], payload["summary"], changes, overrides, layers, args.xlsx
        )
    if not args.check:
        write_json_artifact(args.out, payload)
        write_daily_csv(changes)

    stats = payload["stats"]
    age = quote_age_days(quotes_generated_at)
    print(
        f"funnel: {stats['companies']} companies · "
        f"T1 {stats['t1']} / T2 {stats['t2']} / T3 {stats['t3']} · "
        f"{stats['manual']} manual override(s)"
    )
    print(
        f"quotes: {quotes_generated_at or 'missing'}"
        + (f" · {age:.1f} day(s) old" if age is not None else "")
    )
    if changes:
        counts: dict[str, int] = defaultdict(int)
        for change in changes:
            counts[change["kind"]] += 1
        print("changes: " + " · ".join(f"{kind} {count}" for kind, count in counts.items()))
        for change in changes[:15]:
            print(
                f"  {change['kind']:<6} {change['ticker']:<6} "
                f"{change['before']} → {change['after']}  {change['note']}"
            )
        if len(changes) > 15:
            print(f"  … {len(changes) - 15} more in {DAILY_CSV_PATH}")
    else:
        print("changes: none")
    if excel_path:
        print(f"wrote {excel_path}")
    if not args.check:
        print(f"wrote {args.out}")

    if args.check:
        stale = age is None or age > args.max_age_days
        if stale:
            print(
                f"  ! quote snapshot is stale (limit {args.max_age_days:g} days) — "
                "run: uv run python -m fdc.quotes",
                file=sys.stderr,
            )
        if stats["missing_price"]:
            print(
                f"  ! {stats['missing_price']} company(ies) have no usable price",
                file=sys.stderr,
            )
        if stale or stats["missing_price"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
