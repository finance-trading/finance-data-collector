# 135 只十年赢家：财报低开后的固定时点收盘统计

> 数据截止：2026-09-25；样本：筛选报告中的 135 只近十年总回报跑赢 S&P 500 的股票；合格低开事件：558 个；价格口径：拆股重述后的日收盘价。

## 统计口径

财报反应日为公告后首个反应交易日，事件门槛为该日开盘相对财报前一交易日收盘低开至少 5%。

设 `P_SEC` 为财报公布前、尚未反映公告的最后一个交易日收盘价。对 `H=1..12`，观察时点是反应日加 H 个日历月；若边界日不是交易日，取边界日前最近一个可用交易日收盘价 `C_H`。固定时点收益为：

`X_H = C_H / P_SEC - 1`

“固定时点超过”只表示 `C_H > P_SEC`。窗口内某一天曾经收盘超过 `P_SEC` 是另一条路径指标，不可替代固定时点结果。

## 结果摘要

| 月份 | 可观察事件 | 涉及公司 | 固定时点超过数/比例 | 全样本平均 X_H | 中位数 | P10/P90 | X_H>0 平均 | 未超过平均缺口 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 554 | 113 | 110 / 19.86% | -7.85% | -7.65% | -21.27% / 4.87% | 7.39% | 11.62% |
| 2 | 539 | 112 | 138 / 25.60% | -6.74% | -7.16% | -25.69% / 11.83% | 12.71% | 13.44% |
| 3 | 531 | 112 | 200 / 37.66% | -3.33% | -5.26% | -25.08% / 18.98% | 15.73% | 14.84% |
| 4 | 529 | 112 | 223 / 42.16% | -0.96% | -4.20% | -25.18% / 23.79% | 18.52% | 15.16% |
| 5 | 518 | 112 | 239 / 46.14% | 0.78% | -1.87% | -26.89% / 30.90% | 20.92% | 16.47% |
| 6 | 513 | 112 | 258 / 50.29% | 4.34% | 0.64% | -26.54% / 34.71% | 24.66% | 16.22% |
| 9 | 492 | 112 | 301 / 61.18% | 14.46% | 6.93% | -24.82% / 54.75% | 35.11% | 18.10% |
| 12 | 463 | 109 | 299 / 64.58% | 24.40% | 12.07% | -25.02% / 76.65% | 47.93% | 18.49% |

完整 1–12 月结果见 [`winners_135/monthly_summary.csv`](../../data/research/earnings_gap_recovery/winners_135/monthly_summary.csv)。

## `monthly_summary.csv` 字段说明

### 样本与分母

- `month`：观察期限，单位为日历月。
- `valid_events`、`valid_companies`：全部 558 个合格低开事件及其去重公司数。它们是该快照的固定样本规模。
- `observed_events`、`observed_companies`：已走完整个 H 月期限、且有有效收盘价的事件数和公司数。
- `observed`：`observed_events` 的兼容别名。
- `right_censored`：尚未走完整期限的右删失事件数，不当作失败。

### 固定时点 `X_H`

- `fixed_point_recovered`、`fixed_point_recovery_rate_pct`：在 H 月固定时点 `C_H>P_SEC` 的事件数和比例。
- `positive_x_h_count`、`positive_x_h_rate_pct`：`X_H>0` 的数量和比例，与上面固定时点超过口径一致。
- `x_h_average_pct`、`x_h_median_pct`：所有 observed 事件的 X_H 均值和中位数；负数表示整体仍低于 P_SEC。
- `x_h_p10_pct`、`x_h_p25_pct`、`x_h_p75_pct`、`x_h_p90_pct`：全样本 X_H 分位数。P10/P25 表示较差侧，P75/P90 表示较好侧。
- `positive_x_h_average_pct`、`positive_x_h_median_pct`、`positive_x_h_p10_pct`、`positive_x_h_p25_pct`、`positive_x_h_p75_pct`、`positive_x_h_p90_pct`：仅对 X_H>0 事件统计，展示成功超出的典型幅度和分散程度。
- `unrecovered_x_h_count`：固定时点仍未超过 P_SEC 的事件数。
- `unrecovered_x_h_average_gap_pct`、`unrecovered_x_h_median_gap_pct`：未超过事件距离 P_SEC 的平均和中位缺口，使用正数表示缺多少。
- `worst_decile_average_x_h_pct`：X_H 最差 10% 事件的平均表现，用于衡量少数坏结果的严重程度。

### 固定时点分布桶

- `positive_0_5_count`、`positive_5_10_count`、`positive_10_20_count`、`positive_20_plus_count`：X_H 正值事件分别落在 0–5%、5–10%、10–20%、20% 以上的数量。
- `negative_0_5_gap_count`、`negative_5_10_gap_count`、`negative_10_20_gap_count`、`negative_20_plus_gap_count`：X_H 为负的事件分别仍有 0–5%、5–10%、10–20%、20% 以上缺口的数量。边界按绝对缺口划分，0 不计入正值桶。

### 窗口路径：曾经恢复与最高收盘

- `recovered`、`recovery_rate_pct`：窗口内至少一天收盘超过 P_SEC 的事件数和比例；这是“曾经恢复”，不是固定时点站稳。
- `recovered_average_excess_pct`、`recovered_median_excess_pct`：曾经恢复事件的窗口最高收盘超额均值和中位数。
- `recovery_trading_days_median`、`recovery_trading_days_p25`、`recovery_trading_days_p75`：首次收盘恢复所需交易日的中位数及中间 50% 区间。
- `max_close_average_excess_pct`、`max_close_median_excess_pct`、`max_close_excess_p10_pct`、`max_close_excess_p25_pct`、`max_close_excess_p75_pct`、`max_close_excess_p90_pct`：窗口内最高收盘相对 P_SEC 的全样本分布。
- `max_close_trading_days_median`：达到窗口最高收盘所需交易日的中位数。
- `never_recovered_max_close_count`、`never_recovered_max_close_gap_pct`：窗口内从未收盘恢复事件数及其最高收盘距 P_SEC 的平均缺口。
- `excess_p10_pct`、`excess_p25_pct`、`excess_p75_pct`、`excess_p90_pct`：兼容字段，当前与固定时点 X_H 分位数一致；新分析应优先使用 `x_h_*` 或 `max_close_*` 的明确字段。

### 期末兼容字段

`terminal_*` 字段保留用于兼容旧报告：当前 `terminal_excess_*` 与固定时点 X_H 对应，`terminal_recovered` 与 `fixed_point_recovered` 对应；`terminal_positive_*`、`terminal_non_positive_*` 和相应四档桶也按固定时点 X_H 计算。新报告建议使用名称更明确的 `fixed_point_*`、`x_h_*`、`positive_x_h_*` 和 `negative_*_gap_count`。

### 实际收益、基准与风险路径

- `actual_return_*`：从反应日后下一交易日开盘到期限末的含现金分红调整收益；不是 X_H，也不是按 P_SEC 买入的收益。
- `benchmark_return_*`、`relative_return_*`：同期 SPY 及相对 SPY 的收益；若数据不可得则留空。
- `max_drawdown_average_pct`、`max_drawdown_median_pct`：窗口收盘路径最大回撤的均值和中位数。
- `pre_recovery_min_excess_median_pct`：首次恢复前最低收盘相对 P_SEC 的中位超额。

## 限制

这是先用完整近十年回报筛选出的赢家池，再回看低开事件，存在明显前视和幸存者偏差。事件等权，同一公司多次财报并非独立样本；Yahoo Finance 的事件时间和价格未逐条用发行人公告核验。结果描述历史价格路径，不构成买入授权。
