# finance-data-collector
Finance Data Collector

## SEC filing research page

The local research page moves from a company filing timeline to reported
statements, disclosures, and exact source evidence. It reads persisted parser
output only; the browser does not recompute financial values.

```bash
uv sync
docker compose up -d postgres
export FDC_DATABASE_URL='postgresql+psycopg://fdc:fdc@localhost:5432/fdc'
export FDC_SEC_ROOT="$PWD/sec"
export FDC_SEC_USER_AGENT='Collector name@example.com'
alembic upgrade head
uv run fdc parse filings --ticker MSFT
uv run uvicorn fdc.api:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/company.html?ticker=MSFT`. The API and static page
share the same origin. See [the parser runbook](docs/runbook.md) for archive
prerequisites, scoped parsing, forced/versioned reparses, deterministic tests,
and optional PostgreSQL/live SEC checks.

## AI 产业分层（`web/data/companies.json`）

`web/data/companies.json` 是 AI 产业链 universe 的唯一数据源：

- `layers`：有序分层（上游 → 下游），每层声明自己的 `segments`（细分环节）
- `companies`：每行声明 `layer` + `segment`，可选 `also_in`（跨层角色的层 id 数组）
- `sector` / `industry` 使用 GICS 标签，`description` 是节点卡片文案

| 层 id | 分层 | 细分环节 | 公司数 |
| --- | --- | --- | --- |
| `power` | 能源与电力 | 数据中心电力与温控 / 发电与核电 / 电网与工程 | 16 |
| `silicon` | 芯片与半导体 | 算力芯片 / 存储 / 模拟电源 / 晶圆代工 / 设备材料 / EDA 与 IP / 光互连 | 55 |
| `infra` | 算力基础设施与云 | 云与超大规模 / GPU 算力租赁 / AI 服务器 / 数据中心网络 / 电信与连接 | 40 |
| `model` | 模型与数据平台 | 基础模型 / 数据云与 MLOps / AI 开发平台 | 9 |
| `app` | AI 软件与应用 | 企业软件与 Agent / 广告营销 / 安全与身份 / 消费内容 / IT 服务 / 金融 AI / 医疗 AI / 客服 / 开发工具 / 法律科技 / 垂直 SaaS / 国防政府 | 79 |
| `edge` | 终端与具身智能 | 端侧设备 / 自动驾驶与机器人 | 12 |

构建与查看：

```bash
uv run python -m fdc.ai_layers                 # 校验分层契约 -> web/data/layers.json（树状 JSON）
uv run python -m fdc.ai_layers --tree          # 终端 ASCII 树
uv run python -m fdc.ai_layers --mermaid       # Mermaid graph，可直接粘进文档
uv run python -m fdc.ai_layers --enrich-graph  # 把 layer/segment 写回 graph.json，并校验图与 universe 对齐
uv run python -m fdc.graph                     # 3D 关系图数据（首次需联网：10-K 互提及 + 13F 共持边）
uv run python -m fdc.graph --offline           # 完全离线：只算行业边
uv run python -m fdc.graph --refresh-cache     # 忽略 sec/.cache/efts，重新抓 EDGAR

uv run python -m http.server -d web 8000
# http://localhost:8000/layers.html  AI 分层：分层图（按层分列 + 跨层虚线）/ 树状图 / Mermaid
# http://localhost:8000/             3D 公司关系图（行业 / 分层着色）
```

构建脚本同时写出 `data/<name>.json` 与 `data/<name>.js`（脚本垫片），所以直接双击
`web/layers.html` / `web/index.html` 也能打开：`file://` 下浏览器禁止 `fetch()`，页面会自动
改用 `<script>` 垫片读取数据，无需起本地服务器。

`tests/unit/test_ai_layers.py` 覆盖分层契约校验（未知层、未声明细分、重复 ticker、空环节）与
树 / ASCII / Mermaid 渲染，全部离线运行。`tests/unit/test_graph.py` 用桩 EFTS 响应覆盖 10-K
互提及解析、13F 阈值与互选裁剪、EFTS 缓存读写与 `--refresh-cache`，并复检已落库的 `graph.json`
单点度数 ≤ 5。

`graph.json` 与 universe 的对齐由 `fdc.ai_layers.audit_graph` 守住：universe 扩过标的但没重跑
`fdc.graph` 时，`--enrich-graph` 会列出 `missing` / `stale` ticker 并以非零码退出（旧图不能悄悄
上线），`test_real_graph_matches_universe` 用同一个审计函数在 CI 里复检；确实要原样查看旧图时加
`--allow-stale-graph`。

行业边按"最细可用桶"生成：先按 GICS `(sector, industry)` 建 K 近邻网格；桶里只剩自己时降级到
`(layer, segment)`、再降级到 `layer`，在每个桶都落单的公司（KEYS 独占一个 GICS 行业）连到同层
名字最近的 K 家 —— 实测 449 条行业边、211 家公司全部有边（修复前 6 家孤立：
PWR / AES / KEYS / FVRR / TCOM / TRI），全图 676 条边、度数中位数 6。
`test_real_graph_leaves_no_node_isolated` 守住这一点。

三类边里 13F 共同持仓是噪音最重的一族：EFTS 按名字命中 13F-HR 申报人，任何两个大盘标的都会被
同一批指数型机构"共同持有"（211 家实测 7524 条边，权重中位数 3、最大 19，93% 是噪声）。所以
默认只保留共享 ≥8 家机构的配对，再裁到每个公司最强的 5 个**互选**伙伴
（`--cohold-min-shared` / `--cohold-neighbors`，0 = 不裁剪）：实测 211 家 → 274 个候选对、
裁剪后 133 条、去重行业边后落库 124 条，单点最大度 5、权重 8–19，头部边是可解释的共持簇
（DOCU–ZM 19、WULF–HUT 17、WULF–IREN 16、BILI–PDD 15、NVDA–META 14）。
`test_real_graph_cohold_edges_respect_the_cap` 守住这个形状。

EFTS 响应缓存在 `sec/.cache/efts/`（随 `sec/` 一起不进 Git），所以重跑 `fdc.graph` 秒级完成、
改阈值调参完全离线，要重新抓 EDGAR 才加 `--refresh-cache`。

## Local SEC Data

SEC filing packages are centralized under `sec/<company>/`. The directory is
local-only and excluded from Git because the filing archive is several
gigabytes. Research projects read this canonical store directly and do not keep
local `company/<company>/sec` directories.

The SEC download skill writes new ticker data to `sec/<TICKER>/` and keeps its
metadata cache in `sec/.cache/`.
