# finance-data-collector
Finance Data Collector

## AI 产业分层（`web/data/companies.json`）

`web/data/companies.json` 是 AI 产业链 universe 的唯一数据源：

- `layers`：有序分层（上游 → 下游），每层声明自己的 `segments`（细分环节）
- `companies`：每行声明 `layer` + `segment`，可选 `also_in`（跨层角色的层 id 数组）
- `sector` / `industry` 使用 GICS 标签，`description` 是节点卡片文案

| 层 id | 分层 | 细分环节 | 公司数 |
| --- | --- | --- | --- |
| `power` | 能源与电力 | 数据中心电力与温控 / 发电与核电 / 电网与工程 | 8 |
| `silicon` | 芯片与半导体 | 算力芯片 / 存储 / 模拟电源 / 晶圆代工 / 设备材料 / EDA 与 IP / 光互连 | 31 |
| `infra` | 算力基础设施与云 | 云与超大规模 / GPU 算力租赁 / AI 服务器 / 数据中心网络 / 电信与连接 | 19 |
| `model` | 模型与数据平台 | 基础模型 / 数据云与 MLOps / AI 开发平台 | 7 |
| `app` | AI 软件与应用 | 企业软件与 Agent / 广告营销 / 安全与身份 / 消费内容 / IT 服务 | 29 |
| `edge` | 终端与具身智能 | 端侧设备 / 自动驾驶与机器人 | 5 |

构建与查看：

```bash
uv run python -m fdc.ai_layers                 # 校验分层契约 -> web/data/layers.json（树状 JSON）
uv run python -m fdc.ai_layers --tree          # 终端 ASCII 树
uv run python -m fdc.ai_layers --mermaid       # Mermaid graph，可直接粘进文档
uv run python -m fdc.ai_layers --enrich-graph  # 把 layer/segment 写回 web/data/graph.json
uv run python -m fdc.graph                     # 3D 关系图数据（需联网：10-K 互提及 13F 共持边；universe 变更后重跑以对齐标的）

uv run python -m http.server -d web 8000
# http://localhost:8000/layers.html  AI 分层：分层图（按层分列 + 跨层虚线）/ 树状图 / Mermaid
# http://localhost:8000/             3D 公司关系图（行业 / 分层着色）
```

`tests/unit/test_ai_layers.py` 覆盖分层契约校验（未知层、未声明细分、重复 ticker、空环节）与
树 / ASCII / Mermaid 渲染，全部离线运行。

## Local SEC Data

SEC filing packages are centralized under `sec/<company>/`. The directory is
local-only and excluded from Git because the filing archive is several
gigabytes. Research projects read this canonical store directly and do not keep
local `company/<company>/sec` directories.

The SEC download skill writes new ticker data to `sec/<TICKER>/` and keeps its
metadata cache in `sec/.cache/`.
