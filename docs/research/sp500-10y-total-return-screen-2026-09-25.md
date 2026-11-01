# 当前 S&P 500 成分证券：近十年总回报跑赢基准筛选

> 截止日期：2026-09-25（最近一个与成分股持仓文件一致的完整交易日）  
> 价格区间：2016-09-26 至 2026-09-25，共 3,651 个日历日（9.9961 年）  
> 口径：只比较含分红总回报，不使用财务质量、估值或其他指标。

## 结论

- 当前样本为 **503 个成分证券**（对应约 500 家公司；GOOG/GOOGL 等多类别股份分别计算）。
- **466 个**证券拥有通过完整性与身份检查的全区间数据；其中 **135 个**跑赢基准，**331 个**未跑赢；**37 个**标为 `UNAVAILABLE`。
- 本筛选使用同区间 S&P 500 Total Return Index（Yahoo 代码 `^SP500TR`）作为门槛：累计总回报 **325.85%**，年化总回报 **15.60%**。
- 入选比例为可比较证券的 **28.97%**，或当前 503 个证券的 **26.84%**。
- 前十名依次为 NVDA、AMD、MU、FIX、DELL、LRCX、ANET、STX、KLAC、AVGO。

机械筛选最初得到 467 个有首尾价格的证券和 136 个跑赢者；人工身份检查发现 `P` 已对应新证券 Everpure（持仓标识符 74624M102），而 Yahoo 的十年 `P` 序列存在旧代码历史归属风险，因此将其从第 48 名候选改列为 `UNAVAILABLE`。这个调整使最终可用数为 466、入选数为 135。

## 前十名速览

| 排名 | 代码 | 公司 | 10 年累计总回报 | 年化总回报 | 相对基准年化超额 |
|---:|---|---|---:|---:|---:|
| 1 | NVDA | Nvidia Corp | 14158.99% | 64.25% | 48.65 pp |
| 2 | AMD | Advanced Micro Devices | 9878.32% | 58.48% | 42.89 pp |
| 3 | MU | Micron Technology Inc | 6293.29% | 51.58% | 35.98 pp |
| 4 | FIX | Comfort Systems Usa Inc | 5922.92% | 50.68% | 35.08 pp |
| 5 | DELL | Dell Technologies  C | 4510.42% | 46.70% | 31.11 pp |
| 6 | LRCX | Lam Research Corp | 3839.58% | 44.41% | 28.82 pp |
| 7 | ANET | Arista Networks Inc | 3783.89% | 44.21% | 28.61 pp |
| 8 | STX | Seagate Technology Holdings | 3574.70% | 43.41% | 27.81 pp |
| 9 | KLAC | Kla Corp | 3090.25% | 41.40% | 25.80 pp |
| 10 | AVGO | Broadcom Inc | 2657.75% | 39.35% | 23.75 pp |

## 方法

1. **当前成分证券。** 读取 State Street 官方 SPY 每日持仓 XLSX（文件标注 `As of 25-Sep-2026`）。剔除现金/占位行 `-` 和极小的非标准残余行 `2602335D` 后，得到 503 个权益证券；并与可机器读取的 Wikipedia 当前成分表核对，503 个代码完全一致。由于 S&P 的完整成分导出需要许可，这里把 SPY 持仓作为第一方、可复核的当前指数代理，而不声称它就是 S&P 的授权名单。
2. **共同观察窗口。** 目标起点 2016-09-25 是周日，因此统一取其后的首个交易日 2016-09-26；终点为 2026-09-25。这样所有证券与基准使用相同两个收盘日。
3. **含分红价格。** 个股采用 Yahoo Finance `Adj Close`。Yahoo 对该字段的定义是：对适用的拆股和股息分配作历史回溯调整。`BRK.B`、`BF.B` 在 Yahoo 查询时映射为 `BRK-B`、`BF-B`。
4. **基准。** 使用 S&P 500 Total Return Index（`^SP500TR`），而不是价格指数 `^GSPC`。起始值 4,077.709961，终值 17,364.789063。State Street 的 SPY 页面说明 SPY 在扣费前寻求对应 S&P 500 的价格与收益表现；但 SPY 有 0.0945% 总费用率，因此 SPY 复权回报是可投资的净费用代理，不等同于未扣费用的官方指数总回报。
5. **计算。** `累计总回报 = 终值 / 初值 - 1`；`CAGR = (终值 / 初值)^(365.2425 / 实际日数) - 1`；`年化超额 = 个股 CAGR - 基准 CAGR`。仅当年化总回报严格大于基准时入选。
6. **可用性门槛。** 必须在共同起点后四个日历日内有价格、在终点有价格，并有连续、可归属于当前证券的历史。上市/分拆后历史不足十年、缺失或身份不安全者标记 `UNAVAILABLE`，不判为未跑赢。

