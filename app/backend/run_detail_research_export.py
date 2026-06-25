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
from app.delivery import ASSET_STRATEGYBOOK, RDPManifest  # noqa: E402  §17 RDP 接线（D-RDP-1 wire）

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


def _artifact_present(value: Any) -> bool:
    """run-bundle 字段是否真有内容：None→False；空 DataFrame→False；空/纯空白 str→False。

    （DataFrame 直接 `if df:` 会抛 ValueError，故按 .empty / str.strip 分流判定。）
    """

    if value is None:
        return False
    empty_attr = getattr(value, "empty", None)
    if empty_attr is not None:  # DataFrame-like
        return not bool(empty_attr)
    if isinstance(value, str):
        return bool(value.strip())
    return True


def build_rdp_from_run_bundle(
    run_id: str,
    manifest: Mapping[str, Any],
    *,
    asset_ref: str | None = None,
    asset_kind: str = ASSET_STRATEGYBOOK,
    trades: pd.DataFrame | None = None,
    positions: pd.DataFrame | None = None,
    attribution: pd.DataFrame | None = None,
    report_md: str | None = None,
    strategy_py: str | None = None,
    log_text: str | None = None,
    **rdp_fields: Any,
) -> RDPManifest:
    """把现导出器 run-bundle 的 **6 字段**（trades / positions / attribution / report_md /
    strategy_py / log_text）诚实投影进一份开放格式 `RDPManifest`（§17 · D-RDP-1 wire · 扩展不替换）。

    映射（只把【真实存在】的产物落进 §17 对应槽，不存在即留空，绝不凭空补）：
      · strategy_py  → code_refs + source_file_refs（"strategy.py"，狭义源码）
      · report_md    → source_file_refs（"report.md"，随包带的研究报告文件）
      · log_text     → source_file_refs（"backtest.log"，运行日志文件）
      · trades / positions → backtest_run_refs=(run_id,)（产物来自该回测运行）
      · attribution  → attribution（§17 归因字段，指向 "attribution.csv" 逐期归因产物）

    诚实边界（§3 不假绿灯 / no template false success · RULES.project）：
    - 【门强制】项——artifact_hash / reproducibility_command / dataset_versions /
      ingestion_skill_refs / 未验证残余——**不在**这 6 个 run-bundle 字段里。本函数只从 `manifest`
      已有键 + 显式 `rdp_fields` 透传，都缺 → 产出 RDP 残缺，`validate_rdp` 据实标 missing（verdict
      blocked/missing，**绝不**美化成完整交付）。补全真血统是 D-RDP-2 聚合器（依赖 LINE-A
      LLMCallRecord + B DatasetVersion）的活，本卡只接线投影。
    - id 走单一身份源（RDPManifest 内部复用 lineage.ids.content_hash），本函数不另造哈希。

    `rdp_fields` 显式覆盖任何同名映射（让调用方/聚合器能补齐 §17 完整字段，按内容寻址出有效 RDP）。
    """

    source_file_refs: list[str] = []
    code_refs: list[str] = []
    if _artifact_present(strategy_py):
        source_file_refs.append("strategy.py")
        code_refs.append("strategy.py")
    if _artifact_present(report_md):
        source_file_refs.append("report.md")
    if _artifact_present(log_text):
        source_file_refs.append("backtest.log")

    attribution_note = ""
    if _artifact_present(attribution):
        attribution_note = "attribution.csv（逐期归因产物，随包带）"

    # backtest_run_refs：该 run 即一次回测运行（trades/positions 是其产物）。
    backtest_run_refs: tuple[str, ...] = (run_id,)

    # manifest（run.json）里已有的 §17 键 → 透传（缺则留空，不补默认）。
    def _m(key: str, default: Any = "") -> Any:
        val = manifest.get(key, default)
        return val if val is not None else default

    fields: dict[str, Any] = {
        "asset_ref": asset_ref or _m("asset_ref") or f"run:{run_id}",
        "asset_kind": asset_kind,
        "created_by": _m("created_by"),
        "research_proposition": _m("research_proposition"),
        "research_graph_ref": _m("research_graph_ref"),
        "data_pit_semantics": _m("data_pit_semantics"),
        "environment": _m("environment"),
        "environment_lock": _m("environment_lock"),
        "code_hash": _m("code_hash") or _m("config_hash"),
        "seed": manifest.get("seed"),
        "reproducibility_command": _m("reproducibility_command"),
        "artifact_hash": _m("artifact_hash"),
        "attribution": attribution_note or _m("attribution"),
        "source_file_refs": tuple(source_file_refs),
        "code_refs": tuple(code_refs),
        "backtest_run_refs": backtest_run_refs,
    }
    fields.update(rdp_fields)  # 显式 §17 字段（dataset_versions / ingestion_skill_refs / 未验证残余…）覆盖映射
    return RDPManifest(**fields)


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
    rdp: RDPManifest | None = None,
) -> Path:
    """
    写入 `{DATA_ROOT}/artifacts/experiments/{run_id}/`，供 Web / Notebook 读取。

    - `manifest` 会写入 `run.json`（须含 `run_id` 或与参数 `run_id` 一致）。
    - `portfolio` 写入 `portfolio.csv`（须有后端可识别的时间列之一 + 至少 `equity` 等列，见 run_detail_core）。
    - 其余参数均可无；有则写入对应文件。
    - `rdp`（§17 · D-RDP-1 wire · **扩展不替换 · 只加文件**）：给出则额外写开放格式 `rdp.json`
      （`RDPManifest.to_json()`，第三方可解析），不动 run.json/portfolio.csv 等既有产物，
      也不动前端「收益概述」页冻结口径。不给则不写（向后兼容，既有调用零行为变化）。
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
    if rdp is not None:
        # §17 开放格式交付包：只加文件，不触碰既有产物与冻结口径（扩展不替换）。
        (root / "rdp.json").write_text(rdp.to_json(), encoding="utf-8")

    return root


__all__ = [
    "OverviewRow",
    "build_date_axis",
    "build_overview_rows",
    "build_rdp_from_run_bundle",
    "export_run_bundle_for_detail",
    "filter_overview_rows",
    "normalize_benchmark_points",
    "normalize_equity_points",
    "plot_overview_three_panel_plotly",
    "safe_number",
    "to_date_label",
]
