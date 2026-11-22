# 公司质量评分（Quality Score）设计

日期：2026-11-17  
状态：待用户复核  
来源规则：`finance-stastic` 的 CQ_V2，最新现成快照 `cq-edgartools-rating-snapshot-2026-10-05-cqv2-v4`（评分截止日 2026-09-30）

## 目标与边界

将公司质量评分能力迁入 `finance-data-collector`，使本项目能够基于财务事实重新计算评分、为每次计算保存一份快照，并通过 API 和公司详情页展示评分与解释。首次上线只迁入该源快照中与本项目公司目录匹配的公司，不导入整个 480 家 universe。

数据库只保存计算结果、评分解释及快照元信息；不把源年度财务事实、同业排名中间量或规则定义写入数据库。计算所需年度事实文件作为受版本控制的数据输入放在项目数据目录；原始事实仍保留在输入文件中，而不是评分表中。以后每次重算形成新快照，不覆盖旧快照。

不包含：重建 SEC/XBRL 原始事实抽取流程、导入源项目全部 480 家公司、回测与历史评分重建、评分规则编辑 UI、手工覆盖评分。

## 现有依据

- 当前项目使用 SQLAlchemy 与 Alembic，目录数据由 `data/ai_companies.json` 提供，公司目录 API 位于 `src/fdc/api.py`，公司详情页由 `frontend/src/pages/company.ts` 驱动。
- `finance-stastic` 最新 CQ_V2 评分清单为 `../finance-stastic/data/company_quality/cq-edgartools-rating-snapshot-2026-10-05-cqv2-v4/rating_snapshots.csv.gz`。manifest 标明规则版本 `CQ_V2`、截止日 `2026-09-30`、行业 peer key `gics_sector`、peer minimum 10、语义策略 `CQ_EDGARTOOLS_SEMANTIC_POLICY_V2`；共 480 家，其中 350 家 `score_available`。
- 该评分以 revenue growth、operating margin、cash conversion、capital efficiency、financial strength 五个行业排名维度构成质量分；通过 CQ_V2 五年连续性、现金流支持、净负债/EBITDA、利息覆盖等硬门槛，并包含 `QUALIFIED`、`NOT_QUALIFIED`、`UNKNOWN`、`SEPARATE_MODEL` 等状态。
- 年度事实输入位于 `../finance-stastic/data/company_quality/cq-edgartools-annual-facts-2026-10-05-v2/edgartools_annual_facts.csv.gz`，约 7.4 MB。规则实现依赖 Pandas/NumPy 及源项目模块；迁移时需提取必要计算代码并使用本项目现有依赖，避免运行时依赖兄弟仓库路径。

## 数据模型

新增独立表 `company_quality_score`，以 UUID 为主键；关联公司使用规范 ticker 与 CIK（如存在），不对当前 `issuer` 做强制外键依赖，因为目录公司未必已摄取 SEC filing。记录字段至少包括：

- `ticker`、`cik`、`company_name`、`sector`：稳定识别与该次快照的展示信息。
- `rating_cutoff`、`calculated_at`、`snapshot_id`、`rule_version`、`semantic_policy`：快照时间与模型可追溯信息。
- `quality_score`（允许为空）、`score_available`、`status`、`dimension_count`、`peer_count`、`period_ends`。
- 五个维度分数：`revenue_growth_dimension`、`operating_margin_dimension`、`cash_conversion_dimension`、`capital_efficiency_dimension`、`financial_strength_dimension`。
- 解释字段：`unknown_reasons`、`v2_hard_status`、`v2_unknown_reasons`、通过门槛数/门槛总数，以及关键门槛指标（净负债/EBITDA、利息覆盖、累计净利润/CFO、正经营利润年数、正 CFO 年数）。

每次 run 的 ticker 唯一，允许同一 ticker 有多次历史记录。使用唯一约束 `(snapshot_id, ticker)` 防止一次评分意外重复写入；查询“最新评分”时按 `calculated_at`、`rating_cutoff` 排序。快照采用同一 run 的统一 `snapshot_id` 与统一 `calculated_at`。分数和比率使用数据库 Numeric/Decimal 类型，解释列表以 JSON 或兼容 SQLite/PostgreSQL 的文本结构保存，遵循现有模型约定。

