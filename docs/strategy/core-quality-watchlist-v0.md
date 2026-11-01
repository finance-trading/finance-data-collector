# Core Quality Watchlist v0

> 状态：**PROVISIONAL**。这是研究候选池，不是买入清单，也不是已完成 Point-in-Time 验证的 Quality Universe。  
> 截止日期：2026-09-26（America/Los_Angeles）。  
> 共同财务窗口：SEC Frames CY2021–CY2025。  
> 结论：先持续覆盖 23 家公司；23 家均通过本文件第 2 节的初步机械门槛。任何买入仍必须在事件发生前通过最终冻结的 Quality Gate，并在事件后完成 Temporary / Structural 判断与重新估值。
> 四层筛选口径：[`four-layer-screening-rules-v0.md`](four-layer-screening-rules-v0.md)。现有 23 家产生于 Layer 3 评分卡之前，必须在 96 家统一双人评分后才可转为正式核心观察池。

## 1. 本次到底做了什么

本次先用一份日期为 2026-09-23 的当前 S&P 500 成分股快照建立候选 universe：503 个证券代码，合并双重股权后解析为 500 家公司。随后用 SEC 官方 Frames / Company Facts 数据读取 CY2021–CY2025 的 Revenue、Operating Income、Net Income、CFO、CapEx、Diluted Shares、Assets、Equity、Cash 和 Debt。

这一轮筛选的用途是把约 500 家公司缩小成一个能开始做深度研究的范围，而不是证明这些公司当前便宜或将来一定恢复。

### 证据边界

- 财务数据来自 SEC，是一手来源。
- 当前成分股快照不是 S&P Dow Jones Indices 官方授权文件，因此当前成员身份仍需用同日官方文件复核。
- 当前成分股不能替代历史成分股；这份名单不可直接拿去做历史回测。
- SEC Frames 是跨公司快速筛选工具，tag fallback、公司财年和公司行动可能造成不可比；所有入选公司仍要逐份 10-K 复核。
- Company Facts 可能包含后续重述，不代表历史事件时点当时可见的数据。

因此这份名单必须标记为 **PROVISIONAL**。

## 2. 初步机械门槛

先排除 GICS Financials、Real Estate 和 Utilities；这些行业需要针对监管资本、准备金、资产负债表或公用事业资本结构设计专用口径。其余公司使用以下 v0 门槛：

1. CY2021–CY2025 至少有 4 个可比年度观察；
2. `FCF = CFO - CapEx`，至少 4/5 年为正；
3. 五年中位 ROA 不低于 5%；
4. 五年中位 FCF margin 不低于 4%；
5. 五年中位 Operating margin 不低于 8%；
6. 观察期 Revenue CAGR 为正；
7. Diluted-share CAGR 不高于 3%；
8. 最新 `Net debt / FCF` 不高于 4 倍。

在 500 家解析公司中，96 家通过上述初步门槛。本文件最初从这 96 家中人工选择 23 家，兼顾：

- 商业模式在当前能力圈内；
- 黏性来源可以被经营指标验证；
- Temporary / Structural 问题可以写成可证伪命题；
- 覆盖数量能维持在 15–30 家；
- 不完全依赖一个收入模式或一个行业。

这些阈值尚未在正式 Strategy Contract 中冻结。尤其是 ROA 只是当前可横向取得的资本效率 proxy，不能代替最终 ROIC。

从 2026-09-27 起，96→核心观察池必须改用四层筛选文档中的六项双人评分卡。以下 23 家因此仍是候选名单，不代表已经完成统一评分。

## 3. 候选核心观察池（23 家）

状态代码：

- **PASS**：通过本次初步机械门槛；
- **PASS ≠ BUY**：没有做当前估值、事件判断或安全边际判断。

### A. 数字平台、软件、数据与安全（12）

