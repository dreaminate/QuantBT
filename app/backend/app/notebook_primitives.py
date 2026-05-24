from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

from .run_detail_core import (
    RUN_SERIES_COLUMNS,
    get_run_attribution,
    get_run_detail,
    get_run_logs,
    get_run_source,
    load_run,
    load_series_response,
    load_table_response,
)
from .schemas import NotebookBundle, NotebookMetricCard


METRIC_CARD_SPECS = [
    ("total_return", "总收益", "pct"),
    ("annualized_return", "年化收益", "pct"),
    ("max_drawdown", "最大回撤", "pct"),
    ("sharpe", "夏普", "num"),
    ("sortino", "索提诺", "num"),
    ("alpha", "Alpha", "pct"),
    ("beta", "Beta", "num"),
    ("trade_count", "交易次数", "num"),
]


def load_run_context(run_id: str) -> dict[str, Any]:
    return get_run_detail(run_id)


def build_metric_cards(run_id: str) -> list[NotebookMetricCard]:
    run = get_run_detail(run_id)
    metrics = run.get("metrics") or {}
    cards: list[NotebookMetricCard] = []
    for key, label, fmt in METRIC_CARD_SPECS:
        value = metrics.get(key)
        if value is None:
            value = run.get(key)
        cards.append(NotebookMetricCard(key=key, label=label, value=value, format=fmt))
    return cards


def _series_to_frame(run_id: str, series_name: str) -> pd.DataFrame:
    payload = load_series_response(run_id, series_name, "overall")
    return pd.DataFrame(payload["points"])


def plot_equity_overview(run_id: str) -> go.Figure:
    equity = _series_to_frame(run_id, "equity")
    benchmark = _series_to_frame(run_id, "benchmark_return")
    turnover = _series_to_frame(run_id, "turnover")
    fig = go.Figure()
    if not equity.empty:
        fig.add_trace(go.Scatter(x=equity["timestamp"], y=equity["value"], mode="lines", name="策略净值"))
    if not benchmark.empty:
        fig.add_trace(go.Scatter(x=benchmark["timestamp"], y=benchmark["value"], mode="lines", name="基准收益"))
    if not turnover.empty:
        fig.add_trace(go.Bar(x=turnover["timestamp"], y=turnover["value"], name="换手率", yaxis="y2", opacity=0.35))
        fig.update_layout(
            yaxis2=dict(title="换手率", overlaying="y", side="right", showgrid=False),
        )
    fig.update_layout(
        title="收益概览",
        template="plotly_white",
        hovermode="x unified",
        xaxis_title="时间",
        yaxis_title="值",
    )
    return fig


def plot_metric_series(run_id: str, series_name: str) -> go.Figure:
    frame = _series_to_frame(run_id, series_name)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=frame.get("timestamp"), y=frame.get("value"), mode="lines", name=series_name))
    fig.update_layout(
        title=series_name,
        template="plotly_white",
        hovermode="x unified",
        xaxis_title="时间",
        yaxis_title="值",
    )
    return fig


def show_trades_table(run_id: str) -> pd.DataFrame:
    payload = load_table_response(run_id, "trades", limit=100000, offset=0, sort="execution_timestamp", order="desc")
    return pd.DataFrame(payload["rows"])


def show_positions_table(run_id: str) -> pd.DataFrame:
    payload = load_table_response(run_id, "positions", limit=100000, offset=0, sort="execution_timestamp", order="asc")
    return pd.DataFrame(payload["rows"])


def show_logs(run_id: str) -> pd.DataFrame:
    payload = get_run_logs(run_id, limit=100000, offset=0)
    return pd.DataFrame(payload["entries"])


def show_report(run_id: str) -> str:
    return load_run(run_id).report_markdown


def show_strategy_source(run_id: str) -> str:
    return get_run_source(run_id)["content"]


def show_attribution(run_id: str) -> pd.DataFrame:
    payload = get_run_attribution(run_id)
    return pd.DataFrame(payload["rows"])


def render_detail_bundle(run_id: str) -> NotebookBundle:
    run = get_run_detail(run_id)
    available_series = [series for series in list(RUN_SERIES_COLUMNS) + ["daily_buy", "daily_sell"] if load_series_response(run_id, series)["available"]]
    return NotebookBundle(
        run=run,
        metric_cards=build_metric_cards(run_id),
        available_series=available_series,
        report_markdown=show_report(run_id),
        log_entries=get_run_logs(run_id, limit=2000, offset=0)["entries"],
    )


__all__ = [
    "build_metric_cards",
    "load_run_context",
    "plot_equity_overview",
    "plot_metric_series",
    "render_detail_bundle",
    "show_attribution",
    "show_logs",
    "show_positions_table",
    "show_report",
    "show_strategy_source",
    "show_trades_table",
]
