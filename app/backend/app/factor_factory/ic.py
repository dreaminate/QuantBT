"""M4 · 因子专业性硬指标：IC / Rank-IC / IC-IR / IC 衰减。

按 QuantBT-GOAL.md §2.2「专业性硬指标」要求：任何特征 PR 必须能产出
IC / Rank-IC / IC-IR / IC 衰减曲线（5/10/20 日 horizon）。

输入 panel：必须含列 (ts, symbol, factor_value, forward_return_h{n})。
我们额外提供 helper 自动从 close 价生成 `forward_return_h{n}`。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import polars as pl


@dataclass
class ICReport:
    horizon: int
    ic_mean: float
    rank_ic_mean: float
    ic_ir: float
    rank_ic_ir: float
    sample_count: int
    by_period: list[dict[str, Any]] = field(default_factory=list)
    # D-F2-AUDIT(b)：IC 截面序列有自相关（overlapping forward window 尤甚），朴素 t = IR·√N
    # 会高估显著性。Newey-West HAC 调整后的 t 统计量是 IC 显著性的诚实口径。lag 默认 = horizon-1
    # （重叠窗口的诱导自相关阶数）。tstat=None 表示样本不足无法估计。
    ic_tstat_nw: float | None = None
    nw_lag: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "ic_mean": _safe_float(self.ic_mean),
            "rank_ic_mean": _safe_float(self.rank_ic_mean),
            "ic_ir": _safe_float(self.ic_ir),
            "rank_ic_ir": _safe_float(self.rank_ic_ir),
            "sample_count": int(self.sample_count),
            "ic_tstat_nw": _safe_float(self.ic_tstat_nw),
            "nw_lag": int(self.nw_lag),
            "by_period": self.by_period,
        }


def _safe_float(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return round(f, 6)


def newey_west_tstat(series: list[float], lag: int | None = None) -> float | None:
    """IC 序列均值是否显著异于 0 的 Newey-West (HAC) t 统计量。

    朴素 t = mean/(std/√N) 假设 IC 序列 iid；但重叠 forward-return 窗口会诱导强自相关，
    使朴素 t 系统性高估显著性（López de Prado 反复点名的「重叠样本」陷阱）。NW 用 Bartlett
    核给前 `lag` 阶自协方差加权，给出对自相关稳健的均值方差。

    lag=None → 自动取 floor(4·(N/100)^(2/9))（Newey-West 1994 经验规则）。
    返回 None：样本不足（N<3）或方差退化（无法估计）。
    """

    x = [float(v) for v in series if v == v]  # 滤 NaN
    n = len(x)
    if n < 3:
        return None
    mean = sum(x) / n
    centered = [v - mean for v in x]
    gamma0 = sum(c * c for c in centered) / n
    if gamma0 <= 0:
        return None
    if lag is None:
        lag = int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    lag = max(0, min(lag, n - 1))
    # 长程方差 = γ0 + 2·Σ_{k=1..lag} w_k·γ_k，w_k = 1 - k/(lag+1)（Bartlett）。
    long_run = gamma0
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1.0)
        gamma_k = sum(centered[t] * centered[t - k] for t in range(k, n)) / n
        long_run += 2.0 * w * gamma_k
    if long_run <= 0:
        # 负自相关把长程方差压到非正——退回朴素方差（保守不放大显著性）。
        long_run = gamma0
    se = math.sqrt(long_run / n)
    if se <= 0:
        return None
    return mean / se


def attach_forward_returns(panel: pl.DataFrame, horizons: list[int]) -> pl.DataFrame:
    """给 panel 加列 forward_return_h{n}（次 n 日 close 累计收益）。"""

    if "close" not in panel.columns:
        raise ValueError("panel 必须含 `close` 列")
    df = panel.sort(["symbol", "ts"])
    new_cols: list[pl.Expr] = []
    for h in horizons:
        col_name = f"forward_return_h{h}"
        new_cols.append(
            ((pl.col("close").shift(-h) / pl.col("close")) - 1).over("symbol").alias(col_name)
        )
    return df.with_columns(new_cols)


def compute_ic_report(
    panel: pl.DataFrame,
    factor_col: str,
    horizon: int = 5,
    forward_return_col: str | None = None,
) -> ICReport:
    """对 (ts, symbol, factor_col) 计算截面 IC + RankIC 序列与各项汇总。"""

    fwd_col = forward_return_col or f"forward_return_h{horizon}"
    if fwd_col not in panel.columns:
        panel = attach_forward_returns(panel, [horizon])
    df = panel.select(["ts", "symbol", factor_col, fwd_col]).drop_nulls()
    if df.is_empty():
        return ICReport(horizon=horizon, ic_mean=0.0, rank_ic_mean=0.0, ic_ir=0.0, rank_ic_ir=0.0, sample_count=0)
    by_ts = (
        df.group_by("ts")
        .agg(
            pl.corr(factor_col, fwd_col).alias("ic"),
            pl.corr(
                pl.col(factor_col).rank(),
                pl.col(fwd_col).rank(),
            ).alias("rank_ic"),
            pl.len().alias("n_symbols"),
        )
        .sort("ts")
    )
    ic_series = by_ts.get_column("ic").drop_nulls()
    rank_ic_series = by_ts.get_column("rank_ic").drop_nulls()
    ic_mean = float(ic_series.mean()) if ic_series.len() else 0.0
    ic_std = float(ic_series.std()) if ic_series.len() > 1 else 0.0
    rank_ic_mean = float(rank_ic_series.mean()) if rank_ic_series.len() else 0.0
    rank_ic_std = float(rank_ic_series.std()) if rank_ic_series.len() > 1 else 0.0
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0.0
    rank_ic_ir = rank_ic_mean / rank_ic_std if rank_ic_std > 0 else 0.0
    # D-F2-AUDIT(b)：NW HAC t——重叠 forward 窗口诱导自相关，lag 默认取 horizon-1。
    nw_lag = max(0, horizon - 1)
    ic_tstat_nw = newey_west_tstat(ic_series.to_list(), lag=nw_lag)
    return ICReport(
        horizon=horizon,
        ic_mean=ic_mean,
        rank_ic_mean=rank_ic_mean,
        ic_ir=ic_ir,
        rank_ic_ir=rank_ic_ir,
        sample_count=int(by_ts.height),
        ic_tstat_nw=ic_tstat_nw,
        nw_lag=nw_lag,
        by_period=by_ts.to_dicts()[:1000],
    )


def compute_ic_decay(
    panel: pl.DataFrame,
    factor_col: str,
    horizons: list[int] | None = None,
) -> list[ICReport]:
    """IC 衰减曲线：默认 [1, 3, 5, 10, 20] 日 horizon。"""

    if horizons is None:
        horizons = [1, 3, 5, 10, 20]
    panel = attach_forward_returns(panel, horizons)
    return [compute_ic_report(panel, factor_col, horizon=h) for h in horizons]


__all__ = [
    "ICReport",
    "attach_forward_returns",
    "compute_ic_decay",
    "compute_ic_report",
    "newey_west_tstat",
]
