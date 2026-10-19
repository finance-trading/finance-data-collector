# 32 龙头「关系证据」原始来源审计

审计日期：2026-10-18。逐条检查 `ai-layer-leaders-32-company-relations.xlsx` 的「关系证据」32 行（24 个不重复 URL）。`verified` 仅指来源支持所述事实，**不自动证明已采购、已交付或当前收入**；`overstated` 指原表把计划、试用或联合方案表述成更强的现况；`unavailable` 指本轮无法读取原文，不能断言主张为假。公告是单方或双方新闻稿，非合同/发票/财务披露。

| # | 表内关系 | 审计 | 来源实际支持的级别及需调整处 |
|---:|---|---|---|
| 1 | GEV → AWS | verified | [GE Vernova 2025-03-04](https://www.gevernova.com/news/press-releases/ge-vernova-aws-accelerate-global-energy-demand)：战略框架协议；公告明确称 *will continue to provide* AWS 接网变电站方案，既有供应关系有依据，但新增站点范围属未来计划。可画供应边，标「既有供应＋框架协议」。 |
| 2 | TSM → NVDA（NVDA 上游行） | verified | [NVIDIA 2025-10-17](https://blogs.nvidia.com/blog/tsmc-blackwell-manufacturing/)：TSMC Arizona 首片 NVIDIA Blackwell 晶圆产出，报道称 Blackwell 达量产阶段。能证明芯片制造环节，不能据此推出全部 Blackwell 均在 Arizona 制造。 |
| 3 | TSM → NVDA（TSM 下游行） | verified | 同[上](https://blogs.nvidia.com/blog/tsmc-blackwell-manufacturing/)；与 #2 是同一关系的双向索引，图中只能计一条边。 |
| 4 | NVDA → META（NVDA 下游行） | overstated | [NVIDIA 2026-02-17](https://nvidianews.nvidia.com/news/meta-builds-ai-infrastructure-with-nvidia)：已扩展 Grace CPU 部署，但 Blackwell/Rubin「数百万」是多年合作的 *will enable deployment*；Rubin 的更大部署尚属计划。拆成「现有 Grace 部署」与「计划 GPU/网络部署」，不能将数百万 GPU 标为已部署。 |
| 5 | NVDA → META（META 上游行） | overstated | 同[上](https://nvidianews.nvidia.com/news/meta-builds-ai-infrastructure-with-nvidia/)；与 #4 同一边，不可双计。 |
| 6 | NVDA → Google Cloud（NVDA 下游行） | overstated | [NVIDIA 2024-03-18](https://nvidianews.nvidia.com/news/google-cloud-ai-development)：Grace Blackwell 是 *announced its adoption*，尚非该公告证明已部署；H100 驱动 DGX Cloud 当时已 GA。按产品分别标「宣布采用」和「已提供」，而非统一已交付。 |
| 7 | NVDA → Google Cloud（GOOGL 上游行） | overstated | 同[上](https://nvidianews.nvidia.com/news/google-cloud-ai-development/)；与 #6 同一边，不可双计。 |
| 8 | NVDA → NBIS（NVDA 下游行） | verified | [Nebius 2026-03-11](https://nebius.com/newsroom/nvidia-and-nebius-partner-to-scale-full-stack-ai-cloud)：明确称 Nebius 全球平台 *ongoing deployment of NVIDIA infrastructure*；5GW 及 Rubin/Vera 扩建是未来计划。既有部署可画供应边，扩建不可画成已完成。 |
| 9 | NVDA → NBIS（NBIS 上游行） | verified | 同[上](https://nebius.com/newsroom/nvidia-and-nebius-partner-to-scale-full-stack-ai-cloud/)；与 #8 同一边，不可双计。该公告同时披露 NVIDIA 拟向 Nebius 投资 $2bn，此为**反向资金关系**，不应混作硬件供应。 |
| 10 | NBIS → Microsoft | verified | [Nebius 2025-09-08](https://nebius.com/newsroom/nebius-announces-multi-billion-dollar-agreement-with-microsoft-for-ai-infrastructure)：多年协议，承诺从 Vineland 数据中心 *starting later this year* 交付专用 AI 容量。证实已签约，不单凭此公告证明实际交付已开始；画「已签供应协议/待核实交付」。 |
| 11 | AWS → CRM（CRM 上游行） | verified | [Salesforce 2023-11-27](https://www.salesforce.com/news/press-releases/2023/11/27/aws-data-ai-strategic-partnership-expansion/)：Salesforce *significantly expands its use of AWS*，Data Cloud 采用 AWS-native 路径。支持云服务使用。 |
| 12 | CRM → AWS（CRM 下游行） | verified | 同[上](https://www.salesforce.com/news/press-releases/2023/11/27/aws-data-ai-strategic-partnership-expansion/)：AWS 增加全公司 Salesforce CRM 使用，包括采用 Data Cloud。与 #11 是**真实的双向不同产品/服务关系**，应保留双向两条边，明确供应物不同。 |
| 13 | APP → Wayfair | verified | [AppLovin Wayfair 案例](https://new.applovin.com/en/resources/video-testimonial-wayfair)：Wayfair 做了州级 holdout 和 ROAS 测试，来源称测试并扩张获客渠道；属于客户使用/试用案例，**不是长期采购承诺或量化收入证据**。页面未标发布日期。 |
| 14 | AWS → TEAM | overstated | [Atlassian AWS 合作页](https://www.atlassian.com/partnerships/aws)：页面称在 AWS 基础设施上 *build, scale, and secure*，并称 Atlassian 云产品上架 AWS Marketplace；足以支持平台/渠道合作，但该页不足以证明所有企业云应用均「在 AWS 上构建、运行」及实际采购规模。改「AWS 基础设施及 Marketplace 合作」；页面无明确发布日期。 |
| 15 | NVDA → ADBE | overstated | [Adobe 2026-03-16](https://news.adobe.com/news/2026/03/adobe-and-nvidia-announce-strategic-partnership)：Adobe *will use* NVIDIA 计算技术和库开发下一代 Firefly，属宣布的开发计划/技术合作，未证实已经采购或交付。改虚线「宣布采用/联合开发」。 |
| 16 | AWS → GEV | verified | 同[GE Vernova 2025-03-04](https://www.gevernova.com/news/press-releases/ge-vernova-aws-accelerate-global-energy-demand/)：AWS 将支持 GEV 云迁移与数字创新。是战略框架协议中的拟议云服务关系，**未证实云迁移已完成或具体消费额**；只能画「协议/计划」虚线，不能画现有采购实线。 |
| 17 | ETN — NVDA | unavailable | [Eaton 所列 URL](https://www.eaton.com/us/en-us/company/news-insights/news-releases/2025/eaton-accelerates-data-center-infrastrructure-in-ai-era-with-nvidia.html) 本轮超时，且路径 `infrastrructure` 疑似拼写错误。该行暂撤出「已核实」集合，需找到可读取的 Eaton/NVIDIA 官方原文后复核；绝不推断具体采购。 |
| 18 | MU — NVDA | unavailable | [Micron 所列 URL](https://investors.micron.com/news/press-release/2026/Micron-in-High-Volume-Production-of-HBM4-Designed-for-NVIDIA-Vera-Rubin-PCIe-Gen6-SSD-and-SOCAMM2-03-16-2026/default.aspx) 返回 Cloudflare 403。不能复核「HBM4 量产出货」和「为 Vera Rubin 设计」的原文边界，暂不画采购边。 |
| 19 | CSCO — NVDA | verified | [Cisco 2026-03-16](https://newsroom.cisco.com/c/r/newsroom/en/us/a/y2026/m03/cisco-secure-ai-factory-with-nvidia-GTC-2026.html)：扩展 Secure AI Factory 参考架构；Cisco N9100 有 NVIDIA Spectrum-4 版本已 GA、Spectrum-6 为新公布产品。可画「产品集成/部分现售」，不能等同 Cisco 与 NVIDIA 之间某笔采购合同。 |
| 20 | VZ — NVDA | verified | [Verizon 2024-12-17](https://www.verizon.com/about/news/verizon-nvidia-power-ai-workloads-5g-private-networks-mec)：共同开发私有 5G/MEC 企业 AI 方案，集成 NVIDIA AI Enterprise/NIM；当时预计 2025 初演示。画「联合方案」，非已签大客户销售。 |
| 21 | SAP — Microsoft Cloud | verified | [SAP 2025-05-27](https://news.sap.com/2025/05/new-sap-business-suite-acceleration-program-microsoft-cloud/)：双方 Business Suite Acceleration Program、Azure 上的 SAP Cloud ERP Private 和 Copilot 集成。画「云平台/产品集成」，非具名采购合同。 |
| 22 | HUBS — OpenAI | unavailable | [HubSpot 所列 URL](https://ir.hubspot.com/news-releases/news-release-details/hubspot-and-openai-deepen-partnership-bring-ai-transformation) 返回 Cloudflare 403；暂不把 ChatGPT CRM connector 或 2026-09-16 日期当作本轮已复核事实。 |
| 23 | Google Cloud → PANW | unavailable | [Palo Alto Networks 所列 URL](https://investors.paloaltonetworks.com/news-releases/news-release-details/palo-alto-networks-and-google-cloud-forge-landmark-agreement/) 返回 403；Prisma Access 是否及如何运行在 Google 网络上须另找官方可访问原文。暂不画已核实供应边。 |
| 24 | IBM — NVDA | verified | [IBM 2026-03-16](https://newsroom.ibm.com/2026-03-16-ibm-and-nvidia-announce-expanded-collaboration-at-gtc-2026-to-advance-ai-for-the-enterprise)：数据分析、文档处理、基础设施和咨询层面的扩展合作；画「技术集成/合作」，不画单向采购。 |
| 25 | V — AWS | overstated | [AWS/Visa 2025-12-01](https://press.aboutamazon.com/aws/2025/12/visa-and-aws-enable-next-generation-agentic-commerce-capabilities)：Visa *will list* Intelligence Commerce 于 AWS Marketplace，双方 *will publish* AgentCore 蓝图；属宣布的上架/发布计划，非该公告证实已经上架。改「计划产品集成/渠道」虚线。 |
| 26 | TWLO — OpenAI | verified | [Twilio 2024-10-01](https://www.twilio.com/en-us/press/releases/openai-integration)：宣布将 OpenAI Realtime API 集成到 Twilio 通信 API，*will enable* 客户开发语音应用。证实合作/集成公告，未证实 30 万客户均已采用。 |
| 27 | TRI — Microsoft | verified | [Thomson Reuters 2023-05-23](https://www.thomsonreuters.com/en/press-releases/2023/may/thomson-reuters-brings-forward-vision-to-redefine-the-future-of-professionals-with-content-driven-ai-technology)：宣布 Microsoft 365 Copilot 插件，用于法律研究、起草及协作。支持产品集成，不证明采购。 |
| 28 | PLTR — Anthropic / AWS | unavailable | [Palantir IR 所列 URL](https://investors.palantir.com/news-details/2024/Anthropic-and-Palantir-Partner-to-Bring-Claude-AI-Models-to-AWS-for-U.S.-Government-Intelligence-and-Defense-Operations/) HTTP 200 但本轮只能提取导航，无新闻正文；不能据此复核 Claude 版本、部署范围和机构使用情况。待另找官方原文。 |
| 29 | AAPL — TXN（Apple 行） | verified | [Apple 2026-03-26](https://www.apple.com/newsroom/2026/03/apple-adds-new-partners-to-its-american-manufacturing-program/)：Texas Instruments 被列为制造计划首批伙伴，并称首批伙伴已达成扩建里程碑；**此文未列 TXN 为 Apple 生产何具体部件**。保留伙伴边，不画具体芯片采购。 |
| 30 | AAPL — TSMC | verified | 同[Apple 2026-03-26](https://www.apple.com/newsroom/2026/03/apple-adds-new-partners-to-its-american-manufacturing-program/)：Apple、Bosch 与 TSMC *will work together* 在 TSMC Washington 为 Bosch 传感硬件生产 IC，服务 Apple 产品功能。是已宣布的**三方未来制造计划**；不能简化成「TSMC 已直接供货 Apple 此 IC」。 |
| 31 | TXN — AAPL（TXN 行） | verified | 同[Apple 公告](https://www.apple.com/newsroom/2026/03/apple-adds-new-partners-to-its-american-manufacturing-program/)；与 #29 同一伙伴关系，图中只能计一次。 |
| 32 | DELL — NVDA | unavailable | [Dell 所列产品页](https://www.dell.com/en-us/shop/campaign/lp/nvidia-ai) 返回 403，暂不能复核页面文案；即使产品页证实联合品牌，也不等于某笔采购合同。 |

## 对图的直接修正

1. **实线产品/服务流**仅保留原文能证实当前制造、使用或部署的关系：TSM → NVDA、NVDA → NBIS（既有基础设施）、AWS → CRM、CRM → AWS、GEV → AWS（既有变电站供应）、APP → Wayfair（明确标试用/案例）；NVDA → META 只限现有 Grace CPU，NVDA → Google Cloud 只限已 GA 的 H100/DGX Cloud 部分。GEV → AWS 的新增站点、NBIS → Microsoft 的签约容量和 AAPL/TSMC 的 IC 计划都不能当作已交付。
2. **虚线并附状态**：NVDA → META 的 Blackwell/Rubin 数百万颗计划、NVDA → Google Cloud 的 Grace Blackwell 采用、NBIS → Microsoft 的已签协议、AWS → GEV 的云迁移支持、NVDA → ADBE 的联合开发、V — AWS 的拟上架/蓝图、AAPL — TSMC 的三方制造计划。
3. **合作/集成线与供应边分开**：CSCO、VZ、SAP、IBM、TWLO、TRI、AAPL—TXN；TEAM—AWS 只画平台/渠道合作，除非补到可核实的运行/采购证据。暂移出「已核实」可视边：ETN—NVDA、MU—NVDA、HUBS—OpenAI、PANW—Google Cloud、PLTR—Anthropic/AWS、DELL—NVDA。保留为「待核实」列表和原 URL，不能静默删除。
4. 双向索引去重：TSM/NVDA、NVDA/META、NVDA/GOOGL、NVDA/NBIS、AAPL/TXN 是**每对一条事实**，不应按工作簿行数计算边数；CRM/AWS 例外，两种产品方向不同，应画两条并标注供应物。

截至本轮，26 行可直接确认或限定性确认，6 行因来源不可读或正文缺失不能复核。分类基于该公告自身的时间语态；公告之后是否履约，需另查更新的官方证据。
