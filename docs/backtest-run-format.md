# 回测详情协议与 Notebook 原语

**完整版（单文件：数据契约全集 + Python 导出模板 + 回测详情各功能与 Notebook 原语对照）**：[`app/backend/qb_backtest_complete_guide.py`](../app/backend/qb_backtest_complete_guide.py)（运行 `python qb_backtest_complete_guide.py` 可打印路径与 Notebook 代码模板）。

**Jupyter / 三联主图 / 研究侧导出（函数表、`build_overview_rows`、Notebook）**：[jupyter-run-detail.md](./jupyter-run-detail.md)。

**API 参考手册（Python 原语、`run_detail_research_export`、HTTP `/api/runs/*`）**：[api-reference.md](./api-reference.md)。

**聚宽风格页顶指标 `jq_overview_metrics`（不必写入 `run.json`、Notebook 如何读取、与三联图区别）**：[jq-overview-metrics.md](./jq-overview-metrics.md)。

`qb` 的回测列表、对比分析、回测详情和 Notebook 原语都是纯文件驱动：

- Web 页面不依赖数据库
- Notebook 原语不依赖前端组件
- Web 与 Notebook 共用同一套底层读取逻辑

根目录固定读取：

- `data/artifacts/experiments/{run_id}/`

## 一、页面功能与输入文件映射

| 页面功能 | 对应文件 | 缺失时行为 | Notebook 原语 |
|---|---|---|---|
| 收益概述 | `run.json` + `portfolio.csv`（`trades.csv` 用于成交笔数等）；**页顶指标块**由 API 动态计算字段 **`jq_overview_metrics`**（不必手写在 `run.json`） | 页面可打开，缺列时部分指标为「—」 | 指标块与三联图区别、代码示例： [jq-overview-metrics.md](./jq-overview-metrics.md)、[jupyter-run-detail.md](./jupyter-run-detail.md)；`load_run_context(run_id)["jq_overview_metrics"]` |
| 回测列表 | `run.json` | 该 run 不会出现在列表 | `load_run_context()` |
| 对比分析指标表 | `run.json` | 对比表信息不完整 | `build_metric_cards()` |
| 对比分析曲线 | `series/*.csv` 或 `portfolio.csv` | 缺列时退回派生逻辑，再缺则该序列无数据 | `plot_metric_series()` |
| 交易详情 | `trades.csv` | “暂无成交明细 artifact” | `show_trades_table()` |
| 每日持仓 | `positions.csv` | “暂无持仓明细 artifact” | `show_positions_table()` |
| 日志输出 | `backtest.log` | 空日志 | `show_logs()` |
| 策略代码 | `strategy.py` | 显示占位文本 | `show_strategy_source()` |
| Markdown 报告 | `report.md` | 显示占位文本 | `show_report()` |
| 归因 | `attribution.csv` | 显示“未提供 attribution.csv” | `show_attribution()` |

## 二、目录结构

```text
data/
  artifacts/
    experiments/
      {run_id}/
        run.json
        portfolio.csv
        trades.csv              # optional
        positions.csv           # optional
        report.md               # optional
        backtest.log            # optional
        strategy.py             # optional
        attribution.csv         # optional
        series/                 # optional
          strategy_return.csv
          benchmark_return.csv
          alpha.csv
          ...
```

## 三、核心文件协议

### 1. `run.json`

这是页面摘要、列表卡片和对比分析指标表的主清单。

最小可用示例：

```json
{
  "run_id": "demo_run",
  "strategy_id": "demo_strategy",
  "strategy_name": "Demo Strategy",
  "started_at": "2026-04-05T12:00:00Z",
  "status": "completed",
  "record_name": "第一次实验",
  "market": "stocks_cn",
  "frequency": "1d",
  "benchmark": "000300.SH",
  "metrics": {
    "total_return": 0.21,
    "annualized_return": 0.18,
    "max_drawdown": -0.09,
    "sharpe": 1.42,
    "sortino": 1.98,
    "alpha": 0.07,
    "beta": 0.83,
    "trade_count": 68
  }
}
```

回测列表和对比分析最常用字段：

- 顶层：`run_id`、`strategy_id`、`strategy_name`、`started_at`、`status`、`record_name`
- 顶层：`market`、`frequency`、`benchmark`
- `metrics`：`total_return`、`sharpe`、`max_drawdown`、`trade_win_rate` / `win_rate`、`turnover`

建议补充：

- `strategy_mode`
- `strategy_ref`
- `analysis_start`
- `analysis_end`
- `duration_seconds`
- `execution_profile`
- `execution_model`
- `instrument_type`
- `data_dependencies`
- `produced_outputs`
- `data_coverage_summary`
- `in_sample`
- `out_of_sample`
- `cost_breakdown`

说明：

- `metrics` 是概览卡片的主要来源
- 顶层字段会作为部分指标的回退来源
- 文件允许 UTF-8 with BOM，后端会兼容读取

### 2. `portfolio.csv`

这是最重要的时序文件。

最低要求：

- `timestamp`
- `equity`

推荐列：

- `timestamp`
- `equity`
- `net_return`
- `benchmark_return`
- `turnover`
- `drawdown`
- `alpha`
- `beta`
- `sharpe`
- `sortino`
- `information_ratio`
- `volatility`
- `benchmark_volatility`
- `max_drawdown`
- `funding_return`
- `fee_cost`

示例：

