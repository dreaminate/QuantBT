# -*- coding: utf-8 -*-
r"""
================================================================================
qb 回测产物：完整数据契约 + Python 导出模板 + 回测详情 / Notebook 原语对照
================================================================================

本文件是唯一「完整版」说明：数据字段、文件路径、与页面功能、Notebook 函数的对应关系
均写在一起。可选字段在注释中标注「可无」，不设「推荐 / 不推荐」分级。

目录根（与 app/ 同级）下：

    data/artifacts/experiments/{run_id}/

若设置环境变量 BACKTEST_DATA_ROOT，则 {BACKTEST_DATA_ROOT}/artifacts/experiments/{run_id}/

-------------------------------------------------------------------------------
研究侧：与「收益概述」行数据对齐 + 一键导出（Python）
-------------------------------------------------------------------------------
- 模块：`app/backend/run_detail_research_export.py`（`build_overview_rows`、`export_run_bundle_for_detail`、可选 `plot_overview_three_panel_plotly`）。
- **API 参考手册（签名、参数、HTTP）**：`docs/api-reference.md`。
- 说明与 Notebook 示例：`docs/jupyter-run-detail.md`、`docs/notebooks/qb_run_detail_research.ipynb`。

-------------------------------------------------------------------------------
一、文件清单（每个 run 一个子目录 {run_id}）
-------------------------------------------------------------------------------

【必须】否则无法进入回测列表 / 详情
  - run.json
  - portfolio.csv（至少含后端用于派生曲线的列，见下文「portfolio.csv」）

【可无】缺失时对应页面显示占位或空
  - trades.csv          → 交易详情
  - positions.csv       → 每日持仓
  - backtest.log        → 日志输出（解析为 timestamp / level / message）
  - report.md           → Markdown 报告
  - strategy.py         → 策略代码
  - attribution.csv     → 归因表
  - series/*.csv        → 覆盖默认派生；每个文件两列 timestamp,value
  - tearsheet.html      → 仅用于 artifact 统计「是否存在」

-------------------------------------------------------------------------------
二、run.json（UTF-8，允许 BOM）
-------------------------------------------------------------------------------

整份 JSON 会作为 manifest 读取。下列字段按「后端 / 列表 / 详情」实际读取范围列出；
标注「可无」表示缺省仍可运行，对应 UI 显示 n/a 或空。

【标识与展示 — 建议都填】
  run_id: str                    # 必须与目录名 {run_id} 一致
  strategy_id: str               # 可无，缺则用 run_id
  strategy_name: str
  started_at: str                # ISO-8601 字符串
  status: str                    # 如 completed / running / failed
  record_name: str | null       # 可无，列表「记录名」展示

【分类与筛选 — 可无】
  favorite: bool                # 可无，默认 false；列表「仅收藏」筛选
  strategy_mode: str             # 可无，如 rule / model / combo
  strategy_ref: str
  market: str                    # 如无则列表筛选不到
  frequency: str
  benchmark: str
  model_used: bool

【时间窗口 — 可无】
  analysis_start: str
  analysis_end: str
  duration_seconds: number

【metrics 对象 — 详情卡片与列表数值的主要来源；键可无则显示 n/a】
  metrics: {
    total_return: number
    annualized_return: number
    max_drawdown: number
    sharpe: number
    sortino: number
    alpha: number
    beta: number
    volatility: number
    benchmark_volatility: number
    information_ratio: number
    trade_win_rate: number      # 与 win_rate 二选一即可，后端会读任一名
    win_rate: number
    turnover: number
    trade_count: number
    # 其他数字亦可放入 metrics，前端卡片会按 key 尝试展示
  }

【jq_overview_metrics — 不要求写入 run.json】
  详情 API get_run_detail / Notebook load_run_context 会在响应中额外包含字段 jq_overview_metrics
  （JoinQuant 风格「收益概述」页顶两排汇总指标）。由 compute_jq_overview_metrics 在服务端按
  portfolio / trades / manifest 动态计算；字段与语义见 docs/jq-overview-metrics.md。
  磁盘 run.json 可不包含该键；若手写也不会覆盖服务端计算结果。

【顶层指标回退 — 可无；若 metrics 缺则部分界面会读顶层同名键】
  returns, annualized_return, drawdown, sharpe, turnover, alpha, beta,
  win_rate, sortino, information_ratio, volatility, benchmark_volatility,
  fitness, margin, pnl, book_size, long_count, short_count,
  profit_loss_ratio, avg_daily_return, daily_win_rate, trade_count

【样本内外与成本 — 可无】
  in_sample: object
  out_of_sample: object          # 可含 periods（整数），用于详情「样本外周期数」
  cost_breakdown: object         # 如 fee_cost, funding_return；对比页会读

【数据血缘 — 可无】
  dataset_versions: object      # 字符串键值，列表展示摘要
  universe_snapshot_id: str
  stock_pool_id: str
  data_dependencies: array
  produced_outputs: array
  component_runs: array
  data_coverage_summary: object

【执行与中性化 — 可无】
  execution_profile: str
  execution_model: str
  instrument_type: str
  requested_neutralization: str
  resolved_neutralization: str
  neutralization: str
  unit_handling: str
  pasteurization: str
  temporary_symbols_count: number
  top_n: number
  ranking_metric: str
  resolved_candidate_count: number

【其他 — 可无】
  config_snapshot: object

【命名输出 — 可无；性能分析页「命名输出」表格】
  produced_outputs: [ 数组元素字段如下，均可无 except output_name 用于展示
    producer_scope, producer_id, producer_name, component_run_id,
    output_name, output_type, dataset_name, version_id,
    artifact_path, file_path, row_count, start, end, consumed_by, summary
  ]

-------------------------------------------------------------------------------
三、portfolio.csv
-------------------------------------------------------------------------------

时间列（至少一列，后端按顺序识别第一列存在的）：
  timestamp | date | trade_date | ann_date | cal_date

【必须有的业务列】
  equity: number                 # 净值序列；无则无法正确展示主曲线

【可无；缺失时部分序列尝试从 equity 派生或不展示】
  net_return: number             # API 序列名 strategy_return 映射到此列
  benchmark_return: number
  turnover: number
  drawdown: number
  max_drawdown: number
  alpha: number
  beta: number
  sharpe: number
  sortino: number
  information_ratio: number
  volatility: number
  benchmark_volatility: number
  gross_return: number
  funding_return: number
  fee_cost: number

-------------------------------------------------------------------------------
四、series/{name}.csv（可无；存在则优先于 portfolio 派生）
-------------------------------------------------------------------------------

每个文件固定两列：timestamp, value（表头必须存在）。

name 与后端 load_series_response 使用的名称一致，包括：
  equity, drawdown, turnover, net_return, gross_return, funding_return, fee_cost,
  benchmark_return, alpha, beta, sharpe, sortino, information_ratio,
  volatility, benchmark_volatility, max_drawdown,
  strategy_return               # 可与 net_return 二选一提供文件；二列 value 语义相同

注意：API 中「策略收益」序列名为 strategy_return，底层 portfolio 列名为 net_return。

-------------------------------------------------------------------------------
五、trades.csv（可无）
-------------------------------------------------------------------------------

后端表格过滤会识别的时间列之一：
  execution_timestamp（优先）| timestamp | trade_date | date | ...

【可无列】按你实际有则填；无列则该列不展示
  symbol, trade_side, quantity, price, turnover, realized_pnl, estimated_fee,
  delta_weight, execution_model, fee_rate, estimated_slippage

每日买入额 / 卖出额柱状图：依赖 turnover + trade_side（含 buy / sell 语义），可无则图为空。

-------------------------------------------------------------------------------
六、positions.csv（可无）
-------------------------------------------------------------------------------

时间列同上。

  symbol, row_kind, quantity, close_price, market_value, pnl, side, weight,
  score, selected_period_return, gross_contribution, funding_contribution

-------------------------------------------------------------------------------
七、attribution.csv（可无）
-------------------------------------------------------------------------------

列可无；有则展示

  label, weight, benchmark_weight, portfolio_return, benchmark_return,
  allocation_effect, selection_effect, interaction_effect, active_return

-------------------------------------------------------------------------------
八、backtest.log（可无）
-------------------------------------------------------------------------------

文本。若单行能被 " - " 分成 3 段，则解析为 timestamp, level, message；否则整行作为 message。

-------------------------------------------------------------------------------
九、回测详情页功能 ↔ 数据 ↔ Notebook 原语（函数模板见模块内示例函数）
-------------------------------------------------------------------------------

功能视图「收益概述」     → run.json + portfolio.csv + series 可选
  → plot_equity_overview(run_id)   # 单张 Plotly，布局≠ Web 三联图
  → load_run_context(run_id).get("jq_overview_metrics")  # 页顶两排数字；与 GET /api/runs/{id} 同源；docs/jq-overview-metrics.md

功能视图「交易详情」     → trades.csv
  → show_trades_table(run_id)

功能视图「每日持仓&收益」→ positions.csv
  → show_positions_table(run_id)

功能视图「日志输出」     → backtest.log
  → show_logs(run_id)

功能视图「性能分析」     → 产物文件是否存在于磁盘（artifact_stats）+ run.json 的 produced_outputs 数组
  → load_run_context(run_id)  # 查看 artifact_stats、produced_outputs

功能视图「策略代码」     → strategy.py
  → show_strategy_source(run_id)

功能视图「Markdown 报告」 → report.md
  → show_report(run_id)

功能视图「归因」         → attribution.csv
  → show_attribution(run_id)

指标页「策略收益」       → 序列 strategy_return（列 net_return 或 series/strategy_return.csv）
  → plot_metric_series(run_id, "strategy_return")

指标页「基准收益」       → benchmark_return
  → plot_metric_series(run_id, "benchmark_return")

指标页「阿尔法 / 贝塔 / 夏普 / 索提诺 / 信息比率 / 波动率 / 基准波动率 / 最大回撤」
  → plot_metric_series(run_id, "alpha" | "beta" | "sharpe" | "sortino" |
                        "information_ratio" | "volatility" | "benchmark_volatility" | "max_drawdown")

汇总包
  → render_detail_bundle(run_id)

================================================================================
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

# 在「app/backend」为 cwd 且已安装依赖时：
#   python qb_backtest_complete_guide.py
# 或在项目根目录：
#   python -c "import sys; sys.path.insert(0, 'app/backend'); import qb_backtest_complete_guide as g; g.print_paths()"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _data_root() -> Path:
    return Path(os.getenv("BACKTEST_DATA_ROOT") or (_project_root() / "data")).resolve()


def experiment_dir(run_id: str) -> Path:
    """data/artifacts/experiments/{run_id}/"""
    return _data_root() / "artifacts" / "experiments" / run_id


def ensure_experiment_dir(run_id: str) -> Path:
    root = experiment_dir(run_id)
    root.mkdir(parents=True, exist_ok=True)
    (root / "series").mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# run.json：全字段模板（值可为 None 的键表示可无，导出时可删键）
# ---------------------------------------------------------------------------

RUN_JSON_TEMPLATE_FULL: dict[str, Any] = {
    "run_id": "my_run_001",
    "strategy_id": "my_strategy",
    "strategy_name": "示例策略",
    "started_at": "2026-04-05T12:00:00Z",
    "status": "completed",
    "record_name": "实验记录名",
    "favorite": False,
    "strategy_mode": "rule",
    "strategy_ref": "workspace/python/strategy.py",
    "market": "stocks_cn",
    "frequency": "1d",
    "benchmark": "000300.SH",
    "model_used": False,
    "analysis_start": "2024-01-01",
    "analysis_end": "2025-12-31",
    "duration_seconds": 3600,
    "metrics": {
        "total_return": 0.12,
        "annualized_return": 0.08,
        "max_drawdown": -0.05,
        "sharpe": 1.1,
        "sortino": 1.3,
        "alpha": 0.03,
        "beta": 0.85,
        "volatility": 0.15,
        "benchmark_volatility": 0.14,
        "information_ratio": 0.4,
        "trade_win_rate": 0.55,
        "turnover": 2.5,
        "trade_count": 120,
    },
    "in_sample": {},
    "out_of_sample": {"periods": 0},
    "cost_breakdown": {"fee_cost": 0.001, "funding_return": 0.0},
    "dataset_versions": {"cn_daily": "2026Q1"},
    "universe_snapshot_id": "snap-001",
    "stock_pool_id": None,
    "temporary_symbols_count": None,
    "top_n": None,
    "ranking_metric": None,
    "resolved_candidate_count": None,
    "instrument_type": "stock",
    "execution_profile": None,
    "execution_model": None,
    "requested_neutralization": None,
    "resolved_neutralization": None,
    "neutralization": None,
    "unit_handling": None,
    "pasteurization": None,
    "data_dependencies": [],
    "produced_outputs": [
        {
            "output_name": "predictions",
            "dataset_name": "cn_daily",
            "version_id": "v1",
            "row_count": 5000,
            "producer_scope": "local",
            "producer_id": "pipe-1",
            "producer_name": None,
            "component_run_id": None,
            "output_type": "parquet",
            "artifact_path": "outputs/predictions.parquet",
            "file_path": None,
            "start": None,
            "end": None,
            "consumed_by": [],
            "summary": {},
        }
    ],
    "component_runs": [],
    "data_coverage_summary": {},
    "config_snapshot": None,
}


def write_run_json(path: Path, data: Mapping[str, Any] | None = None) -> None:
    """写入 run.json；data 默认使用 RUN_JSON_TEMPLATE_FULL。"""
    payload = dict(data if data is not None else RUN_JSON_TEMPLATE_FULL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# portfolio.csv：列名全集（除时间列外；时间列任选其一）
# ---------------------------------------------------------------------------

PORTFOLIO_COLUMNS_DOCUMENTED = [
    "timestamp",
    "equity",
    "net_return",
    "benchmark_return",
    "turnover",
    "drawdown",
    "max_drawdown",
    "alpha",
    "beta",
    "sharpe",
    "sortino",
    "information_ratio",
    "volatility",
    "benchmark_volatility",
    "gross_return",
    "funding_return",
    "fee_cost",
]

# trades.csv：时间列 + 下列列（可无列则缺省展示）
TRADES_COLUMNS_DOCUMENTED = [
    "execution_timestamp",
    "symbol",
    "trade_side",
    "quantity",
    "price",
    "turnover",
    "realized_pnl",
    "estimated_fee",
    "delta_weight",
    "execution_model",
    "fee_rate",
    "estimated_slippage",
]

# positions.csv：时间列 + 下列列（可无列则缺省展示）
POSITIONS_COLUMNS_DOCUMENTED = [
    "execution_timestamp",
    "symbol",
    "row_kind",
    "quantity",
    "close_price",
    "market_value",
    "pnl",
    "side",
    "weight",
    "score",
    "selected_period_return",
    "gross_contribution",
    "funding_contribution",
]

# attribution.csv：下列列（可无则表格缺列）
ATTRIBUTION_COLUMNS_DOCUMENTED = [
    "label",
    "weight",
    "benchmark_weight",
    "portfolio_return",
    "benchmark_return",
    "allocation_effect",
    "selection_effect",
    "interaction_effect",
    "active_return",
]


def write_portfolio_csv_example(path: Path) -> None:
    """最小可演示三行；equity 必须。"""
    lines = [
        ",".join(PORTFOLIO_COLUMNS_DOCUMENTED),
        "2026-01-01T00:00:00Z,100000,0.0,0.0,0.0,0.0,0.0,0.0,0.8,1.0,1.1,0.4,0.15,0.14,0.0,0.0,0.0",
        "2026-01-02T00:00:00Z,101000,0.01,0.002,0.1,0.0,0.0,0.001,0.8,1.02,1.12,0.41,0.151,0.141,0.0,0.0,0.0",
        "2026-01-03T00:00:00Z,100800,-0.002,0.001,0.08,-0.002,-0.002,-0.0005,0.8,0.99,1.08,0.38,0.152,0.142,0.0,0.0,0.0",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_trades_csv_example(path: Path) -> None:
    """列名全集见 TRADES_COLUMNS_DOCUMENTED；示例一行。"""
    lines = [
        ",".join(TRADES_COLUMNS_DOCUMENTED),
        "2026-01-02T09:35:00Z,000001.SZ,buy,1000,12.30,12300,0,6.15,0,,0,0",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_positions_csv_example(path: Path) -> None:
    """列名全集见 POSITIONS_COLUMNS_DOCUMENTED；示例一行。"""
    lines = [
        ",".join(POSITIONS_COLUMNS_DOCUMENTED),
        "2026-01-02T15:00:00Z,000001.SZ,close,1000,12.30,12300,0,long,0.1,0,0,0,0,0",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_attribution_csv_example(path: Path) -> None:
    """列名全集见 ATTRIBUTION_COLUMNS_DOCUMENTED。"""
    lines = [
        ",".join(ATTRIBUTION_COLUMNS_DOCUMENTED),
        "sector/finance,0.25,0.20,0.02,0.018,0.001,0.0005,0.0005,0.002",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_strategy_py_example(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 策略源码占位\n", encoding="utf-8")


def write_report_md_example(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 回测报告\n\n摘要。\n", encoding="utf-8")


def write_backtest_log_example(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("2026-04-05 20:10:00 - INFO - Backtest started\n", encoding="utf-8")


def write_series_csv(path: Path, rows: list[tuple[str, float]]) -> None:
    """series 文件：timestamp,value"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["timestamp,value"] + [f"{ts},{val}" for ts, val in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 导出整套最小可浏览目录（列表 + 详情概览）
