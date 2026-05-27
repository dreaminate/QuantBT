"""M5 · 标签函数实现。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import polars as pl


@dataclass(frozen=True)
class LabelStats:
    label_type: str
    rows: int
    positive_share: float | None = None
    negative_share: float | None = None
    timeout_share: float | None = None


def _ensure_required(panel: pl.DataFrame, cols: list[str]) -> None:
    missing = [c for c in cols if c not in panel.columns]
    if missing:
        raise ValueError(f"label 需要列 {cols}，缺失 {missing}")


def raw_return_label(panel: pl.DataFrame, horizon: int = 1) -> pl.DataFrame:
    """raw forward return = close[t+h] / close[t] - 1"""

    _ensure_required(panel, ["ts", "symbol", "close"])
    df = panel.sort(["symbol", "ts"]).with_columns(
        ((pl.col("close").shift(-horizon) / pl.col("close")) - 1).over("symbol").alias("label_raw_return")
    )
    return df.select(["ts", "symbol", "label_raw_return"])


def excess_return_label(
    panel: pl.DataFrame,
    benchmark_panel: pl.DataFrame,
    horizon: int = 1,
) -> pl.DataFrame:
    """超额 = 个股 forward return - 同一 ts 上基准 forward return。"""

    _ensure_required(panel, ["ts", "symbol", "close"])
    _ensure_required(benchmark_panel, ["ts", "close"])
    sym_returns = raw_return_label(panel, horizon).rename({"label_raw_return": "stock_fwd"})
    bench = (
        benchmark_panel.sort("ts")
        .with_columns(((pl.col("close").shift(-horizon) / pl.col("close")) - 1).alias("bench_fwd"))
        .select(["ts", "bench_fwd"])
    )
    merged = sym_returns.join(bench, on="ts", how="left")
    return merged.with_columns(
        (pl.col("stock_fwd") - pl.col("bench_fwd")).alias("label_excess_return")
    ).select(["ts", "symbol", "label_excess_return"])


def xs_rank_label(panel: pl.DataFrame, horizon: int = 1) -> pl.DataFrame:
    """归一化截面排名（0..1）作为 learning-to-rank 标签。"""

    fwd = raw_return_label(panel, horizon).rename({"label_raw_return": "fwd"})
    ranked = fwd.with_columns(
        ((pl.col("fwd").rank("ordinal").over("ts").cast(pl.Float64) - 1)
         / (pl.len().over("ts").cast(pl.Float64) - 1).clip(lower_bound=1.0)).alias("label_xs_rank")
    )
    return ranked.select(["ts", "symbol", "label_xs_rank"])


def vol_adjusted_return_label(
    panel: pl.DataFrame,
    horizon: int = 1,
    vol_window: int = 20,
) -> pl.DataFrame:
    """forward return / 滚动 σ（EWMA-like）。"""

    _ensure_required(panel, ["ts", "symbol", "close"])
    sorted_panel = panel.sort(["symbol", "ts"])
    df = sorted_panel.with_columns(
        ((pl.col("close").shift(-horizon) / pl.col("close")) - 1).over("symbol").alias("fwd"),
        (pl.col("close").pct_change()).over("symbol").alias("ret_1d"),
    )
    df = df.with_columns(
        pl.col("ret_1d").rolling_std(window_size=vol_window).over("symbol").alias("vol_w")
    )
    df = df.with_columns(
        (pl.col("fwd") / pl.col("vol_w")).alias("label_vol_adjusted_return")
    )
    return df.select(["ts", "symbol", "label_vol_adjusted_return"])


def triple_barrier_label(
    panel: pl.DataFrame,
    *,
    take_profit_sigma: float = 2.0,
    stop_loss_sigma: float = 2.0,
    max_holding_days: int = 10,
    vol_window: int = 20,
) -> pl.DataFrame:
    """López de Prado 三重障碍。

    返回三元标签 (+1=触上沿/-1=触下沿/0=超时)；附带 hit_horizon、return_at_hit。
    实现说明：用 numpy/polars 循环，per-symbol O(N) 时间复杂度。
    """

    _ensure_required(panel, ["ts", "symbol", "close"])
    sorted_panel = panel.sort(["symbol", "ts"])
    sigma = (
        sorted_panel.with_columns(
            (pl.col("close").pct_change()).over("symbol").alias("ret_1d")
        )
        .with_columns(pl.col("ret_1d").rolling_std(window_size=vol_window).over("symbol").alias("sigma"))
        .select(["ts", "symbol", "close", "sigma"])
    )
    label_rows: list[dict] = []
    for sid, grp in sigma.group_by("symbol", maintain_order=True):
        symbol = sid[0] if isinstance(sid, tuple) else sid
        n = grp.height
        close = grp.get_column("close").to_numpy()
        sig = grp.get_column("sigma").to_numpy()
        ts = grp.get_column("ts").to_list()
        for i in range(n):
            entry_close = close[i]
            entry_sigma = sig[i]
            if entry_sigma is None or entry_sigma != entry_sigma:  # NaN
                label_rows.append({
                    "ts": ts[i],
                    "symbol": symbol,
                    "label_triple_barrier": None,
                    "hit_horizon": None,
                    "return_at_hit": None,
                })
                continue
            tp = entry_close * (1 + take_profit_sigma * entry_sigma)
            sl = entry_close * (1 - stop_loss_sigma * entry_sigma)
            label = 0
            hit_h = max_holding_days
            ret = 0.0
            end = min(n - 1, i + max_holding_days)
            for j in range(i + 1, end + 1):
                c = close[j]
                if c >= tp:
                    label = 1
                    hit_h = j - i
                    ret = (c / entry_close) - 1
                    break
                if c <= sl:
                    label = -1
                    hit_h = j - i
                    ret = (c / entry_close) - 1
                    break
            else:
                if end > i:
                    ret = (close[end] / entry_close) - 1
                    hit_h = end - i
            label_rows.append({
                "ts": ts[i],
                "symbol": symbol,
                "label_triple_barrier": label,
                "hit_horizon": hit_h,
                "return_at_hit": ret,
            })
    return pl.DataFrame(label_rows)


def meta_label(
    triple_barrier_df: pl.DataFrame,
    base_direction: pl.DataFrame,
) -> pl.DataFrame:
    """Meta labeling：base_direction 给方向，meta 决定是否下注。

    输入：
        triple_barrier_df: 含 `label_triple_barrier` (+1/-1/0)
        base_direction: 含 `direction` (+1/-1) 表示模型预测方向
    输出：
        `label_meta` 1 = 与 base 方向一致 → 下单；0 = 不下单。
    """

    merged = triple_barrier_df.join(base_direction, on=["ts", "symbol"], how="inner")
    return merged.with_columns(
        (
            (pl.col("direction") == pl.col("label_triple_barrier"))
            & (pl.col("label_triple_barrier") != 0)
        )
        .cast(pl.Int8)
        .alias("label_meta")
    ).select(["ts", "symbol", "label_meta"])


def label_stats(df: pl.DataFrame, label_col: str) -> LabelStats:
    """三分类标签的分布统计；其它标签只给样本数。"""

    if df.is_empty():
        return LabelStats(label_type=label_col, rows=0)
    rows = df.height
    if label_col == "label_triple_barrier":
        counts = df.get_column(label_col).value_counts().to_dict(as_series=False)
        values = counts.get(label_col, counts.get("label_triple_barrier", []))
        counts_map = counts.get("count", [])
        total = sum(counts_map) if counts_map else 1
        ratios: dict[int, float] = {}
        for v, c in zip(values, counts_map):
            if v is None:
                continue
            ratios[int(v)] = c / total
        return LabelStats(
            label_type=label_col,
            rows=rows,
            positive_share=ratios.get(1, 0.0),
            negative_share=ratios.get(-1, 0.0),
            timeout_share=ratios.get(0, 0.0),
        )
    return LabelStats(label_type=label_col, rows=rows)


__all__ = [
    "LabelStats",
    "excess_return_label",
    "label_stats",
    "meta_label",
    "raw_return_label",
    "triple_barrier_label",
    "vol_adjusted_return_label",
    "xs_rank_label",
]
