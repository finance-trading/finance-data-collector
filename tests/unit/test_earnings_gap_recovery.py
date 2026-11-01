from __future__ import annotations

import pandas as pd
import pytest

from scripts.earnings_gap_recovery import (
    calculate_snapshot,
    event_window_metrics,
    parse_spy_holdings,
    summarize_metrics,
    total_return_from_adjusted_open,
)


def test_recovery_uses_close_only_and_strictly_exceeds_target() -> None:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-02-02"])
    prices = pd.DataFrame(
        {
            "Open": [90.0, 105.0, 100.0],
            "High": [110.0, 120.0, 130.0],
            "Close": [90.0, 99.0, 99.0],
        },
        index=dates,
    )

    metrics = event_window_metrics(
        prices,
        reaction_date=pd.Timestamp("2024-01-02"),
        target_close=100.0,
        max_months=1,
        cutoff=pd.Timestamp("2024-03-01"),
    )

    assert metrics[1].observed is True
    assert metrics[1].recovered is False
    assert metrics[1].max_close == 99.0
    assert metrics[1].excess == pytest.approx(-0.01)


def test_fixed_horizon_x_uses_last_close_at_calendar_month_boundary() -> None:
    dates = pd.to_datetime(
        ["2024-01-02", "2024-01-03", "2024-01-31", "2024-02-02"]
    )
    prices = pd.DataFrame(
        {"Close": [90.0, 130.0, 95.0, 98.0]},
        index=dates,
    )

    metric = event_window_metrics(
        prices,
        reaction_date=pd.Timestamp("2024-01-02"),
        target_close=100.0,
        max_months=1,
        cutoff=pd.Timestamp("2024-03-01"),
    )[1]

    assert metric.max_close == 130.0
    assert metric.fixed_close == 98.0
    assert metric.fixed_excess == pytest.approx(-0.02)


def test_fixed_horizon_uses_previous_trading_close_when_boundary_is_non_trading() -> None:
    dates = pd.to_datetime(["2024-01-02", "2024-02-01", "2024-02-05"])
    prices = pd.DataFrame({"Close": [90.0, 101.0, 120.0]}, index=dates)

    metric = event_window_metrics(
        prices,
        reaction_date=pd.Timestamp("2024-01-02"),
        target_close=100.0,
        max_months=1,
        cutoff=pd.Timestamp("2024-03-01"),
    )[1]

    assert metric.fixed_date == pd.Timestamp("2024-02-01")
    assert metric.fixed_close == 101.0
    assert metric.fixed_excess == pytest.approx(0.01)


def test_window_metrics_capture_recovery_time_terminal_state_and_risk_path() -> None:
    dates = pd.to_datetime(
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-02-02"]
    )
    prices = pd.DataFrame(
        {"Close": [90.0, 95.0, 102.0, 80.0, 105.0, 103.0]},
        index=dates,
    )

    metric = event_window_metrics(
        prices,
        reaction_date=pd.Timestamp("2024-01-02"),
        target_close=100.0,
        max_months=1,
        cutoff=pd.Timestamp("2024-03-01"),
    )[1]

    assert metric.recovery_trading_days == 2
    assert metric.terminal_close == 103.0
    assert metric.terminal_excess == pytest.approx(0.03)
    assert metric.max_drawdown_pct == pytest.approx((80.0 / 102.0 - 1.0) * 100.0)
    assert metric.pre_recovery_min_close == 90.0
    assert metric.pre_recovery_min_excess_pct == pytest.approx(-10.0)


