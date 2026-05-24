# Jupyter 与回测详情页：原语函数、三联主图、研究导出

**完整 API 参考手册（函数签名、参数、返回值、HTTP 与 JSON 结构）**：[api-reference.md](./api-reference.md)。

**聚宽风格页顶指标块 `jq_overview_metrics`（是否要写进 run.json、Notebook 怎么取、与三联图区别）**：[jq-overview-metrics.md](./jq-overview-metrics.md)（建议先读该文再写分析脚本）。

本文档只保留**常用与易混点**；完整文件契约仍以 [backtest-run-format.md](./backtest-run-format.md) 与 [`app/backend/qb_backtest_complete_guide.py`](../app/backend/qb_backtest_complete_guide.py) 为准。

## 1. 三联主图（收益概述）在 Web 里如何组成

- 浏览器里**不是**三个独立 API，而是 **一个 ECharts option**：三个 `grid` + 联动 `dataZoom`，由前端 `buildOverviewRows` + `buildOverviewOption` 生成（源码：`app/frontend/src/pages/RunDetailPage.tsx`）。
- 输入数据来自 **5 条序列**（`/api/runs/{id}/series`）：
  - `equity`：净值曲线（首点归一）
  - `benchmark_return`：基准（点值 +1 再参与收益换算）
  - `turnover`：换手
  - `daily_buy` / `daily_sell`：日买入额 / 卖出额（可由 `trades.csv` 聚合）
- 研究侧若要与页面**逐日行数据一致**，使用 Python 模块 [`run_detail_research_export.py`](../app/backend/run_detail_research_export.py) 中的 **`build_overview_rows`**（逻辑与前端一致）。

### 1.1 页顶「聚宽风格」指标块 vs 三联图

- **页顶两排数字**（策略收益、基准收益、阿尔法、夏普等）：来自详情 JSON 的 **`jq_overview_metrics`**，由后端 **`compute_jq_overview_metrics`** 在每次 `get_run_detail` / `load_run_context` 时计算，**不要求**你在 `run.json` 里预先约定该字段。字段表与计算说明见 [jq-overview-metrics.md](./jq-overview-metrics.md)。
- **三联图**（折线 + 柱）：来自序列与 `buildOverviewRows` 的逐日行；Notebook 侧对齐用 **`build_overview_rows`**。这是**另一套数据**（按日），不要与 `jq_overview_metrics`（全样本汇总）混淆。

**在 Notebook 中取页顶同源的指标块：**

```python
from app.notebook_primitives import load_run_context

jq = load_run_context(run_id).get("jq_overview_metrics") or {}
```

仓库内 **`python app/backend/qb_backtest_complete_guide.py`** 打印的模板里也已包含与上一行等价的示例（见该模块的 `template_detail_functions`）。

## 2. Notebook 原语函数一览（`app/backend/app/notebook_primitives.py`）

| 函数 | 对应详情页区域 | 主要依赖文件 | 备注 |
|------|----------------|--------------|------|
| `load_run_context(run_id)` | 全局 JSON（指标、元数据） | 读整个实验目录，等价 `get_run_detail` | 返回体含 **`jq_overview_metrics`**（动态计算，见 [jq-overview-metrics.md](./jq-overview-metrics.md)） |
| `build_metric_cards(run_id)` | 概览区指标卡片 | `run.json` 的 `metrics` 等 | |
| `plot_equity_overview(run_id)` | 视觉上对应「收益概述」 | `portfolio.csv` / `series/*.csv` | **单张 Plotly 图**叠加净值/基准/换手，**布局≠ Web 三联子图**；**不**单独返回 `jq_overview_metrics`，需配合 `load_run_context` |
| `plot_metric_series(run_id, name)` | 侧栏各「指标页」 | 同上 | `name` 为 `strategy_return`、`alpha` 等 |
| `show_trades_table(run_id)` | 交易详情 | `trades.csv` | |
| `show_positions_table(run_id)` | 每日持仓 | `positions.csv` | |
| `show_logs(run_id)` | 日志输出 | `backtest.log` | |
| `show_report(run_id)` | Markdown 报告 | `report.md` | |
| `show_strategy_source(run_id)` | 策略代码 | `strategy.py` | |
| `show_attribution(run_id)` | 归因 | `attribution.csv` | |
| `render_detail_bundle(run_id)` | 打包摘要 | 上述综合 | 返回 `NotebookBundle` |

完整导出列表见源码 `__all__`。

## 3. 研究导出：内存 DataFrame → 详情页可读目录

模块：**[`app/backend/run_detail_research_export.py`](../app/backend/run_detail_research_export.py)**

| API | 作用 |
|-----|------|
| `OverviewRow`（TypedDict） | 与 Web「概览行」字段一致（snake_case） |
| `build_overview_rows(...)` | 五组序列 → 概览行列表 |
| `filter_overview_rows(...)` | 按日期区间筛选 |
| `export_run_bundle_for_detail(...)` | 写 `data/artifacts/experiments/{run_id}/` 下 `run.json`、`portfolio.csv` 及可选附件 |
| `plot_overview_three_panel_plotly(rows, ...)` | 可选：三行子图近似 Web 布局（仅可视化） |

## 4. 示例与 Notebook

- **单文件手册与导出示例**：[`qb_backtest_complete_guide.py`](../app/backend/qb_backtest_complete_guide.py)（`export_minimal_run`、`export_full_demo_artifacts`、打印 Notebook 模板字符串）。
- **交互 Notebook**：[`docs/notebooks/qb_run_detail_research.ipynb`](./notebooks/qb_run_detail_research.ipynb)（读原语、构造 overview、写盘）。

## 5. 环境变量

- `BACKTEST_DATA_ROOT`：覆盖默认的「项目根下 `data/`」；artifact 仍落在 `{DATA_ROOT}/artifacts/experiments/{run_id}/`。
