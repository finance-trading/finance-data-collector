# AI 产业链回撤后的投资研究优先级（2026-11-01 PDT）

> 本页只比较 AI 产业链候选及 SMH。零持仓、跨行业股票和 ETF 的入场机会筛查见[2026-11-02 扩展研究](market-pullback-entry-screen-2026-11-02.md)；本页的 SMH 第一名不适用于扩展范围。

**结论：若按 3–5 年、适中风险、尚无半导体重仓来比较，建仓工具的研究优先级为 SMH → TSM → NVDA；GOOGL 是最值得另行核查的事件型错价候选。** SMH 优先是因为它分散了单一公司风险，不代表它比 TSM/NVDA 更便宜。所有标的目前均为 `WATCH`，不是 `BUY_CANDIDATE`。现有组合、可承受亏损及买入资金未知，不给仓位或价格指令。

## 范围和时点

项目的 [`data/ai_companies.json`](../../data/ai_companies.json) 有 234 家、6 层公司；[漏斗规则](../strategy/ai-chain-company-funnel-v0.md)按层内市值决定覆盖深度，价格触发只启动研究。本页在此前已有一手经营底稿的 NVDA、TSM、ASML、ANET、VRT、MSFT、GOOGL、AMZN、PLTR、AMD 中排序，同时检查 META、ORCL 的回撤与已有质量边界；另将 SMH 作为半导体组合工具比较。**不是对 234 家逐一完成基本面和估值复核**。10 月 30 日是 11 月 1 日之前最近交易日。个股价格采用 [Nasdaq 历史行情接口](https://api.nasdaq.com/api/quote/NVDA/historical?assetclass=stocks&limit=300&fromdate=2025-10-30&todate=2026-11-01)，逐证券替换 URL 中的 `NVDA`；SMH 使用[同一交易所 ETF 行情](https://api.nasdaq.com/api/quote/SMH/historical?assetclass=etf&limit=300&fromdate=2025-10-30&todate=2026-11-01)。回撤定义为当日收盘价 / 过去约一年最高**收盘价** − 1，和项目漏斗按盘中高点计算的 52 周回撤略有差别；ETF 价格回撤也不是相对净值的折价。个股市值来自本地 [`data/generated/quotes.json`](../../data/generated/quotes.json) 的 yfinance 快照，生成时间 2026-10-31 16:02 UTC；它仅用于下述粗略倍数，不是发行人数据。

| 股票 | 10/30 美元收盘 | 近一年最高收盘回撤 | 初步定位 |
|---|---:|---:|---|
| **SMH ETF** | **$522.49/份** | **−21.9%** | 无半导体重仓时优先研究的核心工具 |
| TSM（1 ADS = 5 普通股） | $406.13 | −16.4% | 单股综合优先研究 |
| NVDA | $204.64 | −14.5% | 高现金创造、单一利润池风险 |
| GOOGL | $279.84 | −30.5% | 事件型错价待核 |
| VRT | $232.50 | −38.2% | 高弹性、需核有机增长及订单 |
| ASML（Nasdaq 普通股） | $1,565.90 | −21.3% | 光刻质量高、现金流异常需正常化 |
| ANET | $168.86 | −22.1% | 网络候选，现金桥缺失 |
| MSFT | $521.91 | −4.0% | 质量候选，但此轮不算明显错价 |
| AMZN | $240.35 | −15.4% | AWS 强，建设期现金支出重 |
| PLTR | $184.11 | −11.9% | 高估值，非优先 |
| AMD | $504.80 | −22.3% | 竞争兑现及估值待证明 |

## 排序依据和否决点

1. **SMH：无半导体重仓时排第一，但仍是单一行业敞口。** [VanEck 2026-10-29 官方持仓](smh-primary-facts-2026-11-01.md)显示仅 25 只股票，前十大占 **68.05%**；NVDA **19.62%**、TSM **9.48%**，两者合计 **29.10%**，另含 AMD、AVGO、设备与存储公司。它降低单家公司选错的影响，却仍受同一轮 AI CapEx、半导体周期和估值收缩驱动；基金[总费用率](https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/) **0.35%/年**。10/30 收盘 $522.49 对同日官方 NAV **$522.76**，约 **−0.05%**，不存在明显 ETF 交易折价；−21.9% 是相对历史最高收盘价的跌幅，不能当安全边际。若已有 NVDA/TSM，增持 SMH 会重复加仓这些公司，不自动排第一。
2. **TSM：单股综合第一。** [2026 Q3 发行人 6-K](https://www.sec.gov/Archives/edgar/data/1046179/000104617926000726/a3q26e_withguidancexfinal.htm)披露季度收入 NT$1,494.243bn、同比 +50.9%，毛利率 66.4%；[演示稿](https://www.sec.gov/Archives/edgar/data/1046179/000104617926000726/a3q26presentatione.htm)披露季度 CFO NT$919.77bn、CapEx NT$443.21bn。先进制程和封装覆盖多家 AI 设计商，比单一 GPU 或应用的需求押注更分散。代价是高资本强度、台湾地缘风险、客户集中和 ADS/汇率桥；[原始输入底稿](ai-noncloud-valuation-raw-inputs-2026-10-18.md)仍缺完整最新净债务、租赁及同日汇率，所以**没有可信买入价或 Bear Case 损失**。
3. **NVDA：单股经营与已实现现金流优先，适合更能承受周期波动者。** [FY2027 Q2 业绩发布](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027)及[原始输入底稿](ai-noncloud-valuation-raw-inputs-2026-10-18.md)给出截至 2026-07-26 的 TTM 收入 $302.970bn、公司定义 FCF $126.886bn。以本次约 $4.941tn 市值机械相除，约 **39 倍历史 FCF**；这不是正常化收益倍数。若超高毛利率、客户 CapEx 或出口条件回落，历史现金流不可直线外推。14.5% 回撤本身不足以证明有安全边际。
4. **GOOGL：跌幅最大的一线平台候选，但先核资本回报。** [2026 Q3 发行人 8-K 附件](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000080/googexhibit991q32026.htm)披露季度收入 $127.577bn、同比 +25%；Google Cloud 收入 $30.709bn、同比 +103%，部门经营利润 $11.121bn；集团经营利润 $40.576bn、同比 +30%。同一附件给出 Q3 CFO $42.290bn、现金 PPE 购置 $51.355bn，单季 FCF **−$9.065bn**；TTM FCF **$19.747bn**。按约 $3.440tn 市值，历史 FCF 倍数约 **174 倍**，因为 AI CapEx 正在吞噬现金；不可把行情缓存显示的 GAAP `PE=14.61` 当作便宜证据，2026 年 9M 非经营投资收益 $127.478bn 严重抬高净利。同一报告还披露 Q3 普通股增发净额 $12.371bn，以及 9M 强制转换优先股净融资 $19.063bn。10/28 收盘 $324.89、10/29 $283.82（[Nasdaq 同口径日线](https://api.nasdaq.com/api/quote/GOOGL/historical?assetclass=stocks&limit=20&fromdate=2026-10-20&todate=2026-11-01)），证明财报后出现大幅价格反应，**不证明市场错了**。先查资本支出何时转为可持续股东现金流、增发摊薄与新债务，才能上调排序。
5. **VRT：高增速观察，不升为第一。** [2026 Q3 SEC Company Facts](https://data.sec.gov/api/xbrl/companyfacts/CIK0001674101.json)及[更新底稿](ai-operating-primary-refresh-2026-11-01.md)给出收入 $4.3128bn、同比 +61.2%，GAAP 营业利润 $0.9838bn、同比 +90.4%。按 2025 年报与 2026/2025 前九个月机械拼接，TTM CFO − 现金 PP&E 约 $3.1472bn；约 $89.527bn 市值 / 该差额约 **28.4 倍**。此差额未扣融资租赁、收购代价和稀释；Q3 有机增长、订单/积压和更新指引本轮未核，不能把 38.2% 回撤自动视作便宜。

**暂缓其他标的。** [AMZN 2026 Q3 发布](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000038/amzn-20260930xex991.htm)披露 AWS 收入 $46.0bn、同比 +39%，但集团 TTM 公司定义 FCF 为 **−$42.4bn**，需先重估建设期投入与未来回收。ASML 的 [Q3 US GAAP 财表](https://www.sec.gov/Archives/edgar/data/937966/000162828026065813/financial_statementsxusx.htm)现金流受大额营运资本流入扭曲；ANET、AMD、PLTR 的现金、稀释与正常化估值桥仍不完整（见[一手筛查](ai-other-candidates-primary-screen-2026-10-18.md)）。MSFT 仅约 4% 回撤；PLTR/AMD 当前行情缓存的历史 PE 分别约 157/130 倍，直接用“AI 下跌”解释买点不足。ORCL 虽约 50% 回撤，[项目质量观察池](../strategy/core-quality-watchlist-v0.md)仍标记当前快速 FCF 门槛不通过，须单独核对云 CapEx 回收，不进入这次前三。

## 行动边界

对 **SMH** 先核组合内已有半导体敞口、基金最新持仓、前十大及单一公司权重，并给行业整体盈利/估值压力情景；若作为核心持仓，再单独买 TSM/NVDA 只能是有意的超配。对 **TSM 与 NVDA** 补同日证券/货币桥、最新净债务和租赁、正常化 FCF 与毛利率/资本强度 Bear Case；对 **GOOGL** 补 Q3 后 CapEx、融资与稀释的现金回收模型。项目[四层筛选规则](../strategy/four-layer-screening-rules-v0.md)的单股 `BUY_CANDIDATE` 需要事件前质量证据、具体下跌原因、事件后 Bear/Base/Bull、约 30% 的 Base upside、可承受的 Bear 损失及组合主题上限；ETF 不能机械套用单股质量门槛，但同样要核行业估值及组合风险。当前这些门槛未完成；本页的排序只决定下一步研究，不提供实盘买入授权。