```csv
timestamp,equity,net_return,benchmark_return,turnover,drawdown,alpha,beta,sharpe,sortino,information_ratio,volatility,benchmark_volatility,max_drawdown
2026-01-01T00:00:00Z,100000,0.0000,0.0000,0.00,0.0000,0.0000,0.79,1.10,1.40,0.80,0.170,0.140,0.0000
2026-01-02T00:00:00Z,101200,0.0120,0.0050,0.12,0.0000,0.0070,0.79,1.20,1.55,0.92,0.171,0.141,0.0000
```

派生能力：

- 顶部收益概述图
- 对比分析中的净值和回撤曲线
- 回测详情中的净值 / 指标时序
- 当没有 `series/*.csv` 时，后端优先从这里派生 `drawdown` / `max_drawdown`

### 3. `trades.csv`

推荐列：

- `execution_timestamp`
- `symbol`
- `trade_side`
- `quantity`
- `price`
- `turnover`
- `realized_pnl`
- `estimated_fee`
- `delta_weight`
- `execution_model`
- `fee_rate`
- `estimated_slippage`

示例：

```csv
execution_timestamp,symbol,trade_side,quantity,price,turnover,realized_pnl,estimated_fee
2026-01-02T09:35:00Z,000001.SZ,buy,1000,12.30,12300,0,6.15
2026-01-08T10:20:00Z,000001.SZ,sell,1000,12.90,12900,600,6.45
```

### 4. `positions.csv`

推荐列：

- `execution_timestamp`
- `symbol`
- `row_kind`
- `quantity`
- `close_price`
- `market_value`
- `pnl`
- `side`
- `weight`
- `score`
- `selected_period_return`
- `gross_contribution`
- `funding_contribution`

### 5. `backtest.log`

普通文本日志，每行建议格式：

```text
2026-04-05 20:10:00 - INFO - Backtest started
2026-04-05 20:10:02 - INFO - Loaded 300 symbols
2026-04-05 20:12:20 - INFO - Backtest finished
```

### 6. `report.md`

Markdown 报告正文。

### 7. `strategy.py`

策略源码，可选；若存在会在“策略代码”页展示。

### 8. `series/{series_name}.csv`

如果你想覆盖页面默认的时序派生逻辑，可以显式提供单指标序列文件。

常用名称：

- `equity`
- `drawdown`
- `strategy_return`
- `benchmark_return`
- `alpha`
- `beta`
- `sharpe`
- `sortino`
- `information_ratio`
- `volatility`
- `benchmark_volatility`
- `max_drawdown`

统一格式：

```csv
timestamp,value
2026-01-01T00:00:00Z,0.01
2026-01-02T00:00:00Z,0.02
```

优先级：

1. 若存在 `series/{series_name}.csv`，页面和 Notebook 优先使用它
2. 否则尝试从 `portfolio.csv` 对应列读取
3. 若还没有，再尝试少量可推导逻辑

### 9. `attribution.csv`

可选。若存在会展示归因表。

推荐列：

- `label`
- `weight`
- `benchmark_weight`
- `portfolio_return`
- `benchmark_return`
- `allocation_effect`
- `selection_effect`
- `interaction_effect`
- `active_return`

## 四、Notebook 原语协议

Notebook 原语位于：

- `app/backend/app/notebook_primitives.py`

建议在 notebook 中这样导入：

```python
import sys
from pathlib import Path

project_root = Path.cwd()
sys.path.append(str(project_root / "app" / "backend"))

from app.notebook_primitives import (
    load_run_context,
    build_metric_cards,
    plot_equity_overview,
    plot_metric_series,
    show_trades_table,
    show_positions_table,
    show_logs,
    show_report,
    show_strategy_source,
    show_attribution,
    render_detail_bundle,
)
```

常用示例：

```python
bundle = render_detail_bundle("quant1-demo")
plot_equity_overview("quant1-demo").show()
show_trades_table("quant1-demo").head()
```

## 五、内置真实样例

当前仓库内置两个样例：

- `data/artifacts/experiments/demo/`
- `data/artifacts/experiments/quant1-demo/`

其中 `quant1-demo` 是从 `quant1` 的真实 run 转换到当前 `qb` 契约：

- 源目录：本机 `quant1` run，可通过环境变量 `QUANT1_DEMO_SOURCE_RUN` 指定
- 目标目录：`data/artifacts/experiments/quant1-demo/`

转换映射：

- `metrics.json` + 元信息 -> `run.json`
- `equity_curve.json` + `rolling_series.json` + `daily_portfolios.json` -> `portfolio.csv`
- `backtest.log` -> `trades.csv`
- `daily_portfolios.json` -> `positions.csv`
- `strategy.py`、`report.md`、`backtest.log` 原样带入

当前样例的降级点：

- 没有原生 `attribution.csv`，归因页会显示缺失占位
- 没有原生 `series/*.csv`，但 `portfolio.csv` 已覆盖对比与详情所需主要序列
- `trades.csv` 与 `positions.csv` 是根据源日志和每日组合做的 best-effort 转换，用于演示页面链路，不等同于原始撮合明细

## 六、建议工作流

1. 在 notebook 中完成策略回测。
2. 把结果写入 `data/artifacts/experiments/{run_id}/`。
3. 至少保证 `run.json` 和 `portfolio.csv` 存在。
4. 若你想让页面功能更完整，再补 `trades.csv`、`positions.csv`、`report.md`、`backtest.log`、`series/*.csv`、`attribution.csv`。
5. Web 页面和 Notebook 原语会同时可用。