S&P 官网在 2026-09-25 显示的标准化“10 年年化总回报”为 **15.49%**。本表自行计算为 **15.60%**，差异来自非交易日边界约定：官网滚动十年统计使用其标准周年日规则，而本筛选为保证所有证券可复算，统一使用周日之后的首个共同交易日 2016-09-26。不要混用两个门槛。

## 完整入选名单（135 个）

| 排名 | 代码 | 公司 | 累计总回报 | CAGR | 年化超额 | 起点 | 终点 |
|---:|---|---|---:|---:|---:|---|---|
| 1 | NVDA | Nvidia Corp | 14158.99% | 64.25% | 48.65 pp | 2016-09-26 | 2026-09-25 |
| 2 | AMD | Advanced Micro Devices | 9878.32% | 58.48% | 42.89 pp | 2016-09-26 | 2026-09-25 |
| 3 | MU | Micron Technology Inc | 6293.29% | 51.58% | 35.98 pp | 2016-09-26 | 2026-09-25 |
| 4 | FIX | Comfort Systems Usa Inc | 5922.92% | 50.68% | 35.08 pp | 2016-09-26 | 2026-09-25 |
| 5 | DELL | Dell Technologies  C | 4510.42% | 46.70% | 31.11 pp | 2016-09-26 | 2026-09-25 |
| 6 | LRCX | Lam Research Corp | 3839.58% | 44.41% | 28.82 pp | 2016-09-26 | 2026-09-25 |
| 7 | ANET | Arista Networks Inc | 3783.89% | 44.21% | 28.61 pp | 2016-09-26 | 2026-09-25 |
| 8 | STX | Seagate Technology Holdings | 3574.70% | 43.41% | 27.81 pp | 2016-09-26 | 2026-09-25 |
| 9 | KLAC | Kla Corp | 3090.25% | 41.40% | 25.80 pp | 2016-09-26 | 2026-09-25 |
| 10 | AVGO | Broadcom Inc | 2657.75% | 39.35% | 23.75 pp | 2016-09-26 | 2026-09-25 |
| 11 | TSLA | Tesla Inc | 2570.77% | 38.91% | 23.31 pp | 2016-09-26 | 2026-09-25 |
| 12 | PWR | Quanta Services Inc | 2402.86% | 38.01% | 22.41 pp | 2016-09-26 | 2026-09-25 |
| 13 | FTNT | Fortinet Inc | 2300.50% | 37.43% | 21.83 pp | 2016-09-26 | 2026-09-25 |
| 14 | LITE | Lumentum Holdings Inc | 2197.83% | 36.83% | 21.23 pp | 2016-09-26 | 2026-09-25 |
| 15 | MRVL | Marvell Technology Inc | 2079.79% | 36.11% | 20.51 pp | 2016-09-26 | 2026-09-25 |
| 16 | TER | Teradyne Inc | 1895.34% | 34.91% | 19.31 pp | 2016-09-26 | 2026-09-25 |
| 17 | MPWR | Monolithic Power Systems Inc | 1843.33% | 34.56% | 18.96 pp | 2016-09-26 | 2026-09-25 |
| 18 | SMCI | Super Micro Computer Inc | 1747.93% | 33.88% | 18.28 pp | 2016-09-26 | 2026-09-25 |
| 19 | AMAT | Applied Materials Inc | 1738.51% | 33.81% | 18.21 pp | 2016-09-26 | 2026-09-25 |
| 20 | LLY | Eli Lilly + Co | 1640.40% | 33.08% | 17.48 pp | 2016-09-26 | 2026-09-25 |
| 21 | CIEN | Ciena Corp | 1520.11% | 32.13% | 16.53 pp | 2016-09-26 | 2026-09-25 |
| 22 | TPL | Texas Pacific Land Corp | 1459.18% | 31.62% | 16.03 pp | 2016-09-26 | 2026-09-25 |
| 23 | JBL | Jabil Inc | 1455.05% | 31.59% | 15.99 pp | 2016-09-26 | 2026-09-25 |
| 24 | AXON | Axon Enterprise Inc | 1419.82% | 31.29% | 15.69 pp | 2016-09-26 | 2026-09-25 |
| 25 | PANW | Palo Alto Networks Inc | 1400.56% | 31.12% | 15.52 pp | 2016-09-26 | 2026-09-25 |
| 26 | URI | United Rentals Inc | 1370.80% | 30.86% | 15.26 pp | 2016-09-26 | 2026-09-25 |
| 27 | EME | Emcor Group Inc | 1282.72% | 30.05% | 14.45 pp | 2016-09-26 | 2026-09-25 |
| 28 | AAPL | Apple Inc | 1221.26% | 29.46% | 13.86 pp | 2016-09-26 | 2026-09-25 |
| 29 | CDNS | Cadence Design Sys Inc | 1216.10% | 29.41% | 13.81 pp | 2016-09-26 | 2026-09-25 |
| 30 | MPC | Marathon Petroleum Corp | 1178.83% | 29.04% | 13.44 pp | 2016-09-26 | 2026-09-25 |
| 31 | COHR | Coherent Corp | 1169.66% | 28.95% | 13.35 pp | 2016-09-26 | 2026-09-25 |
| 32 | CAT | Caterpillar Inc | 1142.10% | 28.66% | 13.07 pp | 2016-09-26 | 2026-09-25 |
| 33 | WDC | Western Digital Corp | 1107.78% | 28.30% | 12.71 pp | 2016-09-26 | 2026-09-25 |
| 34 | WSM | Williams Sonoma Inc | 1075.07% | 27.95% | 12.35 pp | 2016-09-26 | 2026-09-25 |
| 35 | KEYS | Keysight Technologies In | 1069.36% | 27.89% | 12.29 pp | 2016-09-26 | 2026-09-25 |
| 36 | APH | Amphenol Corp Cl A | 1051.93% | 27.70% | 12.10 pp | 2016-09-26 | 2026-09-25 |
| 37 | STLD | Steel Dynamics Inc | 1043.60% | 27.61% | 12.01 pp | 2016-09-26 | 2026-09-25 |
| 38 | FLEX | Flex Ltd | 1018.97% | 27.33% | 11.73 pp | 2016-09-26 | 2026-09-25 |
| 39 | NRG | Nrg Energy Inc | 992.76% | 27.03% | 11.43 pp | 2016-09-26 | 2026-09-25 |
| 40 | IBKR | Interactive Brokers Gro Cl A | 977.74% | 26.85% | 11.25 pp | 2016-09-26 | 2026-09-25 |
| 41 | VLO | Valero Energy Corp | 946.15% | 26.47% | 10.88 pp | 2016-09-26 | 2026-09-25 |
| 42 | TT | Trane Technologies Plc | 943.82% | 26.45% | 10.85 pp | 2016-09-26 | 2026-09-25 |
| 43 | MSFT | Microsoft Corp | 921.61% | 26.17% | 10.58 pp | 2016-09-26 | 2026-09-25 |
| 44 | APO | Apollo Global Management Inc | 915.83% | 26.10% | 10.50 pp | 2016-09-26 | 2026-09-25 |
| 45 | TKO | Tko Group Holdings Inc | 915.48% | 26.10% | 10.50 pp | 2016-09-26 | 2026-09-25 |
| 46 | ARES | Ares Management Corp   A | 875.49% | 25.59% | 9.99 pp | 2016-09-26 | 2026-09-25 |
| 47 | DE | Deere + Co | 866.50% | 25.48% | 9.88 pp | 2016-09-26 | 2026-09-25 |
| 48 | PH | Parker Hannifin Corp | 835.89% | 25.07% | 9.47 pp | 2016-09-26 | 2026-09-25 |
| 49 | TRGP | Targa Resources Corp | 799.80% | 24.58% | 8.98 pp | 2016-09-26 | 2026-09-25 |
| 50 | GOOG | Alphabet Inc Cl C | 789.45% | 24.44% | 8.84 pp | 2016-09-26 | 2026-09-25 |
| 51 | NOW | Servicenow Inc | 783.52% | 24.35% | 8.76 pp | 2016-09-26 | 2026-09-25 |
| 52 | GLW | Corning Inc | 776.31% | 24.25% | 8.65 pp | 2016-09-26 | 2026-09-25 |
| 53 | PGR | Progressive Corp | 768.83% | 24.15% | 8.55 pp | 2016-09-26 | 2026-09-25 |
| 54 | GOOGL | Alphabet Inc Cl A | 765.12% | 24.09% | 8.49 pp | 2016-09-26 | 2026-09-25 |
| 55 | ETN | Eaton Corp Plc | 762.10% | 24.05% | 8.45 pp | 2016-09-26 | 2026-09-25 |
| 56 | MS | Morgan Stanley | 738.19% | 23.70% | 8.10 pp | 2016-09-26 | 2026-09-25 |
| 57 | ODFL | Old Dominion Freight Line | 708.47% | 23.25% | 7.66 pp | 2016-09-26 | 2026-09-25 |
| 58 | KKR | Kkr + Co Inc | 705.83% | 23.21% | 7.62 pp | 2016-09-26 | 2026-09-25 |
| 59 | CTAS | Cintas Corp | 687.53% | 22.93% | 7.33 pp | 2016-09-26 | 2026-09-25 |
| 60 | GRMN | Garmin Ltd | 684.62% | 22.89% | 7.29 pp | 2016-09-26 | 2026-09-25 |
| 61 | DECK | Deckers Outdoor Corp | 677.76% | 22.78% | 7.18 pp | 2016-09-26 | 2026-09-25 |
| 62 | FCX | Freeport Mcmoran Inc | 663.92% | 22.56% | 6.96 pp | 2016-09-26 | 2026-09-25 |
| 63 | ADI | Analog Devices Inc | 660.09% | 22.50% | 6.90 pp | 2016-09-26 | 2026-09-25 |
| 64 | NFLX | Netflix Inc | 652.43% | 22.37% | 6.77 pp | 2016-09-26 | 2026-09-25 |
| 65 | NTAP | Netapp Inc | 631.55% | 22.03% | 6.43 pp | 2016-09-26 | 2026-09-25 |
| 66 | BX | Blackstone Inc | 624.98% | 21.92% | 6.32 pp | 2016-09-26 | 2026-09-25 |
| 67 | COST | Costco Wholesale Corp | 622.49% | 21.88% | 6.28 pp | 2016-09-26 | 2026-09-25 |
| 68 | MSCI | Msci Inc | 620.40% | 21.84% | 6.24 pp | 2016-09-26 | 2026-09-25 |
| 69 | SNPS | Synopsys Inc | 619.43% | 21.82% | 6.23 pp | 2016-09-26 | 2026-09-25 |
| 70 | GS | Goldman Sachs Group Inc | 612.39% | 21.70% | 6.11 pp | 2016-09-26 | 2026-09-25 |
| 71 | MSI | Motorola Solutions Inc | 596.79% | 21.43% | 5.84 pp | 2016-09-26 | 2026-09-25 |
| 72 | HLT | Hilton Worldwide Holdings In | 595.39% | 21.41% | 5.81 pp | 2016-09-26 | 2026-09-25 |
| 73 | VEEV | Veeva Systems Inc Class A | 580.77% | 21.15% | 5.55 pp | 2016-09-26 | 2026-09-25 |
| 74 | PHM | Pultegroup Inc | 579.29% | 21.13% | 5.53 pp | 2016-09-26 | 2026-09-25 |
| 75 | JPM | Jpmorgan Chase + Co | 578.26% | 21.11% | 5.51 pp | 2016-09-26 | 2026-09-25 |
| 76 | FICO | Fair Isaac Corp | 574.82% | 21.05% | 5.45 pp | 2016-09-26 | 2026-09-25 |
| 77 | GWW | Ww Grainger Inc | 565.62% | 20.88% | 5.28 pp | 2016-09-26 | 2026-09-25 |
| 78 | ON | On Semiconductor | 564.94% | 20.87% | 5.27 pp | 2016-09-26 | 2026-09-25 |
| 79 | XYZ | Block Inc | 561.64% | 20.81% | 5.21 pp | 2016-09-26 | 2026-09-25 |
| 80 | CF | Cf Industries Holdings Inc | 559.98% | 20.78% | 5.18 pp | 2016-09-26 | 2026-09-25 |
| 81 | FAST | Fastenal Co | 551.01% | 20.61% | 5.01 pp | 2016-09-26 | 2026-09-25 |
| 82 | HPE | Hewlett Packard Enterprise | 529.53% | 20.21% | 4.61 pp | 2016-09-26 | 2026-09-25 |
| 83 | HCA | Hca Healthcare Inc | 528.92% | 20.20% | 4.60 pp | 2016-09-26 | 2026-09-25 |
| 84 | NUE | Nucor Corp | 527.99% | 20.18% | 4.58 pp | 2016-09-26 | 2026-09-25 |
| 85 | AMZN | Amazon.Com Inc | 524.83% | 20.12% | 4.52 pp | 2016-09-26 | 2026-09-25 |
| 86 | LYV | Live Nation Entertainment In | 522.70% | 20.08% | 4.48 pp | 2016-09-26 | 2026-09-25 |
| 87 | ABBV | Abbvie Inc | 521.96% | 20.06% | 4.46 pp | 2016-09-26 | 2026-09-25 |
| 88 | TDG | Transdigm Group Inc | 515.50% | 19.94% | 4.34 pp | 2016-09-26 | 2026-09-25 |
| 89 | AMP | Ameriprise Financial Inc | 513.89% | 19.91% | 4.31 pp | 2016-09-26 | 2026-09-25 |
| 90 | GNRC | Generac Holdings Inc | 507.00% | 19.77% | 4.17 pp | 2016-09-26 | 2026-09-25 |
| 91 | META | Meta Platforms Inc Class A | 496.07% | 19.55% | 3.96 pp | 2016-09-26 | 2026-09-25 |
| 92 | VRTX | Vertex Pharmaceuticals Inc | 495.98% | 19.55% | 3.95 pp | 2016-09-26 | 2026-09-25 |
| 93 | MA | Mastercard Inc   A | 495.14% | 19.53% | 3.94 pp | 2016-09-26 | 2026-09-25 |
| 94 | MAR | Marriott International  Cl A | 473.00% | 19.08% | 3.48 pp | 2016-09-26 | 2026-09-25 |
| 95 | AME | Ametek Inc | 469.37% | 19.01% | 3.41 pp | 2016-09-26 | 2026-09-25 |
| 96 | TDY | Teledyne Technologies Inc | 467.97% | 18.98% | 3.38 pp | 2016-09-26 | 2026-09-25 |
| 97 | MCK | Mckesson Corp | 466.11% | 18.94% | 3.34 pp | 2016-09-26 | 2026-09-25 |
| 98 | CMI | Cummins Inc | 462.90% | 18.87% | 3.27 pp | 2016-09-26 | 2026-09-25 |
| 99 | AXP | American Express Co | 458.90% | 18.79% | 3.19 pp | 2016-09-26 | 2026-09-25 |
| 100 | CASY | Casey S General Stores Inc | 452.26% | 18.64% | 3.05 pp | 2016-09-26 | 2026-09-25 |
| 101 | CSX | Csx Corp | 441.75% | 18.42% | 2.82 pp | 2016-09-26 | 2026-09-25 |
| 102 | HUBB | Hubbell Inc | 439.97% | 18.38% | 2.78 pp | 2016-09-26 | 2026-09-25 |
| 103 | ZBRA | Zebra Technologies Corp Cl A | 439.65% | 18.37% | 2.77 pp | 2016-09-26 | 2026-09-25 |
| 104 | AJG | Arthur J Gallagher + Co | 435.59% | 18.28% | 2.68 pp | 2016-09-26 | 2026-09-25 |
| 105 | WST | West Pharmaceutical Services | 435.16% | 18.27% | 2.67 pp | 2016-09-26 | 2026-09-25 |
| 106 | WMT | Walmart Inc | 434.52% | 18.26% | 2.66 pp | 2016-09-26 | 2026-09-25 |
| 107 | TXN | Texas Instruments Inc | 434.14% | 18.25% | 2.65 pp | 2016-09-26 | 2026-09-25 |
| 108 | DHI | Dr Horton Inc | 429.08% | 18.14% | 2.54 pp | 2016-09-26 | 2026-09-25 |
| 109 | ISRG | Intuitive Surgical Inc | 415.61% | 17.83% | 2.23 pp | 2016-09-26 | 2026-09-25 |
| 110 | IRM | Iron Mountain Inc | 405.58% | 17.60% | 2.00 pp | 2016-09-26 | 2026-09-25 |
| 111 | COR | Cencora Inc | 396.78% | 17.39% | 1.80 pp | 2016-09-26 | 2026-09-25 |
| 112 | WRB | Wr Berkley Corp | 393.61% | 17.32% | 1.72 pp | 2016-09-26 | 2026-09-25 |
| 113 | RSG | Republic Services Inc | 390.97% | 17.26% | 1.66 pp | 2016-09-26 | 2026-09-25 |
| 114 | BNY | Bank Of New York Mellon Corp | 390.33% | 17.24% | 1.64 pp | 2016-09-26 | 2026-09-25 |
| 115 | RJF | Raymond James Financial Inc | 390.14% | 17.24% | 1.64 pp | 2016-09-26 | 2026-09-25 |
| 116 | V | Visa Inc Class A Shares | 381.90% | 17.04% | 1.44 pp | 2016-09-26 | 2026-09-25 |
| 117 | NDAQ | Nasdaq Inc | 377.22% | 16.92% | 1.32 pp | 2016-09-26 | 2026-09-25 |
| 118 | FSLR | First Solar Inc | 377.07% | 16.92% | 1.32 pp | 2016-09-26 | 2026-09-25 |
| 119 | LIN | Linde Plc | 376.19% | 16.90% | 1.30 pp | 2016-09-26 | 2026-09-25 |
| 120 | CBRE | Cbre Group Inc   A | 375.95% | 16.89% | 1.29 pp | 2016-09-26 | 2026-09-25 |
| 121 | JCI | Johnson Controls Internation | 372.94% | 16.82% | 1.22 pp | 2016-09-26 | 2026-09-25 |
| 122 | MCO | Moody S Corp | 372.28% | 16.80% | 1.20 pp | 2016-09-26 | 2026-09-25 |
| 123 | BAC | Bank Of America Corp | 369.73% | 16.74% | 1.14 pp | 2016-09-26 | 2026-09-25 |
| 124 | IDXX | Idexx Laboratories Inc | 367.97% | 16.69% | 1.10 pp | 2016-09-26 | 2026-09-25 |
| 125 | PSX | Phillips 66 | 367.52% | 16.68% | 1.08 pp | 2016-09-26 | 2026-09-25 |
| 126 | FERG | Ferguson Enterprises Inc | 363.63% | 16.59% | 0.99 pp | 2016-09-26 | 2026-09-25 |
| 127 | CSCO | Cisco Systems Inc | 362.14% | 16.55% | 0.95 pp | 2016-09-26 | 2026-09-25 |
| 128 | ORLY | O Reilly Automotive Inc | 358.15% | 16.45% | 0.85 pp | 2016-09-26 | 2026-09-25 |
| 129 | ROK | Rockwell Automation Inc | 355.06% | 16.37% | 0.77 pp | 2016-09-26 | 2026-09-25 |
| 130 | RL | Ralph Lauren Corp | 349.66% | 16.23% | 0.63 pp | 2016-09-26 | 2026-09-25 |
| 131 | TMO | Thermo Fisher Scientific Inc | 344.66% | 16.10% | 0.50 pp | 2016-09-26 | 2026-09-25 |
| 132 | CBOE | Cboe Global Markets Inc | 339.19% | 15.96% | 0.36 pp | 2016-09-26 | 2026-09-25 |
| 133 | TTWO | Take Two Interactive Softwre | 338.87% | 15.95% | 0.35 pp | 2016-09-26 | 2026-09-25 |
| 134 | COP | Conocophillips | 333.35% | 15.80% | 0.20 pp | 2016-09-26 | 2026-09-25 |
| 135 | WELL | Welltower Inc | 329.98% | 15.71% | 0.11 pp | 2016-09-26 | 2026-09-25 |