def test_calculate_snapshot_writes_extended_monthly_summary(tmp_path) -> None:
    pd.DataFrame({"ticker": ["ABC"], "name": ["Example"]}).to_csv(
        tmp_path / "universe.csv", index=False
    )
    pd.DataFrame(
        {
            "ticker": ["ABC"],
            "earnings_datetime_utc": ["2024-01-02T12:00:00+00:00"],
        }
    ).to_csv(tmp_path / "earnings_events.csv", index=False)
    pd.DataFrame(
        {
            "ticker": ["ABC"] * 7,
            "date": pd.to_datetime(
                [
                    "2024-01-01",
                    "2024-01-02",
                    "2024-01-03",
                    "2024-01-04",
                    "2024-01-05",
                    "2024-01-08",
                    "2024-02-02",
                ]
            ),
            "Open": [100.0, 90.0, 95.0, 102.0, 80.0, 105.0, 103.0],
                "Close": [100.0, 90.0, 95.0, 102.0, 80.0, 105.0, 103.0],
                "Adj Close": [100.0, 90.0, 95.0, 102.0, 80.0, 105.0, 103.0],
            }
        ).to_csv(tmp_path / "prices.csv.gz", index=False, compression="gzip")
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-03", "2024-02-02"]),
            "Open": [100.0, 110.0],
            "Close": [100.0, 110.0],
            "Adj Close": [100.0, 110.0],
        }
    ).to_csv(tmp_path / "benchmark_prices.csv", index=False)

    calculate_snapshot(
        data_dir=tmp_path,
        cutoff=pd.Timestamp("2024-03-01"),
    )

    summary = pd.read_csv(tmp_path / "monthly_summary.csv")
    month_one = summary.loc[summary["month"] == 1].iloc[0]
    assert month_one["terminal_recovery_rate_pct"] == 100.0
    assert month_one["terminal_excess_p10_pct"] == pytest.approx(3.0)
    assert month_one["terminal_positive_count"] == 1
    assert month_one["terminal_non_positive_count"] == 0
    assert month_one["terminal_positive_0_5_count"] == 1
    assert month_one["terminal_worst_decile_average_pct"] == pytest.approx(3.0)
    assert month_one["actual_return_observed"] == 1
    assert month_one["actual_return_average_pct"] == pytest.approx(8.4210526)
    assert month_one["relative_return_average_pct"] == pytest.approx(-1.5789474)
    assert month_one["recovery_trading_days_median"] == 2.0
    assert month_one["excess_p25_pct"] == pytest.approx(3.0)
    assert month_one["x_h_average_pct"] == pytest.approx(3.0)
    assert month_one["positive_x_h_count"] == 1
    assert month_one["negative_0_5_gap_count"] == 0
    assert month_one["max_drawdown_median_pct"] == pytest.approx((80.0 / 102.0 - 1.0) * 100.0)


def test_summary_excludes_right_censored_events_per_horizon() -> None:
    metrics = {
        1: [(-0.01, True), (0.10, True), (None, False)],
        2: [(0.10, True), (None, False)],
    }

    summary = summarize_metrics(metrics)

    assert summary[1].recovered == 1
    assert summary[1].observed == 2
    assert summary[1].rate == 50.0
    assert summary[1].average_excess == pytest.approx(4.5)
    assert summary[1].median_excess == pytest.approx(4.5)
    assert summary[2].recovered == 1
    assert summary[2].observed == 1
    assert summary[2].rate == 100.0


def test_parse_spy_holdings_keeps_equity_tickers_and_excludes_residual_rows(tmp_path) -> None:
    holdings = pd.DataFrame(
        {
            "Name": ["NVIDIA CORP", "US DOLLAR", "TPG INC", "BROWN-FORMAN CORP CLASS B"],
            "Ticker": ["NVDA", "-", "2602335D", "BF.B"],
            "Identifier": ["67066G104", "999USDZ92", "436CVR021", "115637209"],
            "Weight": [8.1, 0.2, 0.000003, 0.1],
        }
    )
    path = tmp_path / "spy.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(
            [
                ["Fund Name: State Street SPY"],
                ["Ticker Symbol: SPY"],
                ["Holdings: As of 25-Sep-2026"],
                [],
            ]
        ).to_excel(
            writer, sheet_name="holdings", index=False, header=False
        )
        holdings.to_excel(writer, sheet_name="holdings", index=False, startrow=4)

    parsed = parse_spy_holdings(path)

    assert parsed.to_dict("records") == [
        {"ticker": "NVDA", "name": "NVIDIA CORP"},
        {"ticker": "BF.B", "name": "BROWN-FORMAN CORP CLASS B"},
    ]


def test_total_return_from_adjusted_open_uses_dividend_adjusted_open() -> None:
    prices = pd.DataFrame(
        {
            "Open": [100.0, 110.0],
            "Close": [105.0, 120.0],
            "Adj Close": [100.0, 114.0],
        },
        index=pd.to_datetime(["2024-01-03", "2024-02-02"]),
    )

    result = total_return_from_adjusted_open(
        prices,
        buy_date=pd.Timestamp("2024-01-03"),
        terminal_date=pd.Timestamp("2024-02-02"),
    )

    assert result == pytest.approx(0.197)