| 公司 | 状态 | 为什么值得事前覆盖 | 最需要证伪的结构性风险 | 一手证据 |
|---|---|---|---|---|
| **MSFT — Microsoft** | PASS | 企业软件、云与生产力工作流覆盖广，适合作为“高质量公司遭遇 AI 基建资本强度上升”的标准案例。 | AI CapEx 是否永久压低回报率；云竞争和 Copilot 变现能否覆盖新增资本强度。 | [2026 10-K](https://www.sec.gov/Archives/edgar/data/789019/000119312526323660/msft-20260630.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json) |
| **GOOG / GOOGL — Alphabet** | PASS | Search、YouTube、Cloud 和广告基础设施具有规模与分发优势，且用户、流量、价格、CapEx 均可持续追踪。 | 生成式 AI 是否改变搜索入口和单位经济；反垄断救济是否伤及分发或广告业务。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0001652044.json) |
| **META — Meta Platforms** | PASS | 社交产品和广告系统可用用户、参与度、广告价格及 CapEx 检验，适合研究市场对大额投资的过度反应。 | AI / Reality Labs 投入是否从暂时利润压力变成长期低回报资本配置；监管或用户迁移是否削弱网络效应。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/1326801/000162828026003942/meta-20251231.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0001326801.json) |
| **AAPL — Apple** | PASS | 设备生态、装机基础和服务关系使产品周期与长期用户黏性可以分开研究。 | 硬件成熟、平台监管、供应链与 AI 产品节奏是否造成永久性经济损失。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json) |
| **ADBE — Adobe** | PASS | Creative Cloud 和 Document Cloud 是高频专业工作流，最适合检验“生成式 AI 是增量工具还是替代品”。 | 新模型是否削弱专业软件定价权、续费或工作流控制点。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/796343/000079634326000003/adbe-20251128.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000796343.json) |
| **INTU — Intuit** | PASS | 税务、会计、工资与个人理财产品沉淀数据和工作流，核心 KPI 可以持续验证。 | 政府直接报税、AI 自动化和获客成本变化是否永久削弱产品价值。 | [2026 10-K](https://www.sec.gov/Archives/edgar/data/896878/000089687826000037/intu-20260731.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000896878.json) |
| **ADSK — Autodesk** | PASS | 建筑、工程、制造和设计软件深度嵌入专业流程，订阅转换与使用强度可追踪。 | AI 生成设计、治理 / 会计问题或建筑周期是否削弱长期定价与留存。 | [2026 10-K](https://www.sec.gov/Archives/edgar/data/769397/000076939726000015/adsk-20260131.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000769397.json) |
| **CDNS — Cadence Design Systems** | PASS | EDA 软件和 IP 是复杂芯片设计的关键工具，研发强度和客户需求可由半导体设计活动验证。 | 大客户自研、竞争、出口限制或 AI 对设计工具栈的改变是否削弱控制点。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/813672/000081367226000016/cdns-20251231.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000813672.json) |
| **FTNT — Fortinet** | PASS | 网络安全设备、订阅与服务形成安装基础和续费关系，可区分产品周期与安全平台竞争力。 | 客户向其他平台迁移、硬件更新放缓或安全功能商品化是否造成结构性份额流失。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/1262039/000126203926000007/ftnt-20251231.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0001262039.json) |
| **VRSN — Verisign** | PASS | `.com` / `.net` 注册基础设施具有独特合同与规模属性，域名量、续费和价格可直接观察。 | ICANN 合同、监管、定价限制或域名需求长期下降是否损伤核心经济性。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/1014473/000101447326000006/vrsn-20251231.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0001014473.json) |
| **FICO — Fair Isaac** | PASS | 信用评分和决策软件嵌入信贷流程，具有数据、标准和工作流属性。 | 监管、替代数据 / 模型、客户反制或定价争议是否削弱评分标准地位。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/814547/000081454725000030/fico-20250930.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000814547.json) |
| **VRSK — Verisk Analytics** | PASS | 保险数据、分析和客户工作流具有高嵌入度，适合用续约、数据贡献和保险活动验证黏性。 | AI、监管或客户自建是否降低数据与分析平台的差异化。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/1442145/000143774926004452/vrsk20251231_10k.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0001442145.json) |

### B. 半导体设计与设备（3）

| 公司 | 状态 | 为什么值得事前覆盖 | 最需要证伪的结构性风险 | 一手证据 |
|---|---|---|---|---|
| **AMAT — Applied Materials** | PASS | 半导体制造设备和安装基础服务收入使行业周期、份额和长期工艺需求可以拆分研究。 | 出口限制、客户 CapEx 周期或关键制程竞争是否造成永久性份额 / 内容量下降。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/6951/000162828025056742/amat-20251026.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000006951.json) |
| **MPWR — Monolithic Power Systems** | PASS | 高性能电源管理芯片覆盖多个终端，产品设计导入和客户扩张可持续追踪。 | 客户集中、库存修正、模拟芯片竞争或内部替代是否破坏长期份额增长。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/1280452/000143774926006113/mpwr20251231_10k.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0001280452.json) |
| **QCOM — Qualcomm** | PASS | 无线专利许可与芯片平台提供两种经济引擎，可分别研究终端周期和技术护城河。 | 大客户自研、专利监管、中国敞口或架构迁移是否永久削弱许可与芯片经济。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/804328/000080432825000085/qcom-20250928.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000804328.json) |

### C. 医疗平台、诊断与器械（4）

