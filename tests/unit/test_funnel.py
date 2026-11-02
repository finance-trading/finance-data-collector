"""Per-layer funnel tiers, 52-week position math, manual overrides, and diffs."""

from __future__ import annotations

import json

import pytest
from openpyxl import load_workbook

from fdc.funnel import (
    auto_tier_map,
    build_payload,
    build_rows,
    detect_changes,
    load_overrides,
    remove_override,
    summarize,
    upsert_override,
    write_excel,
)


def _company(ticker: str, layer: str = "silicon", segment: str = "Compute") -> dict:
    return {
        "ticker": ticker,
        "name": ticker.title(),
        "layer": layer,
        "segment": segment,
        "description": "",
    }


LAYERS = [
    {"id": "power", "name": "能源与电力", "summary": "", "segments": ["Grid"]},
    {"id": "silicon", "name": "芯片与半导体", "summary": "", "segments": ["Compute"]},
]


def _quotes(**caps: int) -> dict[str, dict]:
    return {ticker: {"price": 100.0, "market_cap": cap} for ticker, cap in caps.items()}


def test_auto_tiers_rank_inside_each_layer_and_keep_one_t1():
    companies = [
        _company("A", "power"),
        _company("B", "power"),
        *[_company(f"S{index}", "silicon") for index in range(10)],
    ]
    quotes = _quotes(
        A=1_000, B=500,
        S0=1_000, S1=900, S2=800, S3=700, S4=600,
        S5=500, S6=400, S7=300, S8=200, S9=100,
    )

    tiers = auto_tier_map(companies, quotes)

    # 2 companies -> 1 T1 + 1 T2; 10 companies -> T1 top 2, T2 next 3, T3 rest.
    assert tiers["A"] == 1
    assert tiers["B"] == 2
    assert [tiers[f"S{index}"] for index in range(10)] == [1, 1, 2, 2, 2, 3, 3, 3, 3, 3]


def test_missing_market_cap_sorts_last_and_ticker_breaks_ties():
    companies = [_company("AAA"), _company("BBB"), _company("CCC")]
    quotes = {"AAA": {"market_cap": 100}, "CCC": {"market_cap": 100}}

    tiers = auto_tier_map(companies, quotes)

    assert tiers["AAA"] == 1
    assert tiers["CCC"] == 2
    assert tiers["BBB"] == 3


def test_manual_override_wins_and_is_marked():
    companies = [_company("BIG"), _company("MID"), _company("SMALL")]
    quotes = _quotes(BIG=1_000, MID=500, SMALL=1)
    overrides = {"SMALL": {"tier": 1, "note": "生态不可替代"}}

    rows = build_rows(companies, LAYERS, quotes, overrides)
    by_ticker = {row["ticker"]: row for row in rows}

    assert by_ticker["SMALL"]["auto_tier"] == 3
    assert by_ticker["SMALL"]["tier"] == 1
    assert by_ticker["SMALL"]["source"] == "人工"
    assert by_ticker["SMALL"]["note"] == "生态不可替代"
    assert by_ticker["BIG"]["source"] == "自动"


def test_quote_metrics_reconstructs_52_week_range():
    from fdc.funnel import _quote_metrics

    metrics = _quote_metrics({"price": 100.0, "change_52w_pct": -20.0, "rise_52w_pct": 25.0})

    assert metrics["high_52w"] == 125.0
    assert metrics["low_52w"] == 80.0
    assert metrics["position_52w_pct"] == 44.4


def test_degenerate_52_week_range_has_no_position():
    from fdc.funnel import _quote_metrics

    metrics = _quote_metrics({"price": 100.0, "change_52w_pct": 0.0, "rise_52w_pct": 0.0})

    assert metrics["position_52w_pct"] is None


def test_load_overrides_skips_notes_and_rejects_bad_tier(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"_说明": "ignored", "nvda": {"tier": 1, "note": "core"}}))
    assert load_overrides(path) == {"NVDA": {"tier": 1, "note": "core"}}

    path.write_text(json.dumps({"NVDA": {"tier": 9}}))
    with pytest.raises(ValueError):
        load_overrides(path)


def test_detect_changes_reports_tier_trigger_and_price_move():
    previous = [{
        "ticker": "NVDA", "name": "Nvidia", "layer": "silicon", "layer_name": "芯片与半导体",
        "tier": 2, "tier_name": "重要", "auto_tier": 2, "source": "自动",
        "price": 100.0, "change_pct": 1.0, "drawdown_52w_pct": -10.0,
    }]
    current = [{
        "ticker": "NVDA", "name": "Nvidia", "layer": "silicon", "layer_name": "芯片与半导体",
        "tier": 1, "tier_name": "核心", "auto_tier": 1, "source": "自动",
        "price": 90.0, "change_pct": -6.0, "drawdown_52w_pct": -26.0,
    }]

    changes = detect_changes(previous, current)
    kinds = {change["kind"] for change in changes}

    assert {"档位变化", "触发研究", "价格异动"} <= kinds


def test_first_run_has_no_changes():
    rows = build_rows([_company("AAA")], LAYERS, _quotes(AAA=100), {})
    assert detect_changes(None, rows) == []


def test_payload_and_excel_export(tmp_path):
    companies = [_company("BIG"), _company("SMALL")]
    quotes = _quotes(BIG=1_000, SMALL=100)
    payload = build_payload(companies, LAYERS, quotes, "2026-10-30T00:00:00+00:00", {})

    assert payload["stats"] == {
        "companies": 2, "layers": 2, "t1": 1, "t2": 1, "t3": 0, "manual": 0, "missing_price": 0,
    }
    assert len(payload["summary"]) == 2

    path = write_excel(
        payload["rows"], summarize(payload["rows"], LAYERS), [], {}, LAYERS,
        tmp_path / "funnel.xlsx",
    )
    wb = load_workbook(path)
    assert wb.sheetnames == ["漏斗定义", "分层汇总", "公司表", "人工覆盖", "每日变化"]
    assert wb["公司表"].max_row == 3


def test_upsert_and_remove_override_preserve_doc_key(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"_说明": "keep me", "CDNS": {"tier": 1, "note": "EDA"}}))

    upsert_override("ALAB", 1, "optical", path=path)
    raw = json.loads(path.read_text())
    assert raw["_说明"] == "keep me"            # doc key survives a write
    assert raw["ALAB"] == {"tier": 1, "note": "optical"}
    assert load_overrides(path)["ALAB"]["tier"] == 1

    upsert_override("alab", 2, "", path=path)   # ticker is case-insensitive
    assert json.loads(path.read_text())["ALAB"]["tier"] == 2

    assert remove_override("ALAB", path=path) is True
    raw = json.loads(path.read_text())
    assert "ALAB" not in raw and raw["_说明"] == "keep me"
    assert remove_override("ALAB", path=path) is False


def test_override_write_refuses_invalid_existing_file(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text("{broken json")

    with pytest.raises(json.JSONDecodeError):
        upsert_override("AMD", 2, "reason", path=path)
    assert path.read_text() == "{broken json"
