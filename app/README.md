# qb

`qb` 是从 `quant1` 蒸馏出来的单体本地 App，运行时不依赖 `quant1` 包或它的后端服务。

导航已收口为 **6 个全屏台（desk）+ 冻结的回测详情页**（旧的分散页——回测列表/对比/数据中心/策略索引/工坊/IDE/交易/实验/训练——都已搬进对应台，旧路由仍保留为重定向，防外部直链 404）：

- 总览台 `/overview`（含回测列表 / 对比分析 / 数据中心子视图）
- 策略台 `/strategy`（工坊 / IDE / 模板）
- 因子台 `/factors`
- Model 台 `/models`（实验 / 训练）
- 模拟台 `/paper`（原交易）
- Agent 工作台 `/agent-workbench`（原对话 / IDE agent）
- 回测详情 `/runs/{run_id}`（GOAL §M15 冻结的 jq-* SPA，唯一冻结例外）
- 首页 `/` 与社区 / 设置 / 定价走通用 Shell

## 当前目录形态

根目录只保留薄启动壳和数据文档：

- `app/`: 真正的应用代码与启动编排
- `data/`: 行情数据与回测产物
- `docs/`: 协议文档
- `package.json`: 根目录薄转发
- `start.sh`（macOS / Linux）
- `start-qb.ps1` / `start-qb.bat`（Windows）
- `start-qb.js`（跨平台分发器）

真正的服务在：

- `app/backend/`: FastAPI 后端
- `app/frontend/`: 统一的 `qb` 前端
- `app/start.sh`: macOS / Linux 启动脚本
- `app/start-qb.ps1`: Windows 启动脚本
- `app/start-qb.js`: 跨平台分发器（`npm run dev` 走它，按平台选上面对应脚本）

## 一键启动

首次使用先安装依赖。

**macOS / Linux**

```bash
cd app/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd ../frontend
npm install
cd ../..
```

**Windows (PowerShell)**

```powershell
cd app\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

cd ..\frontend
npm install
cd ..\..
```

之后回到项目根目录直接启动（**三大平台同一条命令**）：

```bash
npm run dev
```

`npm run dev` 会自动按平台分发：macOS / Linux → `app/start.sh`，Windows → `app/start-qb.ps1`。
也可绕过 npm 直跑：

- macOS / Linux：`bash app/start.sh`
- Windows：双击 `start-qb.ps1` / `start-qb.bat`

**前端**在当前终端前台运行；**后端在后台运行**。按 `Ctrl+C` 结束前端：macOS / Linux 上 `start.sh` 会一并收掉后端；Windows 上后端进程仍在，需在任务管理器中结束对应 Python/uvicorn。

> `start.sh` 启动时会自动 `mkdir -p ~/.quantbt`，全新机不会因缺目录失败。

默认地址：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`

## 页面路由

**当前台（canonical）**：

- `/overview`: 总览台（回测列表 / 对比分析 / 数据中心子视图）
- `/strategy`: 策略台
- `/factors`: 因子台
- `/models`: Model 台
- `/paper`: 模拟台
- `/agent-workbench`: Agent 工作台
- `/runs/{run_id}`: 回测详情（冻结页）

**旧路由（自动重定向到上面的台，兼容外部直链）**：`/runs`→`/overview`、`/compare`→`/overview?view=compare`、`/data`→`/overview?view=data`、`/strategies`→`/overview?view=runs`、`/workshop`·`/ide`·`/templates`→`/strategy`、`/chat`·`/agent`→`/agent-workbench`、`/trading`→`/paper`、`/experiments`·`/training`→`/models`。

## 数据目录约定

行情数据统一写入根目录 `data/` 下的 CSV：

- K 线类：`data/{market}/{data_kind}/{interval}/{symbol}.csv`
- 其他按标的分文件的数据：`data/{market}/{data_kind}/{symbol}.csv`
- 无标的的全量数据：`data/{market}/{data_kind}/dataset.csv`

每个回测固定放在：

- `data/artifacts/experiments/{run_id}/`

最少文件：

- `run.json`
- `portfolio.csv`

常用可选文件：

- `trades.csv`
- `positions.csv`
- `report.md`
- `backtest.log`
- `strategy.py`
- `series/{series_name}.csv`
- `attribution.csv`

完整协议见 `docs/backtest-run-format.md`。

**完整版（字段全集 + Python 导出函数 + Notebook 与详情页对照模板）**：`app/backend/qb_backtest_complete_guide.py`（在项目根执行 `python app/backend/qb_backtest_complete_guide.py` 可打印路径与代码模板）。

## 演示样例

仓库现在自带两个可直接查看的样例：

- `data/artifacts/experiments/demo/`
- `data/artifacts/experiments/quant1-demo/`

其中 `quant1-demo` 是从 `quant1` 的真实 run 转换过来的，方便你直接看整体效果。

建议直接打开：

- `http://127.0.0.1:5173/overview`（总览台：回测列表 / 对比分析入口）
- `http://127.0.0.1:5173/runs/quant1-demo`（回测详情冻结页）

如果要重新生成这个演示样例，可以运行：

```powershell
python app\backend\convert_quant1_demo.py
```

## Jupyter 研究与详情页对齐

- **API 参考手册**：`docs/api-reference.md`（函数签名、参数、返回值、异常、HTTP 契约）
- 速览：`docs/jupyter-run-detail.md`
- **页顶聚宽风格指标 `jq_overview_metrics`（不必写进 run.json、Notebook 怎么取）**：`docs/jq-overview-metrics.md`
- 研究导出模块：`app/backend/run_detail_research_export.py`（与 Web「收益概述」行数据一致的 `build_overview_rows`、写盘 `export_run_bundle_for_detail`）
- 示例 Notebook：`docs/notebooks/qb_run_detail_research.ipynb`

## Notebook 原语

Notebook 原语位于：

- `app/backend/app/notebook_primitives.py`

典型导入方式：

```python
import sys
from pathlib import Path

project_root = Path.cwd()
sys.path.append(str(project_root / "app" / "backend"))

from app.notebook_primitives import (
    render_detail_bundle,
    plot_equity_overview,
    plot_metric_series,
    show_trades_table,
)

bundle = render_detail_bundle("quant1-demo")
plot_equity_overview("quant1-demo").show()
plot_metric_series("quant1-demo", "alpha").show()
show_trades_table("quant1-demo").head()
```

## 环境变量

- `TUSHARE_TOKEN`: Tushare token，A 股 / 港股 / 美股 / 指数 / 基金 / 债券数据使用
- `BACKTEST_DATA_ROOT`: 可选，自定义 `data` 根目录；默认仍是项目根目录下的 `data`