| 公司 | 状态 | 为什么值得事前覆盖 | 最需要证伪的结构性风险 | 一手证据 |
|---|---|---|---|---|
| **IDXX — IDEXX Laboratories** | PASS | 兽医诊断设备、耗材和参考实验室形成安装基础与重复使用关系。 | 宠物就诊、诊所预算或竞争变化是否导致利用率与定价权长期下行。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/874716/000087471626000038/idxx-20251231.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000874716.json) |
| **VRTX — Vertex Pharmaceuticals** | PASS | 现有疾病领域的商业现金流支持研发管线，适合区分单次试验失败和平台 / 集中度风险。 | 核心产品集中、专利周期、定价政策或管线执行是否造成永久价值损失。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/875320/000087532026000056/vrtx-20251231.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000875320.json) |
| **RMD — ResMed** | PASS | 呼吸设备装机后带动面罩和耗材复购，可用患者流量、装机和供应恢复验证。 | GLP-1、竞争、报销或渠道变化是否永久降低睡眠呼吸治疗需求。 | [2026 10-K](https://www.sec.gov/Archives/edgar/data/943819/000094381926000047/rmd-20260630.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000943819.json) |
| **ISRG — Intuitive Surgical** | PASS | 手术机器人装机量带动器械和服务需求，临床采用与 procedure growth 可持续验证。 | 新竞争、医院预算、监管或临床结果是否破坏装机飞轮，而非仅推迟采购。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/1035267/000103526726000010/isrg-20251231.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0001035267.json) |

### D. 消费平台与经常性服务（4）

