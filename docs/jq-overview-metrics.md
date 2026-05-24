# JoinQuant 风格「收益概述」指标（`jq_overview_metrics`）

查文档时的**推荐阅读顺序**：本文（字段与语义）→ [jupyter-run-detail.md](./jupyter-run-detail.md)（Notebook 里怎么取）→ [api-reference.md](./api-reference.md)（HTTP / 完整 JSON 形状）→ [backtest-run-format.md](./backtest-run-format.md)（磁盘文件契约）。

## 来源

- **计算入口**：`app/backend/app/jq_overview_metrics.py` 中 `compute_jq_overview_metrics(run)`。
- **API**：`get_run_detail` / `GET /api/runs/{run_id}` 响应字段 **`jq_overview_metrics`**（`snake_case` 对象）。
- **前端**：`app/frontend/src/jqOverviewSummary.ts` 中 `JQ_OVERVIEW_SUMMARY_DEFS` 定义 **固定顺序与中文标签**；页面只消费 `jq_overview_metrics`，不依赖对象键顺序。

## 磁盘 `run.json` 是否必须包含该字段？

**不必。** `jq_overview_metrics` 在 **`get_run_detail` 请求时由服务端根据已加载的 `LoadedRun` 动态计算**（读 manifest、`portfolio.csv`、`trades.csv` 等在内存中的结构），**不是**从磁盘 `run.json` 里解析出来的必填键。

- **Web 详情页**：浏览器调 API，响应里始终带有 `jq_overview_metrics`（在能加载该 run 的前提下）。
- **研究侧 `export_run_bundle_for_detail`**：写入的 `run.json` 仅包含你传入的 `manifest`；你可以**不**写 `jq_overview_metrics`。详情 API 仍会在读盘加载后重新计算。
- **若你手动把 `jq_overview_metrics` 写进 `run.json`**：当前实现仍以 **`compute_jq_overview_metrics` 的计算结果为准** 返回给前端，**不会**优先采用文件里手写的对象（避免与真实 portfolio 不一致）。

## 在 Notebook / Python 里怎么取（与页面顶部两排数字同源）

前提：已将 `app/backend` 加入 `sys.path`，且数据目录下存在该 `run_id` 的实验文件夹（见 [jupyter-run-detail.md](./jupyter-run-detail.md)）。

```python
from app.notebook_primitives import load_run_context

ctx = load_run_context(run_id)
jq = ctx.get("jq_overview_metrics") or {}
```

`load_run_context` 在实现上**等于** `get_run_detail(run_id)`（见 `notebook_primitives`），因此 `jq` 与 **`GET /api/runs/{run_id}`** 返回体中的 **`jq_overview_metrics`** 一致。字段含义与计算见下文「语义与计算说明」表。

## 与「三联图 / `build_overview_rows`」的区别

| 项目 | `jq_overview_metrics` | 三联图逐日数据（`buildOverviewRows` / `build_overview_rows`） |
|------|------------------------|---------------------------------------------------------------|
| 含义 | 全回测区间的**汇总指标块**（与页顶两排展示对应） | 每个交易日的行，用于折线/柱 + `dataZoom` |
| 是否随图表时间窗变化 | **否**（全样本统计） | **是**（图上是当前窗口；指标块仍显示全样本） |
| 研究侧 Python | `load_run_context(run_id)["jq_overview_metrics"]` | `run_detail_research_export.build_overview_rows(...)` |

## 语义与计算说明

| 字段 | 说明 |
|------|------|
| `strategy_return` | 策略总收益（小数）。优先 `manifest.metrics.strategy_return` / `total_return`，否则 `manifest.returns`。 |
| `strategy_annual_return` | 策略年化。`metrics.strategy_annual_return` / `annualized_return`。 |
| `benchmark_return` | 基准总收益。`metrics.benchmark_return` / `benchmark_total_return`。 |
| `excess_return` | 累计超额 \((1+R_s)/(1+R_b)-1\)；若策略/基准收益均存在则由此式计算，否则回退 `metrics.excess_return`。 |
| `alpha` … `daily_win_rate` | 自 `manifest.metrics` 映射（键名见源码 `mf(...)` 列表）。 |
| `avg_daily_excess_return` | 若有 `portfolio` 中日度 `net_return` 与 `benchmark_return`：为逐日 \(r_s-r_b\) 的均值；否则回退 `metrics`。 |
| `excess_max_drawdown` | 由日度超额序列构造超额财富曲线后的最大回撤（≤0）；否则回退 `metrics`。 |
| `excess_sharpe_ratio` | 日度超额均值 / 日度超额标准差 × \(\sqrt{252}\)（日度标准差用总体标准差）；否则回退 `metrics`。 |
| `max_drawdown_period` | 优先 `metrics.max_drawdown_period`；否则由 `portfolio` 的 `equity` 与日期列解析最大回撤对应的 **[峰日期, 谷底日期]**。 |
| `profit_count` / `loss_count` | 若 `trades` 存在 `realized_pnl`（或 `pnl` / `profit`）：按正负计数；否则回退 `metrics`。 |

**回测全区间 vs 图表可视区间**：`jq_overview_metrics` 表示 **整段回测/ manifest 统计区间** 的汇总指标；**不**随前端 `dataZoom` 日期窗口变化。图表窗口仅影响三联图与顶部「开始/结束日期」控件。

## 与主图工具栏的对应关系

- **主图三条折线**（策略 / 超额 / 基准）由 `portfolio` 与序列派生的 **逐日累计收益** 计算；**普通轴 / 对数轴** 在对数模式下主 Y 轴为 `1+收益率`（财富）取对数。
- **图例与「超额收益」勾选** 仅控制主图序列显隐，不改变 `jq_overview_metrics` 数值。

## 前端展示格式

- 比率类字段：百分比字符串（由 `formatPct` 格式化）。
- `max_drawdown_period`：展示为 `YYYY-MM-DD ~ YYYY-MM-DD`。
- 红涨绿跌（A 股习惯）：正偏指标为红色，负偏为绿色；最大回撤类负值为绿色强调。

## 一键打印的 Notebook 模板（仓库内）

运行 `python qb_backtest_complete_guide.py` 会打印路径与示例；其中 **`template_detail_functions`** 打印的字符串里包含 **`load_run_context(run_id)["jq_overview_metrics"]`** 片段，可与 `plot_equity_overview` 对照使用。完整契约仍以 [`app/backend/qb_backtest_complete_guide.py`](../app/backend/qb_backtest_complete_guide.py) 顶部文档字符串为准。