# ---------------------------------------------------------------------------


def export_minimal_run(
    run_id: str,
    *,
    overwrite: bool = False,
) -> Path:
    """
    写入最小集合：run.json + portfolio.csv。
    若目录已存在且 overwrite=False，则抛错。
    """
    root = experiment_dir(run_id)
    if root.exists() and not overwrite:
        raise FileNotFoundError(f"目录已存在: {root} ，传入 overwrite=True 覆盖")
    root.mkdir(parents=True, exist_ok=True)
    data = dict(RUN_JSON_TEMPLATE_FULL)
    data["run_id"] = run_id
    write_run_json(root / "run.json", data)
    write_portfolio_csv_example(root / "portfolio.csv")
    return root


def export_full_demo_artifacts(run_id: str, *, overwrite: bool = False) -> Path:
    """
    在最小集合之外，写入 trades / positions / attribution / report / strategy / log，
    便于一次性验证详情页各 Tab（可无文件均覆盖示例）。
    """
    root = export_minimal_run(run_id, overwrite=overwrite)
    write_trades_csv_example(root / "trades.csv")
    write_positions_csv_example(root / "positions.csv")
    write_attribution_csv_example(root / "attribution.csv")
    write_report_md_example(root / "report.md")
    write_strategy_py_example(root / "strategy.py")
    write_backtest_log_example(root / "backtest.log")
    return root


