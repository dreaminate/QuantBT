"""
JoinQuant 风格「收益概述」指标：与前端 `jq_overview_metrics` 字段一一对应，由服务层计算/合并。

语义说明见 docs/jq-overview-metrics.md。
"""

from __future__ import annotations

import math
import statistics
from typing import Any

import polars as pl


def _safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if number != number:
        return None
    return number


def _date_column(frame: pl.DataFrame) -> str | None:
    for column in ("execution_timestamp", "timestamp", "trade_date", "date", "ann_date", "cal_date"):
        if column in frame.columns:
            return column
    return None


def _col(frame: pl.DataFrame, *names: str) -> str | None:
    for n in names:
        if n in frame.columns:
            return n
    return None


def _series_float(frame: pl.DataFrame, col_name: str) -> list[float]:
    if col_name not in frame.columns:
        return []
    return [float(x) if x is not None and not (isinstance(x, float) and math.isnan(x)) else 0.0 for x in frame[col_name].to_list()]


def _max_drawdown_episode_dates(dates: list[str], equity: list[float]) -> tuple[str, str] | None:
    """根据净值序列找最大回撤区间 [阶段高点日期, 谷底日期]。"""
    if len(dates) < 2 or len(equity) != len(dates):
        return None
    running_max = equity[0]
    peak_idx = 0
    max_dd = 0.0
    best_peak = 0
    best_trough = 0
    for i in range(1, len(equity)):
        if equity[i] > running_max:
            running_max = equity[i]
            peak_idx = i
        dd = equity[i] / running_max - 1.0 if running_max else 0.0
        if dd < max_dd:
            max_dd = dd
            best_peak = peak_idx
            best_trough = i
    if best_trough <= best_peak:
        return None
    return dates[best_peak], dates[best_trough]


def compute_jq_overview_metrics(run: Any) -> dict[str, Any]:
    """
    返回 snake_case 字典；数值可为 None（前端显示 —）。
    优先 manifest.metrics，再用 portfolio/trades 派生。
    """
    manifest = run.manifest
    m = manifest.get("metrics") or {}
    pf = run.portfolio
    trades = run.trades

    def mf(*keys: str) -> Any:
        for k in keys:
            if k in m and m[k] is not None and m[k] != "":
                return m[k]
        return None

    out: dict[str, Any] = {}

    _sr = _safe_number(mf("strategy_return", "total_return"))
    if _sr is None:
        _sr = _safe_number(manifest.get("returns"))
    out["strategy_return"] = _sr
    out["strategy_annual_return"] = _safe_number(mf("strategy_annual_return", "annualized_return"))
    out["benchmark_return"] = _safe_number(mf("benchmark_return", "benchmark_total_return"))
    out["alpha"] = _safe_number(mf("alpha"))
    out["beta"] = _safe_number(mf("beta"))
    out["sharpe_ratio"] = _safe_number(mf("sharpe_ratio", "sharpe"))
    out["win_rate"] = _safe_number(mf("win_rate", "trade_win_rate"))
    out["profit_loss_ratio"] = _safe_number(mf("profit_loss_ratio"))
    out["max_drawdown"] = _safe_number(mf("max_drawdown", "drawdown"))
    out["sortino_ratio"] = _safe_number(mf("sortino_ratio", "sortino"))
    out["information_ratio"] = _safe_number(mf("information_ratio"))
    out["strategy_volatility"] = _safe_number(mf("strategy_volatility", "volatility"))
    out["benchmark_volatility"] = _safe_number(mf("benchmark_volatility"))
    out["daily_win_rate"] = _safe_number(mf("daily_win_rate"))

    # —— 由 portfolio 派生 —— #
    date_col = _date_column(pf)
    net_col = _col(pf, "net_return", "strategy_return")
    bench_col = _col(pf, "benchmark_return")

    dates: list[str] = []
    if date_col and len(pf) > 0:
        raw_dates = pf[date_col].to_list()
        dates = [str(d)[:10] if d is not None else "" for d in raw_dates]

    excess_daily: list[float] = []
    if net_col and bench_col and len(pf) > 0:
        nr = _series_float(pf, net_col)
        br = _series_float(pf, bench_col)
        n = min(len(nr), len(br))
        excess_daily = [nr[i] - br[i] for i in range(n)]

    if excess_daily:
        out["avg_daily_excess_return"] = float(sum(excess_daily) / len(excess_daily))
        # 超额净值曲线（日超额复利累计）
        w = 1.0
        peak = 1.0
        max_ex_dd = 0.0
        for x in excess_daily:
            w *= 1.0 + x
            peak = max(peak, w)
            dd = w / peak - 1.0 if peak else 0.0
            max_ex_dd = min(max_ex_dd, dd)
        out["excess_max_drawdown"] = float(max_ex_dd) if max_ex_dd < 0 else None

        if len(excess_daily) > 1:
            sd = statistics.pstdev(excess_daily)
            mu = statistics.mean(excess_daily)
            out["excess_sharpe_ratio"] = float((mu / sd) * math.sqrt(252)) if sd > 0 else None
        else:
            out["excess_sharpe_ratio"] = None
    else:
        out["avg_daily_excess_return"] = _safe_number(mf("avg_daily_excess_return"))
        out["excess_max_drawdown"] = _safe_number(mf("excess_max_drawdown"))
        out["excess_sharpe_ratio"] = _safe_number(mf("excess_sharpe_ratio", "excess_sharpe"))

    # 若 metrics 未给全段累计收益，尝试由 portfolio 日复利累乘得到
    def _cum_return_from_daily(cols: str | None) -> float | None:
        if not cols or len(pf) < 1:
            return None
        xs = _series_float(pf, cols)
        if not xs:
            return None
        w = 1.0
        for x in xs:
            w *= 1.0 + x
        return float(w - 1.0)

    if out["strategy_return"] is None and net_col:
        out["strategy_return"] = _cum_return_from_daily(net_col)
    if out["benchmark_return"] is None and bench_col:
        out["benchmark_return"] = _cum_return_from_daily(bench_col)

    # 累计超额：(1+Rs)/(1+Rb)-1
    rs = out["strategy_return"]
    rb = out["benchmark_return"]
    if rs is not None and rb is not None:
        out["excess_return"] = float((1 + float(rs)) / (1 + float(rb)) - 1)
    else:
        out["excess_return"] = _safe_number(mf("excess_return"))

    # 最大回撤区间
    mdp = mf("max_drawdown_period")
    if isinstance(mdp, (list, tuple)) and len(mdp) == 2:
        out["max_drawdown_period"] = [str(mdp[0])[:10], str(mdp[1])[:10]]
    else:
        eq_col = _col(pf, "equity")
        if date_col and eq_col and len(pf) > 1:
            eq = _series_float(pf, eq_col)
            episode = _max_drawdown_episode_dates(dates, eq)
            out["max_drawdown_period"] = list(episode) if episode else None
        else:
            out["max_drawdown_period"] = None

    # 盈利/亏损次数（成交维度）
    profit_count: int | None = None
    loss_count: int | None = None
    pnl_col = _col(trades, "realized_pnl", "pnl", "profit")
    if pnl_col and len(trades) > 0:
        vals = trades[pnl_col].cast(pl.Float64, strict=False).fill_null(0.0)
        profit_count = int((vals > 0).sum())
        loss_count = int((vals < 0).sum())
    else:
        pc = mf("profit_count")
        lc = mf("loss_count")
        if pc is not None:
            profit_count = int(pc)
        if lc is not None:
            loss_count = int(lc)
    out["profit_count"] = profit_count
    out["loss_count"] = loss_count

    return out