## `UNAVAILABLE`（37 个）

| 代码 | 公司 | 原因 |
|---|---|---|
| ABNB | Airbnb Inc Class A | 可用历史始于 2020-12-10，不足完整窗口 |
| APP | Applovin Corp Class A | 可用历史始于 2021-04-15，不足完整窗口 |
| BE | Bloom Energy Corp  A | 可用历史始于 2018-07-25，不足完整窗口 |
| CARR | Carrier Global Corp | 可用历史始于 2020-03-19，不足完整窗口 |
| CEG | Constellation Energy | 可用历史始于 2022-01-19，不足完整窗口 |
| COIN | Coinbase Global Inc  Class A | 可用历史始于 2021-04-14，不足完整窗口 |
| CRWD | Crowdstrike Holdings Inc   A | 可用历史始于 2019-06-12，不足完整窗口 |
| CTVA | Corteva Inc | 可用历史始于 2019-05-24，不足完整窗口 |
| CVNA | Carvana Co | 可用历史始于 2017-04-28，不足完整窗口 |
| DASH | Doordash Inc   A | 可用历史始于 2020-12-09，不足完整窗口 |
| DDOG | Datadog Inc   Class A | 可用历史始于 2019-09-19，不足完整窗口 |
| DOW | Dow Inc | 可用历史始于 2019-03-20，不足完整窗口 |
| EXE | Expand Energy Corp | 可用历史始于 2021-02-10，不足完整窗口 |
| FDXF | Fedex Freight Holding Co | 可用历史始于 2026-05-27，不足完整窗口 |
| FOX | Fox Corp   Class B | 可用历史始于 2019-03-13，不足完整窗口 |
| FOXA | Fox Corp   Class A | 可用历史始于 2019-03-12，不足完整窗口 |
| GEHC | Ge Healthcare Technology | 可用历史始于 2022-12-15，不足完整窗口 |
| GEV | Ge Vernova Inc | 可用历史始于 2024-03-27，不足完整窗口 |
| HONA | Honeywell Aerospace Inc | 可用历史始于 2026-06-15，不足完整窗口 |
| HOOD | Robinhood Markets Inc   A | 可用历史始于 2021-07-29，不足完整窗口 |
| HWM | Howmet Aerospace Inc | 可用历史始于 2016-11-01，不足完整窗口 |
| INVH | Invitation Homes Inc | 可用历史始于 2017-02-01，不足完整窗口 |
| IR | Ingersoll Rand Inc | 可用历史始于 2017-05-12，不足完整窗口 |
| KVUE | Kenvue Inc | 可用历史始于 2023-05-04，不足完整窗口 |
| MRNA | Moderna Inc | 可用历史始于 2018-12-07，不足完整窗口 |
| OTIS | Otis Worldwide Corp | 可用历史始于 2020-03-19，不足完整窗口 |
| P | Everpure Inc A | 当前证券为新发行的 Everpure；Yahoo 的 P 十年历史存在旧代码归属风险，无法安全串联 |
| PLTR | Palantir Technologies Inc A | 可用历史始于 2020-09-30，不足完整窗口 |
| Q | Qnity Electronics Inc | 可用历史始于 2025-10-27，不足完整窗口 |
| RDDT | Reddit Inc Cl A | 可用历史始于 2024-03-21，不足完整窗口 |
| SNDK | Sandisk Corp | 可用历史始于 2025-02-13，不足完整窗口 |
| SOLV | Solventum Corp | 可用历史始于 2024-03-26，不足完整窗口 |
| UBER | Uber Technologies Inc | 可用历史始于 2019-05-10，不足完整窗口 |
| VICI | Vici Properties Inc | 可用历史始于 2018-01-02，不足完整窗口 |
| VLTO | Veralto Corp | 可用历史始于 2023-10-04，不足完整窗口 |
| VRT | Vertiv Holdings Co A | 可用历史始于 2018-08-02，不足完整窗口 |
| VST | Vistra Corp | 可用历史始于 2016-10-05，不足完整窗口 |

