# qb API 参考手册

本文档为 **API 参考手册** 级别：函数签名、参数、返回值、异常、与 HTTP 的对应关系，以及核心 JSON 结构。
**磁盘文件与字段契约**的扩展说明见 [backtest-run-format.md](./backtest-run-format.md) 与 [`app/backend/qb_backtest_complete_guide.py`](../app/backend/qb_backtest_complete_guide.py)。

---

## 目录

1. [约定](#1-约定)
2. [Python：`app.notebook_primitives`](#2-pythonappnotebook_primitives)
3. [Python：`run_detail_research_export`](#3-pythonrun_detail_research_export)
4. [Python：`app.run_detail_core`（Notebook 常用）](#4-pythonapprun_detail_corenotebook-常用)
5. [数据类型与序列契约](#5-数据类型与序列契约)
6. [HTTP：回测与 Run 相关接口](#6-http回测与-run-相关接口)
7. [附录：其他 HTTP 端点一览](#7-附录其他-http-端点一览)

---

## 1. 约定

| 项 | 说明 |
|----|------|
| 默认后端地址 | `http://127.0.0.1:8000`（以实际启动为准） |
| 数据根目录 | 默认 `{项目根}/data/`；环境变量 `BACKTEST_DATA_ROOT` 可覆盖整个 `data` 等价根 |
| Run 目录 | `{DATA_ROOT}/artifacts/experiments/{run_id}/` |
| Notebook 导入 | 将 `app/backend` 加入 `sys.path` 后：`from app.notebook_primitives import ...`；根目录模块：`import run_detail_research_export`（工作目录或路径需包含 `app/backend`） |

---

## 2. Python：`app.notebook_primitives`

模块路径：`app/backend/app/notebook_primitives.py`。
所有函数在 **run 目录不存在或缺少 `run.json`** 时，行为与后端 `load_run` 一致：通常抛出 **`FileNotFoundError`**（与直接调 `run_detail_core` 相同）。

### 2.1 `load_run_context`

```text
load_run_context(run_id: str) -> dict[str, Any]
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `run_id` | `str` | 与目录名一致 |

| 返回值 | 说明 |
|--------|------|
| `dict` | 与 `get_run_detail(run_id)` 完全相同，见 [§4.3](#43-get_run_detail) |

| 异常 | 条件 |
|------|------|
| `FileNotFoundError` | run 目录或清单不存在 |

**说明**：无额外逻辑，即 `get_run_detail` 的别名式封装。

---

### 2.2 `build_metric_cards`

```text
build_metric_cards(run_id: str) -> list[NotebookMetricCard]
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `run_id` | `str` | run 标识 |

| 返回值 | 说明 |
|--------|------|
| `list[NotebookMetricCard]` | Pydantic 模型列表，字段见 [§5.2](#52-notebookmetriccard--notebookbundle) |

**指标键**（固定顺序，来自模块内 `METRIC_CARD_SPECS`）：`total_return`、`annualized_return`、`max_drawdown`、`sharpe`、`sortino`、`alpha`、`beta`、`trade_count`。
取值优先 `run["metrics"][key]`，否则回退顶层 `run.get(key)`。

**等价 HTTP**：无单独端点；数据来自 `GET /api/runs/{run_id}` 的合并视图。

---

### 2.3 `plot_equity_overview`

```text
plot_equity_overview(run_id: str) -> plotly.graph_objects.Figure
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `run_id` | `str` | run 标识 |

| 返回值 | 说明 |
|--------|------|
| `go.Figure` | 单图叠加：策略净值、基准、`turnover`（若有）；**不是**浏览器「收益概述」三联子图布局 |

**依赖序列**：内部对 `equity`、`benchmark_return`、`turnover` 各调用 `load_series_response` 后转 DataFrame。

---

### 2.4 `plot_metric_series`

```text
plot_metric_series(run_id: str, series_name: str) -> plotly.graph_objects.Figure
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `run_id` | `str` | run 标识 |
| `series_name` | `str` | 与 `load_series_response` 的序列名一致，见 [§5.1](#51-序列名-run_series_columns-与-seriespoint) |

| 返回值 | 说明 |
|--------|------|
| `go.Figure` | 单条折线：`x=timestamp`，`y=value` |

---

### 2.5 `show_trades_table`

```text
show_trades_table(run_id: str) -> pandas.DataFrame
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `run_id` | `str` | run 标识 |

| 返回值 | 说明 |
|--------|------|
| `DataFrame` | `load_table_response(..., "trades", limit=100000, offset=0, sort="execution_timestamp", order="desc")["rows"]` 的表格化结果 |

**等价 HTTP**：`GET /api/runs/{run_id}/tables/trades`（参数等价于上述固定值）。

---

### 2.6 `show_positions_table`

```text
show_positions_table(run_id: str) -> pandas.DataFrame
```

与 `show_trades_table` 相同，但 `table_name="positions"`，`sort="execution_timestamp"`，`order="asc"`。

**等价 HTTP**：`GET /api/runs/{run_id}/tables/positions`。

---

### 2.7 `show_logs`

```text
show_logs(run_id: str) -> pandas.DataFrame
```

| 返回值 | 说明 |
|--------|------|
| `DataFrame` | `get_run_logs(run_id, limit=100000, offset=0)["entries"]` |

列结构：`timestamp` / `level` / `message`（见日志文件解析逻辑）。

**等价 HTTP**：`GET /api/runs/{run_id}/logs`（limit/offset 不同，本函数拉取更大窗口）。

---

### 2.8 `show_report`

```text
show_report(run_id: str) -> str
```

| 返回值 | 说明 |
|--------|------|
| `str` | `load_run(run_id).report_markdown`，无文件时为空字符串 |

---

### 2.9 `show_strategy_source`

```text
show_strategy_source(run_id: str) -> str
```

| 返回值 | 说明 |
|--------|------|
| `str` | `get_run_source(run_id)["content"]` |

**等价 HTTP**：`GET /api/runs/{run_id}/source` 中的 `content`。

---

### 2.10 `show_attribution`

```text
show_attribution(run_id: str) -> pandas.DataFrame
```

| 返回值 | 说明 |
|--------|------|
| `DataFrame` | `get_run_attribution(run_id)["rows"]`；无 `attribution.csv` 时可能为空表 |

**等价 HTTP**：`GET /api/runs/{run_id}/attribution`。

---

### 2.11 `render_detail_bundle`

```text
render_detail_bundle(run_id: str) -> NotebookBundle
```

| 返回值 | 说明 |
|--------|------|
| `NotebookBundle` | 见 [§5.2](#52-notebookmetriccard--notebookbundle) |

**行为摘要**：

- `run`：`get_run_detail(run_id)`
- `metric_cards`：`build_metric_cards(run_id)`
- `available_series`：`RUN_SERIES_COLUMNS` 的全部键 + `daily_buy`、`daily_sell` 中，`load_series_response` 返回 `available=True` 的序列名
- `report_markdown`：`show_report(run_id)`
- `log_entries`：`get_run_logs(run_id, limit=2000, offset=0)["entries"]`

---

## 3. Python：`run_detail_research_export`

模块路径：`app/backend/run_detail_research_export.py`（与 `app` 包并列，需将 `app/backend` 加入路径）。

### 3.1 类型 `OverviewRow`

`TypedDict`（`total=False`，键均可选），与前端 `OverviewRow` 对应，**snake_case**：

| 键 | 类型 | 含义 |
|----|------|------|
| `date` | `str` | `YYYY-MM-DD` |
| `strategy_return` | `float \| None` | 策略累计收益（净值比首点归一后 −1） |
| `benchmark_return` | `float \| None` | 基准累计收益（点值 +1 为 NAV 后 −1） |
| `excess_daily` | `float \| None` | 策略日收益 − 基准日收益（与前端一致） |
| `turnover` | `float \| None` | 换手；无点则为 `None` |
| `daily_buy` | `float \| None` | 日买入额 |
| `daily_sell` | `float \| None` | 日卖出额 |

### 3.2 `build_overview_rows`

```text
build_overview_rows(
    equity_points: Sequence[SeriesPoint],
    benchmark_points: Sequence[SeriesPoint],
    turnover_points: Sequence[SeriesPoint],
    daily_buy_points: Sequence[SeriesPoint],
    daily_sell_points: Sequence[SeriesPoint],
) -> list[OverviewRow]
```

| 参数 | 说明 |
|------|------|
| 五组点列 | 每组为 `{"timestamp": str, "value": Any}` 的序列；`timestamp` 建议 ISO 字符串，日期取前 10 位 |

| 返回值 | 说明 |
|--------|------|
| `list[OverviewRow]` | 与 `RunDetailPage.tsx` 中 `buildOverviewRows` **逐行一致** |

**异常**：无显式抛出；非法数值经 `safe_number` 过滤。

---

### 3.3 `filter_overview_rows`

```text
filter_overview_rows(
    rows: Sequence[OverviewRow],
    start_date: str = "",
    end_date: str = "",
) -> list[OverviewRow]
```

字符串比较：`row["date"]` 与 `start_date`/`end_date` 字典序；空字符串表示不限制。

---

### 3.4 `plot_overview_three_panel_plotly`

```text
plot_overview_three_panel_plotly(
    rows: Sequence[OverviewRow],
    *,
    benchmark_label: str = "基准",
    title: str = "收益概述（近似 Web 三联）",
) -> plotly.graph_objects.Figure
```

| 异常 | 条件 |
|------|------|
| `ImportError` | 未安装 `plotly` |

---

### 3.5 `export_run_bundle_for_detail`

```text
export_run_bundle_for_detail(
    run_id: str,
    manifest: Mapping[str, Any],
    portfolio: pd.DataFrame,
    *,
    overwrite: bool = False,
    trades: pd.DataFrame | None = None,
    positions: pd.DataFrame | None = None,
    attribution: pd.DataFrame | None = None,
    report_md: str | None = None,
    strategy_py: str | None = None,
    log_text: str | None = None,
) -> pathlib.Path
```

| 参数 | 说明 |
|------|------|
| `run_id` | 目录名 |
| `manifest` | 写入 `run.json`；会 `setdefault("run_id", run_id)` |
| `portfolio` | **必填**；列要求见 `run_detail_core`（时间列 + `equity` 等），写入 `portfolio.csv` |
| `overwrite` | `False` 且目录已存在时 **不覆盖** |
| 其余 DataFrame | 非空则写入对应 `trades.csv` / `positions.csv` / `attribution.csv` |
| `report_md` / `strategy_py` / `log_text` | 非 `None` 则写入 `report.md` / `strategy.py` / `backtest.log` |

| 返回值 | 说明 |
|--------|------|
| `Path` | `{RUN_ROOT}/{run_id}/` |

| 异常 | 条件 |
|------|------|
| `FileNotFoundError` | 目录已存在且 `overwrite=False` |

**副作用**：调用 `ensure_runtime_dirs()`，保证 `DATA_ROOT`、`RUN_ROOT` 存在。

---

### 3.6 辅助函数（公开）

`normalize_equity_points`、`normalize_benchmark_points`、`build_date_axis`、`to_date_label`、`safe_number`：语义与前端同名函数一致，供校验或自定义组装。见源码与 [§5.1](#51-序列名-run_series_columns-与-seriespoint)。

---

## 4. Python：`app.run_detail_core`（Notebook 常用）

模块路径：`app/backend/app/run_detail_core.py`。

### 4.1 `load_run`

```text
load_run(run_id: str) -> LoadedRun
```

| 返回值 `LoadedRun` 字段 | 说明 |
|-------------------------|------|
| `run_id` | 字符串 |
| `manifest` | `run.json` 解析结果 |
| `portfolio` / `trades` / `positions` | Polars `DataFrame`，缺文件为空表 |
| `report_markdown` | `report.md` 全文或 `""` |
| `source_code` | `strategy.py` 全文或 `""` |
| `attribution` | `attribution.csv` 或空表 |
| `log_entries` | 解析后的日志行列表 |

---

### 4.2 `load_series_response`

```text
load_series_response(run_id: str, series_name: str, segment: str = "overall") -> dict[str, Any]
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `run_id` | `str` | 回显 |
| `series` | `str` | 回显 |
| `segment` | `str` | 回显（当前实现不拆分 segment，保留兼容） |
| `available` | `bool` | `points` 非空则为 `True` |
| `points` | `list[dict]` | 每项 `{"timestamp": ..., "value": float \| None}` |

**序列来源优先级**：

1. `daily_buy` / `daily_sell`：由 `trades.csv` 聚合（见 `_daily_trade_flow`）。
2. 其他：先读 `series/{series_name}.csv`（须含 `timestamp`、`value`）。
3. 若为空：从 `portfolio` 按 `RUN_SERIES_COLUMNS` 映射列派生；`drawdown` / `max_drawdown` 可自 `equity` 计算。

---

### 4.3 `get_run_detail`

```text
get_run_detail(run_id: str) -> dict[str, Any]
```

返回单页详情用的**大字典**（与 `GET /api/runs/{run_id}` 一致），主要包括：

- 标识：`run_id`、`strategy_name`、`strategy_id`、`started_at`、`status`、`record_name` …
- `metrics`：来自 manifest
- **`jq_overview_metrics`**：JoinQuant 风格「收益概述」指标块（服务层 `compute_jq_overview_metrics`），字段与页面 **固定顺序** 对齐；语义与计算见 [docs/jq-overview-metrics.md](./jq-overview-metrics.md)。**该对象不是从磁盘 `run.json` 解析的必填键**，每次 `get_run_detail` 在服务端现算；与三联图逐日数据、研究侧 `build_overview_rows` 的区别亦见该文档。
- `artifact_stats`、`series_available`、`artifact_dir`
- 大量顶层指标回退字段：`returns`、`sharpe`、`alpha` 等（内部 `_metric_value`）

完整键集以源码 `get_run_detail` 为准。

---

### 4.4 `load_table_response`

```text
load_table_response(
    run_id: str,
    table_name: str,
    *,
    limit: int = 200,
    offset: int = 0,
    sort: str | None = None,
    order: str = "desc",
    start_ts: str | None = None,
    end_ts: str | None = None,
    symbol: str | None = None,
    side: str | None = None,
) -> dict[str, Any]
```

| `table_name` | 文件 |
|--------------|------|
| `portfolio` | `portfolio.csv` |
| `trades` | `trades.csv` |
| `positions` | `positions.csv` |

| 返回字段 | 说明 |
|----------|------|
| `table_name` | 回显 |
| `available` | 原始表是否有行 |
| `columns` | 列元数据 |
| `rows` | 当前页行字典列表 |
| `total_rows` | 过滤后总行数 |

| 异常 | 条件 |
|------|------|
| `ValueError` | `table_name` 不在 `TABLE_FILE_NAMES` |

---

### 4.5 `get_run_logs` / `get_run_source` / `get_run_attribution`

```text
get_run_logs(run_id: str, limit: int = 500, offset: int = 0) -> dict[str, Any]
```

返回：`{"entries": list[dict], "total": int}`。

```text
get_run_source(run_id: str) -> dict[str, Any]
```

返回：`{"file_name": "strategy.py", "content": str}`。

```text
get_run_attribution(run_id: str) -> dict[str, Any]
```

无数据时：`available=False`，`message` 提示未提供文件；有数据时含 `rows`（`to_dicts()`）。

---

## 5. 数据类型与序列契约

### 5.1 序列名（`RUN_SERIES_COLUMNS`）与 `SeriesPoint`

内置序列名（键 → `portfolio` 列名或含义）：

| 序列名 | 列名 / 备注 |
|--------|-------------|
| `equity` | `equity` |
| `drawdown` | `drawdown` 或由 `equity` 派生 |
| `turnover` | `turnover` |
| `net_return` | `net_return` |
| `gross_return` | `gross_return` |
| `funding_return` | `funding_return` |
| `fee_cost` | `fee_cost` |
| `strategy_return` | 映射到 `net_return` |
| `benchmark_return` | `benchmark_return` |
| `alpha` … `max_drawdown` | 同名列 |

另支持 **`daily_buy`**、**`daily_sell`**（来自成交聚合，非 `RUN_SERIES_COLUMNS` 映射）。

**`SeriesPoint`**（本文档用语）：`{"timestamp": str, "value": float | None}`。

**`portfolio` 时间列识别**（用于派生序列）：按序匹配首列存在者：`execution_timestamp`、`timestamp`、`trade_date`、`date`、`ann_date`、`cal_date`。

---

### 5.2 `NotebookMetricCard` / `NotebookBundle`

定义于 `app/schemas.py`。

**`NotebookMetricCard`**：`key`、`label`、`value`、`format`（`"pct"` \| `"num"` \| `"text"`）。

**`NotebookBundle`**：

| 字段 | 类型 |
|------|------|
| `run` | `dict[str, Any]` |
| `metric_cards` | `list[NotebookMetricCard]` |
| `available_series` | `list[str]` |
| `report_markdown` | `str \| None` |
| `log_entries` | `list[dict[str, Any]]` |

---

## 6. HTTP：回测与 Run 相关接口

以下前缀：`/api`，默认 **JSON** 响应；**404** 常见于 run 不存在。

### 6.1 `GET /api/runs`

| 响应 | 类型 |
|------|------|
| 200 | `list[dict]`，每项为列表行摘要（manifest 聚合） |

---

### 6.2 `POST /api/runs/query`

**请求体**：`RunQueryRequest`（Pydantic），主要字段：

| 字段 | 说明 |
|------|------|
| `search`、`favorite_only`、`strategy_mode`、`status`、`market`、`frequency`、`benchmark` | 筛选 |
| `dataset_version`、`universe_snapshot_id`、`model_used` | 可选 |
| `sort_by`、`sort_order`、`limit`、`offset` | 排序与分页 |
| `numeric_filters` | `{field, operator, value, value_to?}` 列表 |

**响应**：

```json
{
  "rows": [],
  "total_rows": 0,
  "available_filters": {
    "status": [],
    "market": [],
    "frequency": [],
    "benchmark": [],
    "strategy_mode": [],
    "dataset_version": [],
    "universe_snapshot_id": []
  }
}
```

---

### 6.3 `GET /api/runs/compare`

**Query**：`run_ids` 可重复，至少 1 个。

**响应**：`{"runs": [ ... manifest 行 ... ]}`（顺序与请求 `run_ids` 对齐）。

---

### 6.4 `GET /api/runs/compare/series`

**Query**：`run_ids`（多值）、`series`（必填）、`segment`（默认 `overall`）。

**响应**：含 `series`、`segment`、`runs`；每项含 `run_id`、`strategy_name`、`available`、`points`。

---

### 6.5 `DELETE /api/runs/{run_id}`

**响应**：`{"deleted": "<run_id>"}`；不存在 **404**。

---

### 6.6 `GET /api/runs/{run_id}`

**响应**：与 `get_run_detail(run_id)` 相同的大 JSON（含 **`jq_overview_metrics`**，见 [§4.3](#43-get_run_detail) 与 [jq-overview-metrics.md](./jq-overview-metrics.md)）。

**404**：run 不存在。

---

### 6.7 `GET /api/runs/{run_id}/series`

**Query**：

| 参数 | 默认 | 说明 |
|------|------|------|
| `series` | （必填） | 序列名，见 [§5.1](#51-序列名-run_series_columns-与-seriespoint) |
| `segment` | `overall` | 透传至响应 |

**响应**：与 `load_series_response` 相同。

---

### 6.8 `GET /api/runs/{run_id}/tables/{table_name}`

**路径**：`table_name` ∈ `portfolio` \| `trades` \| `positions`。

**Query**：`limit`（1–100000）、`offset`、`sort`、`order`、`start_ts`、`end_ts`、`symbol`、`side`。

**响应**：与 `load_table_response` 相同。

**400**：`ValueError`（如非法 table，由全局处理）。

---

### 6.9 `GET /api/runs/{run_id}/logs`

**Query**：`limit`（1–100000）、`offset`。

**响应**：`{"entries": [...], "total": n}`。

---

### 6.10 `GET /api/runs/{run_id}/source`

**响应**：`{"file_name": "strategy.py", "content": "..."}`。

---

### 6.11 `GET /api/runs/{run_id}/attribution`

**响应**：与 `get_run_attribution` 相同。

---

### 6.12 `GET /api/runs/{run_id}/artifacts/{artifact_name}/download`

**路径**：`artifact_name` ∈ `run`、`portfolio`、`trades`、`positions`、`report`、`tearsheet`、`strategy`、`log`、`attribution`。

**响应**：文件流（`FileResponse`）；**400** 非法 artifact；**404** 文件不存在。

---

### 6.13 `GET /api/runs/{run_id}/export/{export_type}`

**路径**：`export_type` ∈ `nav`（`portfolio.csv`）、`positions`、`trades`、`metrics`（`run.json`）。

**404**：路径不存在。

---

## 7. 附录：其他 HTTP 端点一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/data/markets` | 数据中心 |
| GET | `/api/data/kinds` | 数据中心 |
| GET | `/api/data/overview` | 数据中心 |
| GET | `/api/data/files` | 数据中心 |
| GET | `/api/data/preview` | 数据中心 |
| GET | `/api/jobs` | 任务列表 |
| GET | `/api/jobs/{job_id}` | 任务详情 |
| POST | `/api/jobs/{job_id}/retry` | 重试 |
| POST | `/api/jobs/{job_id}/cancel` | 取消 |
| POST | `/api/jobs/data/pull` | 拉取数据任务 |

详细请求/响应体以 `app/backend/app/main.py` 与对应 handler 为准。

---

*文档版本与后端源码同步；若行为不一致，以源码为准。*
