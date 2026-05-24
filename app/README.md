# qb

`qb` 是从 `quant1` 蒸馏出来的单体本地 App，运行时不依赖 `quant1` 包或它的后端服务。

现在统一包含 4 个页面：

- 回测列表
- 对比分析
- 数据中心
- 回测详情

## 当前目录形态

根目录只保留薄启动壳和数据文档：

- `app/`: 真正的应用代码与启动编排
- `data/`: 行情数据与回测产物
- `docs/`: 协议文档
- `package.json`: 根目录薄转发
- `start-qb.ps1`
- `start-qb.bat`

真正的服务在：

- `app/backend/`: FastAPI 后端
- `app/frontend/`: 统一的 `qb` 前端
- `app/start-qb.ps1`: 真正的启动脚本

## 一键启动

首次使用先安装依赖：

```powershell
cd app\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

cd ..\frontend
npm install
cd ..\..
```

之后回到项目根目录直接启动：

```powershell
npm run dev
```

或双击根目录：

- `start-qb.ps1`
- `start-qb.bat`

**前端**在当前终端前台运行（不另开 PowerShell 窗口）；**后端在后台运行，无单独窗口**。按 `Ctrl+C` 会结束前端，后端进程仍在，需在任务管理器中结束对应 Python/uvicorn。

默认地址：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`

## 页面路由

- `/runs`: 回测列表
- `/compare`: 对比分析
- `/data`: 数据中心
- `/runs/{run_id}`: 回测详情

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

- `http://127.0.0.1:5173/runs`
- `http://127.0.0.1:5173/runs/quant1-demo`
- `http://127.0.0.1:5173/compare`

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
