# -*- coding: utf-8 -*-
"""
研究侧：与 Web「收益概述」三联图行数据一致的 `build_overview_rows`，以及将内存数据导出为 qb 可读目录。

逻辑对齐 `app/frontend/src/pages/RunDetailPage.tsx` 中 normalizeEquityPoints / normalizeBenchmarkPoints /
buildDateAxis / buildOverviewRows。

完整 API 说明（参数、返回值、异常）：仓库 `docs/api-reference.md` 第 3 节。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence, TypedDict

import pandas as pd

_backend_root = Path(__file__).resolve().parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from app.paths import RUN_ROOT, ensure_runtime_dirs  # noqa: E402

try:
    from plotly.subplots import make_subplots

    _HAS_PLOTLY = True
except ImportError:
    _HAS_PLOTLY = False


class OverviewRow(TypedDict, total=False):
    """与前端 OverviewRow 对应（snake_case）；strategy/benchmark 为累计收益型数值（与页面一致）。"""

    date: str
    strategy_return: float | None
    benchmark_return: float | None
    excess_daily: float | None
    turnover: float | None
    daily_buy: float | None
    daily_sell: float | None


SeriesPoint = dict[str, Any]


def to_date_label(timestamp: str | None) -> str:
    if not timestamp:
        return ""
    return str(timestamp)[:10]


def safe_number(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN
        return None
    return n


def normalize_equity_points(points: Sequence[SeriesPoint]) -> dict[str, float]:
    if not points:
        return {}
    first = safe_number(points[0].get("value"))
    if first is None or first == 0:
        return {}
    out: dict[str, float] = {}
    for point in points:
        ts = point.get("timestamp")
        if not ts:
            continue
        v = safe_number(point.get("value"))
        if v is None:
            continue
        out[to_date_label(str(ts))] = v / first
    return out


def normalize_benchmark_points(points: Sequence[SeriesPoint]) -> dict[str, float]:
    out: dict[str, float] = {}
    for point in points:
        ts = point.get("timestamp")
        if not ts:
            continue
        v = safe_number(point.get("value"))
        if v is None:
            continue
        out[to_date_label(str(ts))] = float(v) + 1.0
    return out


def build_date_axis(*series_groups: Sequence[SeriesPoint]) -> list[str]:
    dates: set[str] = set()
    for group in series_groups:
        for point in group:
            ts = point.get("timestamp")
            if not ts:
                continue
            label = to_date_label(str(ts))
            if label:
                dates.add(label)
    return sorted(dates)


def build_overview_rows(
    equity_points: Sequence[SeriesPoint],
    benchmark_points: Sequence[SeriesPoint],
    turnover_points: Sequence[SeriesPoint],
    daily_buy_points: Sequence[SeriesPoint],
    daily_sell_points: Sequence[SeriesPoint],
) -> list[OverviewRow]:
    """
    与 RunDetailPage.tsx `buildOverviewRows` 一致。
    输入为五组序列点（通常来自 API `load_series_response` 的 points 或自建）。
    """
    dates = build_date_axis(
        equity_points,
        benchmark_points,
        turnover_points,
        daily_buy_points,
        daily_sell_points,
    )
    equity_map = normalize_equity_points(equity_points)
    benchmark_map = normalize_benchmark_points(benchmark_points)
    turnover_map = {to_date_label(str(p["timestamp"])): float(safe_number(p.get("value")) or 0) for p in turnover_points if p.get("timestamp")}
    buy_map = {to_date_label(str(p["timestamp"])): float(safe_number(p.get("value")) or 0) for p in daily_buy_points if p.get("timestamp")}
    sell_map = {to_date_label(str(p["timestamp"])): float(safe_number(p.get("value")) or 0) for p in daily_sell_points if p.get("timestamp")}

    previous_strategy_nav: float | None = None
    previous_benchmark_nav: float | None = None
    rows: list[OverviewRow] = []

    for date in dates:
        strategy_nav = equity_map.get(date)
        benchmark_nav = benchmark_map.get(date)

        strategy_return = strategy_nav - 1.0 if strategy_nav is not None else None
        benchmark_return = benchmark_nav - 1.0 if benchmark_nav is not None else None

        if strategy_nav is not None and previous_strategy_nav is not None and previous_strategy_nav != 0:
            strategy_daily = strategy_nav / previous_strategy_nav - 1.0
        else:
            strategy_daily = 0.0

        if benchmark_nav is not None and previous_benchmark_nav is not None and previous_benchmark_nav != 0:
            benchmark_daily = benchmark_nav / previous_benchmark_nav - 1.0
        else:
            benchmark_daily = 0.0

        if strategy_return is not None or benchmark_return is not None:
            excess_daily = strategy_daily - benchmark_daily
        else:
            excess_daily = None

        row: OverviewRow = {
            "date": date,
            "strategy_return": strategy_return,
            "benchmark_return": benchmark_return,
            "excess_daily": excess_daily,
            "turnover": turnover_map.get(date),
            "daily_buy": buy_map.get(date),
            "daily_sell": sell_map.get(date),
        }
        rows.append(row)

        if strategy_nav is not None:
            previous_strategy_nav = strategy_nav
        if benchmark_nav is not None:
            previous_benchmark_nav = benchmark_nav

    return rows


def filter_overview_rows(rows: Sequence[OverviewRow], start_date: str = "", end_date: str = "") -> list[OverviewRow]:
    out: list[OverviewRow] = []
    for row in rows:
        d = row.get("date") or ""
        if start_date and d < start_date:
            continue
        if end_date and d > end_date:
            continue
        out.append(row)
    return out


def plot_overview_three_panel_plotly(
    rows: Sequence[OverviewRow],
    *,
    benchmark_label: str = "基准",
    title: str = "收益概述（近似 Web 三联）",
) -> Any:
    """
    三行子图：策略/基准累计收益、超额日收益、换手与买卖额。
    需要安装 plotly。若未安装则抛 ImportError。
    """
    if not _HAS_PLOTLY:
        raise ImportError("需要安装 plotly: pip install plotly")

    import plotly.graph_objects as go

    dates = [r["date"] for r in rows]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06, subplot_titles=("策略与基准（累计）", "超额（日）", "换手与买卖额"))

    fig.add_trace(
        go.Scatter(x=dates, y=[r.get("strategy_return") for r in rows], name="策略收益", line=dict(width=2)),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(x=dates, y=[r.get("benchmark_return") for r in rows], name=benchmark_label, line=dict(width=2)),
        row=1,
        col=1,
    )
    fig.add_trace(go.Bar(x=dates, y=[r.get("excess_daily") for r in rows], name="超额收益"), row=2, col=1)
    fig.add_trace(go.Scatter(x=dates, y=[r.get("turnover") for r in rows], name="换手", line=dict(width=1)), row=3, col=1)
    fig.add_trace(go.Bar(x=dates, y=[r.get("daily_buy") for r in rows], name="买入额"), row=3, col=1)
    fig.add_trace(go.Bar(x=dates, y=[r.get("daily_sell") for r in rows], name="卖出额"), row=3, col=1)

    fig.update_layout(title=title, height=900, hovermode="x unified")
    return fig


def export_run_bundle_for_detail(
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
) -> Path:
    """
    写入 `{DATA_ROOT}/artifacts/experiments/{run_id}/`，供 Web / Notebook 读取。

    - `manifest` 会写入 `run.json`（须含 `run_id` 或与参数 `run_id` 一致）。
    - `portfolio` 写入 `portfolio.csv`（须有后端可识别的时间列之一 + 至少 `equity` 等列，见 run_detail_core）。
    - 其余参数均可无；有则写入对应文件。
    """
    ensure_runtime_dirs()
    root = RUN_ROOT / run_id
    if root.exists() and not overwrite:
        raise FileNotFoundError(f"目录已存在: {root} ，使用 overwrite=True 覆盖")

    root.mkdir(parents=True, exist_ok=True)
    (root / "series").mkdir(parents=True, exist_ok=True)

    m = dict(manifest)
    m.setdefault("run_id", run_id)
    (root / "run.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

    portfolio.to_csv(root / "portfolio.csv", index=False, encoding="utf-8-sig")

    if trades is not None and not trades.empty:
        trades.to_csv(root / "trades.csv", index=False, encoding="utf-8-sig")
    if positions is not None and not positions.empty:
        positions.to_csv(root / "positions.csv", index=False, encoding="utf-8-sig")
    if attribution is not None and not attribution.empty:
        attribution.to_csv(root / "attribution.csv", index=False, encoding="utf-8-sig")
    if report_md is not None:
        (root / "report.md").write_text(report_md, encoding="utf-8")
    if strategy_py is not None:
        (root / "strategy.py").write_text(strategy_py, encoding="utf-8")
    if log_text is not None:
        (root / "backtest.log").write_text(log_text, encoding="utf-8")

    return root


__all__ = [
    "OverviewRow",
    "build_date_axis",
    "build_overview_rows",
    "export_run_bundle_for_detail",
    "filter_overview_rows",
    "normalize_benchmark_points",
    "normalize_equity_points",
    "plot_overview_three_panel_plotly",
    "safe_number",
    "to_date_label",
]
