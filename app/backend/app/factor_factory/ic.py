"""M4 · 因子专业性硬指标：IC / Rank-IC / IC-IR / IC 衰减。

按 QuantBT-GOAL.md §2.2「专业性硬指标」要求：任何特征 PR 必须能产出
IC / Rank-IC / IC-IR / IC 衰减曲线（5/10/20 日 horizon）。

输入 panel：必须含列 (ts, symbol, factor_value, forward_return_h{n})。
我们额外提供 helper 自动从 close 价生成 `forward_return_h{n}`。
"""

from __future__ import annotations

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "ic_mean": _safe_float(self.ic_mean),
            "rank_ic_mean": _safe_float(self.rank_ic_mean),
            "ic_ir": _safe_float(self.ic_ir),
            "rank_ic_ir": _safe_float(self.rank_ic_ir),
            "sample_count": int(self.sample_count),
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
    return ICReport(
        horizon=horizon,
        ic_mean=ic_mean,
        rank_ic_mean=rank_ic_mean,
        ic_ir=ic_ir,
        rank_ic_ir=rank_ic_ir,
        sample_count=int(by_ts.height),
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


__all__ = ["ICReport", "attach_forward_returns", "compute_ic_decay", "compute_ic_report"]