# ---------------------------------------------------------------------------
# Notebook：与「回测详情」各区块一一对应的调用模板（复制到 Jupyter 使用）
# ---------------------------------------------------------------------------


def notebook_import_block() -> str:
    return '''
import sys
from pathlib import Path

project_root = Path(r"__REPLACE_WITH_YOUR_PROJECT_ROOT__")  # 例如 D:/1Codeprojects/1Backtest
sys.path.insert(0, str(project_root / "app" / "backend"))

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

RUN_ID = "demo"  # 改成你的 run_id
'''


def template_detail_functions(run_id: str = "demo") -> None:
    """
    在已配置 sys.path 的前提下，下列代码与回测详情页各功能一致。
    本函数仅打印模板字符串，避免在未安装 polars 的环境里执行失败。
    """
    code = f'''
# ---------- 汇总 ----------
bundle = render_detail_bundle("{run_id}")

# ---------- 收益概述（同页「收益概述」图表数据源） ----------
fig_overview = plot_equity_overview("{run_id}")
# fig_overview.show()

# ---------- 收益概述页顶「聚宽风格」指标块（与 Web 两排数字、API 字段 jq_overview_metrics 同源） ----------
jq_metrics = load_run_context("{run_id}").get("jq_overview_metrics") or {}
# 由服务端动态计算，不要求 run.json 含此键；字段说明见 docs/jq-overview-metrics.md

# ---------- 指标子页（与侧栏「指标页」名称一致） ----------
plot_metric_series("{run_id}", "strategy_return")   # 策略收益 → 底层列 net_return
plot_metric_series("{run_id}", "benchmark_return")
plot_metric_series("{run_id}", "alpha")
plot_metric_series("{run_id}", "beta")
plot_metric_series("{run_id}", "sharpe")
plot_metric_series("{run_id}", "sortino")
plot_metric_series("{run_id}", "information_ratio")
plot_metric_series("{run_id}", "volatility")
plot_metric_series("{run_id}", "benchmark_volatility")
plot_metric_series("{run_id}", "max_drawdown")

# ---------- 功能视图 ----------
df_trades = show_trades_table("{run_id}")
df_pos = show_positions_table("{run_id}")
df_logs = show_logs("{run_id}")
text_report = show_report("{run_id}")
text_strategy = show_strategy_source("{run_id}")
df_attr = show_attribution("{run_id}")

# ---------- 性能分析页：产物统计 + run.json 命名输出 ----------
ctx = load_run_context("{run_id}")
artifact_stats = ctx.get("artifact_stats")  # 各 artifact 是否提供、大小、行数
produced = ctx.get("produced_outputs")      # run.json produced_outputs

# ---------- 原始 JSON 详情 / 指标卡片 ----------
cards = build_metric_cards("{run_id}")
'''
    print(code)


def print_paths() -> None:
    print("PROJECT_ROOT =", _project_root())
    print("DATA_ROOT   =", _data_root())
    print("示例实验目录 =", experiment_dir("demo"))


__all__ = [
    "ATTRIBUTION_COLUMNS_DOCUMENTED",
    "PORTFOLIO_COLUMNS_DOCUMENTED",
    "POSITIONS_COLUMNS_DOCUMENTED",
    "RUN_JSON_TEMPLATE_FULL",
    "TRADES_COLUMNS_DOCUMENTED",
    "ensure_experiment_dir",
    "experiment_dir",
    "export_full_demo_artifacts",
    "export_minimal_run",
    "notebook_import_block",
    "print_paths",
    "template_detail_functions",
    "write_attribution_csv_example",
    "write_backtest_log_example",
    "write_portfolio_csv_example",
    "write_positions_csv_example",
    "write_report_md_example",
    "write_run_json",
    "write_series_csv",
    "write_strategy_py_example",
    "write_trades_csv_example",
]


if __name__ == "__main__":
    print(__doc__[:1200] + "\n...（完整契约见本文件开头文档字符串）...\n")
    print_paths()
    print()
    print(notebook_import_block())
    print()
    template_detail_functions("demo")