## 重要限制

- **幸存者偏差：** 用的是 2026-09-25 的当前成分股，而不是 2016 年的点时成分股；退市、被收购、被剔除的历史公司没有进入样本。因此这是“今天有哪些现任成分股过去十年跑赢”的候选筛选，不是可交易历史回测。
- **免费行情并非审计级数据：** Yahoo 可修订历史复权因子；并购、分拆、换股、代码复用、特别分红和境外迁册可能被错误串联或遗漏。`Adj Close` 通常适合初筛，但在据此投资前应对候选逐一用交易所/公司行动数据或付费 CRSP、Bloomberg、FactSet 等复核。
- **前身连续性：** DELL、TKO、PSKY 等证券包含组织重组或前身证券链。Yahoo 提供连续复权序列，所以本次机械口径予以保留，但这些项目的经济连续性需单独审计；`P` 因当前发行人身份明显无法安全归属而已剔除。
- **不含交易摩擦与税：** 结果忽略交易费、买卖价差、税收以及个人对现金股息再投资时点的差异。
- **端点敏感：** 接近门槛的股票会因选择前一交易日还是后一交易日、或行情供应商的复权修订而改变。最低入选者 WELL 仅高出约 0.11 个百分点，尤其需要复核。

## 来源

- [State Street SPY 产品页](https://www.ssga.com/us/en/intermediary/etfs/state-street-spdr-sp-500-etf-trust-spy)：基金目标、基准、费用率、截至日期。
- [State Street SPY 每日持仓 XLSX](https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx)：当前证券、代码、标识符、权重；文件标注 2026-09-25。
- [S&P Dow Jones Indices：S&P 500（USD Total Return）](https://www.spglobal.com/spdji/en/indices/equity/sp-500/?currency=USD&returntype=T-#overview)：官方指数描述、总回报口径和官网十年统计。
- [Yahoo Help：What is the adjusted close?](https://help.yahoo.com/kb/SLN28256.html)：复权收盘价对拆股与股息的处理定义。
- [yfinance 文档](https://ranaroussi.github.io/yfinance/)：用于访问 Yahoo 历史行情的开源客户端；项目声明其不隶属于 Yahoo 且数据仅供研究/教育用途。运行版本 1.7.0。
- [Wikipedia：List of S&P 500 companies](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies)：仅作为可机器读取的二级交叉核对，不作为第一方权威名单。
- [NYSE 交易时间与日历](https://www.nyse.com/trade/hours-calendars)：交易日/核心交易时段参考。

本文件是一次性研究筛选，不构成投资建议，也不把“历史跑赢”解释为未来收益预测或买入授权。