首次导入标记为源 run `cq-edgartools-rating-snapshot-2026-10-05-cqv2-v4`，`calculated_at` 使用导入时间，`rating_cutoff` 保留源日期。对照 CIK/ticker 后，只导入本项目目录中的公司；目录公司未在源 snapshot 出现时不伪造记录。

## 计算与快照流程

1. 将年度事实 CSV 输入复制到本项目受管理的数据目录，并记录来源、SHA-256、事实快照版本及使用的规则版本，保证可重算。规则代码与应用一同维护在 `src/fdc`，不在执行时动态导入兄弟仓库。
2. 读取输入年度事实与目录 universe，按源 CQ_V2 实现完成事实窗口筛选、五维计算、行业 peer 排名和硬门槛判定。目录公司范围使用本项目 catalog；peer ranking 的候选范围/peer 组成需与源模型保持一致：若源评分以 480 家完整 S&P 500 universe 排名，计算时仍须纳入这 480 家作为计算 peer，只将本项目 234 家目录公司结果写入 DB。此项为正确性要求，不能仅在 234 家目录公司内部重排。
3. 校验输入列、关键维度/状态、非有限数值和公司匹配；缺失数据按规则产出 UNKNOWN 或不可用分数，不以 0 代替。失败时不写入半套快照。
4. 在单一事务中写入该 run 的公司评分快照；重复运行同一 `snapshot_id` 应幂等（冲突则拒绝或整体替换该 run，不允许重复行）。后续重算使用新 snapshot ID，不改既有历史。
5. Alembic migration 只建表与索引；历史数据通过显式导入/评分 CLI 任务写入，不在 schema migration 中嵌入大批评分数据。

## API 与 UI

- 新增 `GET /api/v1/companies/{ticker}/quality-score`，返回该公司的最新评分快照：分数、状态、维度、评分日期/规则版本和解释。无记录返回明确的 404/无评分状态，不影响公司详情页其他内容。
- 可选增加目录响应中的最新评分摘要仅在现有列表表格确实需要排序/展示时采用；首版以详情页读取单公司 API 为主，避免把评分字段塞进全部目录响应。
- 公司详情页新增 Quality Score 区块：显示总分及可用性、状态、各维度分数、硬门槛结果、未知/缺失原因、评分截止日和规则版本。UNKNOWN/SEPARATE_MODEL/无记录应有明确文字状态，不显示为零分。
- 前端沿用现有页面 API 请求与组件/样式结构；不新增依赖。

## 失败处理与可追溯性

缺失/损坏输入、必需列不符、ticker/CIK 冲突、peer universe 不足或计算中断时，任务应返回非零错误并保持数据库不变。数据库写入使用事务。API 对缺失评分返回明确响应，评分查询失败不能导致公司主体资料加载失败。每次快照保存来源事实集标识/哈希、规则版本、截止日和语义策略，便于解释“为什么得到此分数”。

## 验证

- 对源 `CQ_V2` 快照执行黄金样本校验：对至少若干个不同状态的 ticker 比对五维分数、总分、状态、门槛数和 unknown reasons；另比对目录范围匹配数及源行数。
- 单测覆盖维度计算/缺失输入/硬门槛状态/同业排名边界，以及 ticker/CIK 公司匹配。
- 数据库测试覆盖 migration、SQLite/PostgreSQL 兼容模型、同一快照唯一性、不同快照保留历史、事务失败不产生半套行、最新快照查询。
- API 测试覆盖成功、无评分、未知 ticker 和字段 schema；前端测试覆盖有分数、UNKNOWN、SEPARATE_MODEL、无记录及 API 失败状态。
- 运行相关后端/前端测试与生产构建。

## 需要在实施前定案的技术点

1. peer 排名 universe：保持源 480 家 universe，评分入库仅筛本项目目录公司；不可用目录 234 家重算排名。执行导入时需要将源 universe 一并作为计算输入或直接验证源输出快照，并将计算输入保存在项目中。
2. Python 依赖：检查当前 `pyproject.toml` 中 pandas/numpy 可用性；优先复用现有依赖。若没有，考虑纯 Python 最小实现还是增加依赖，需以当前部署包体和 source 算法等价性测试决定。
3. 公司详情 API 的路径风格要与当前 `/api/v1/companies` 实际路由协调；目前目录 endpoint 为复数集合，应采用 `/api/v1/companies/{ticker}/quality-score` 并做 ticker 标准化。