| 公司 | 状态 | 为什么值得事前覆盖 | 最需要证伪的结构性风险 | 一手证据 |
|---|---|---|---|---|
| **BKNG — Booking Holdings** | PASS | 在线旅行平台连接全球供需，预订量、间夜、获客与营销效率可持续检验。 | Google / AI 流量入口、直接预订、监管或竞争是否永久提高获客成本并削弱网络。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/1075531/000107553126000009/bkng-20251231.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0001075531.json) |
| **LULU — lululemon** | PASS | 品牌、直营渠道、门店生产率和客户复购可以用同店销售、库存和区域增长验证。 | 产品 / 品牌热度、竞争或区域扩张失误是否从短期执行问题演变成长期品牌衰退。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/1397187/000139718726000020/lulu-20260201.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0001397187.json) |
| **PAYX — Paychex** | PASS | 中小企业工资与人力资源服务具有重复使用和合规工作流，客户数、留存与就业可追踪。 | 云软件竞争、就业周期或利率相关浮存收益下降是否暴露出核心服务增长疲弱。 | [2026 10-K](https://www.sec.gov/Archives/edgar/data/723531/000119312526307785/payx-20260531.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000723531.json) |
| **ROL — Rollins** | PASS | 害虫控制具有重复需求、路线密度和本地服务网络，客户留存与有机增长可验证。 | 人工、客户流失、收购依赖或本地竞争是否削弱路线经济，而非暂时成本压力。 | [2025 10-K](https://www.sec.gov/Archives/edgar/data/84839/000008483926000008/rol-20251231.htm) · [XBRL](https://data.sec.gov/api/xbrl/companyfacts/CIK0000084839.json) |

## 4. 为什么没有把一些“显然很好的公司”直接放进来

没有入选不等于低质量。下面这些名字揭示了筛选器当前的边界，不能把数据问题冒充基本面结论。

| 公司 / 类别 | 当前状态 | 证据边界 |
|---|---|---|
| **V、MA、SPGI、MCO、CME、ICE** | `MANUAL_METHOD_REQUIRED` | GICS Financials 在机械筛选中被排除；支付网络、评级、数据和交易所并非传统银行，但 ROA / leverage 仍需专用口径，不能假装已经通过普通企业门槛。 |
| **COST** | `MANUAL_EXCEPTION_CANDIDATE` | 5/5 FCF 为正、中位 ROA 约 9.0%、收入 CAGR 约 8.9%，但低毛利会员模式使中位 FCF margin 约 2.7%、Operating margin 约 3.4%，机械上未过统一 margin gate。应判断是合理商业模式差异还是放宽标准。 [2025 10-K](https://www.sec.gov/Archives/edgar/data/909832/000090983225000101/cost-20250831.htm) |
| **CRM** | `WATCH / MANUAL_EXCEPTION` | 5/5 FCF 为正、中位 FCF margin 约 27.2%、Operating margin 约 14.4%、收入 CAGR 约 11.9%，但中位 ROA 约 4.2%，低于 5% 门槛。不能为喜欢的公司临时改线。 [2026 10-K](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000060/crm-20260131.htm) |
| **NOW、CTAS** | `DATA_CONFLICT` | Frames 显示 diluted-share CAGR 分别约 50.7% / 40.1%，与拆股 / 公司行动可比性冲突，不能当成真实稀释或硬性 Fail；需先做 split-adjusted 人工复核。 |
| **ROP** | `UNAVAILABLE` | SEC Frames 的 CapEx tag 覆盖不足，无法取得可比 FCF；这是数据缺口，不是 Fail。 |
| **LIN** | `NEAR_MISS` | 最新 Net debt / FCF 约 4.3 倍，略高于 4 倍门槛；其他门槛通过。需要先决定阈值而不是对单个公司破例。 |
| **AMZN** | `FAIL_CURRENT_GATE` | 当前快速口径仅 3/5 年 FCF 为正；在拆分 AWS、零售物流和 AI CapEx 前，不进入本版核心池。 |
| **ORCL** | `FAIL_CURRENT_GATE` | 当前快速口径仅 3/5 年 FCF 为正，最近两年 CapEx 激增；需先判断资本强度是否结构性改变。 |
| 银行、保险、REIT、Utilities | `SEPARATE_MODEL` | 监管资本、准备金、资产负债表和资本强度使普通企业 FCF / ROA / leverage 门槛失真。 |

## 5. 相关性：23 个名字不等于 23 个独立风险

本名单仍明显偏向技术、互联网和无形资产型商业模式。以下必须作为共享风险主题管理：

- **AI 改变软件 / 搜索经济**：MSFT、GOOG/GOOGL、META、ADBE、INTU、ADSK、CDNS；
- **半导体与 AI CapEx 周期**：MSFT、GOOG/GOOGL、META、AMAT、MPWR、QCOM、CDNS；
- **监管嵌入型数据 / 标准**：VRSN、FICO、VRSK；
- **高估值 Quality duration**：几乎覆盖全部名单，不能靠行业标签消除；
- **医疗采用和报销**：IDXX、VRTX、RMD、ISRG，驱动因素不同，但都不能只看历史利润率。

观察池可以同时覆盖这些公司；实际持仓必须另设单主题上限。

## 6. 下一步：把 PASS 变成“事前真正理解”

对 23 家逐一完成一页式正常状态 dossier：

1. 过去五年 Revenue、Operating Income、CFO、CapEx、FCF、Cash、Debt、Diluted Shares 的逐份 10-K 人工复核；
2. 统一 ROIC、净杠杆、稀释、重述和并购调整口径；
3. 三个最重要价值驱动因素与三个核心 KPI；
4. 正常利润率、正常再投资率和资本配置记录；
5. 竞争优势的可观察证据，而不是“护城河”标签；
6. 最可能出现的事件触发器；
7. 哪些证据意味着问题只是 Temporary，哪些意味着已经 Structural；
8. 正常状态估值区间，但不把当前高价或历史高点当 Fair Value。

在这些 dossier 完成前，可以记录事件，但不能因 `PASS` 自动获得买入资格。

## 7. 数据来源与可复现口径

一手来源：

- SEC 公司 / CIK 映射：[`company_tickers.json`](https://www.sec.gov/files/company_tickers.json)；
- SEC Frames 示例：[`RevenueFromContractWithCustomerExcludingAssessedTax / CY2025`](https://data.sec.gov/api/xbrl/frames/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax/USD/CY2025.json)、[`OperatingIncomeLoss / CY2025`](https://data.sec.gov/api/xbrl/frames/us-gaap/OperatingIncomeLoss/USD/CY2025.json)、[`NetCashProvidedByUsedInOperatingActivities / CY2025`](https://data.sec.gov/api/xbrl/frames/us-gaap/NetCashProvidedByUsedInOperatingActivities/USD/CY2025.json)、[`PaymentsToAcquirePropertyPlantAndEquipment / CY2025`](https://data.sec.gov/api/xbrl/frames/us-gaap/PaymentsToAcquirePropertyPlantAndEquipment/USD/CY2025.json)；
- 每家公司的最新 10-K 与 Company Facts：见第 3 节逐行链接。

筛选实现存在的主要技术限制：

- Revenue、CapEx、Debt 等使用多个 us-gaap tag fallback；
- CY Frames 与非自然年公司财年可能存在错位；
- 拆股和其他公司行动可能破坏 diluted-share CAGR 可比性；
- 缺失值被保留为 `UNAVAILABLE`，不应自动判为 Fail；
- 这是当前截面 screen，不具备历史事件所需的 PIT 成分股和 PIT 财务数据。

## 8. 冻结结论

当前可以冻结的是：

> 从 2026-09-26 开始，优先为上述 23 家建立持续覆盖。它们通过了统一的初步机械筛选，并且具备可研究、可监控、可证伪的业务质量机制。

当前不能冻结的是：

> “这 23 家是全量 S&P 500 中客观最好的公司”“它们已经通过最终 Quality Gate”或“它们当前具有安全边际”。现有证据不支持这些结论。
