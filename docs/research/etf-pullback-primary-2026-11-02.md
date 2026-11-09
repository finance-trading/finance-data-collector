# 下跌后的美股 ETF 候选：一手资料快照（2026-11-02 PST）

研究范围：SMH、SOXX、QQQ；VOO 作全市场基线。价格截至最近完整交易日 **2026-10-30**，未把 11 月 2 日尚未开始的交易写入。下表回撤为 Nasdaq 日线在 2025-10-30 至 2026-10-30 的**最高收盘价**至 10 月 30 日收盘价的简单价格变化，未计股息，也不是相对基金净值或内在价值的折价。行情网址将 [SMH](https://api.nasdaq.com/api/quote/SMH/historical?assetclass=etf&limit=300&fromdate=2025-10-30&todate=2026-11-01) 中的代码替换为其余 ETF；本轮直接读取四条 Nasdaq 响应，均有 252 个交易日。

| ETF | 10/30 收盘，美元/份 | 区间最高收盘及日期 | 价格回撤 | 发行人已核产品事实 | 发行人资料状态 |
|---|---:|---|---:|---|---|
| **SMH** | **$522.49** | $668.91，2026-06-22 | **−21.89%** | VanEck 半导体 ETF，追踪 MVIS US Listed Semiconductor 25 Index；年总费用率 **0.35%**；10/30 NAV **$522.76**。 | [VanEck 基金页](https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/)和[官方持仓 XLSX](https://www.vaneck.com/us/en/etf/equity/smh/holdings/download/xlsx/)可读。持仓截至 **10/29**：25 只股票，前十大 **68.05%**，NVDA **19.62%** + TSM **9.48%**；逐项见[SMH 底稿](smh-primary-facts-2026-11-01.md)。 |
| **SOXX** | **$471.51** | $655.01，2026-06-22 | **−28.01%** | **[UNAVAILABLE]**：本轮未从发行人直接核到当前费用、基准、NAV 或持仓。 | [iShares 产品页](https://www.ishares.com/us/products/239705/ishares-phlx-semiconductor-etf)及其官方 CSV、BlackRock PDF 在本轮均返回 **403**；只保留 Nasdaq 价格事实，不凭印象补写基金结构。 |
| **QQQ** | **$690.49** | $759.66，2026-10-06 | **−9.11%** | Invesco 官方页称其追踪 **Nasdaq-100 Index**，提供 Nasdaq 上市的 100 家最大非金融公司敞口。 | [Invesco QQQ 页](https://www.invesco.com/qqq-etf/en/about.html)正文可读，但动态费用和持仓显示“Unable to load data”；本轮费用、当前持仓权重、NAV **[UNAVAILABLE]**。 |
| **VOO** | **$694.81** | $716.20，2026-10-06 | **−2.99%** | Vanguard 页面内产品资料给出基准 **S&P 500 Index**、费用率 **0.03%**（费用日期 2026-04-28）、10/30 NAV **$694.53**。 | [Vanguard VOO 页](https://investor.vanguard.com/investment-products/etfs/profile/voo)可读取产品资料；当前前十大持仓及权重本轮 **[UNAVAILABLE]**。 |

**比较边界：** SOXX 的较大跌幅只说明价格变化，不能在未核费用与持仓时推断它比 SMH 更分散或更便宜。SMH 与 SOXX 都聚焦半导体，QQQ 更广但仍偏大型科技，VOO 是最广的美股大盘基线；后两项产品定位依据各发行人的跟踪基准，不构成彼此未来收益/风险的量化估计。若要形成实盘建仓优先级，应在 SOXX/iShares 访问恢复后补当期持仓和费用，并按拟持仓份额计算与 NVDA、TSM 等个股的穿透重叠。
