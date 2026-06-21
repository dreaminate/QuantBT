"""F2 · 分层回测（五分位 / N 分位）：因子单调性与多空价差的标准诊断。

口径（Grinold-Kahn / Fama-MacBeth 截面分层）：
- 每个截面期（ts）按因子值把 symbol 分成 N 组（默认 5 = 五分位），Q1=因子最低组、
  QN=最高组；
- 每组取该期【组内等权平均 forward-return】，跨期再平均得各分位的平均期收益；
- 多空价差 = QN − Q1（因子方向若为负则价差为负，单调性看 Q1→QN 是否近似单调）。

诚实边界（红线·前视）：
- forward-return **只**经 `ic.attach_forward_returns`（close.shift(-h) 正向滞后、按 symbol
  分组），分层逻辑绝不自造 forward 列——与 IC 端点共用单一滞后源，杜绝某处偷偷 shift(0)。
- 分位用「当期截面」的因子值定组（point-in-time），不混入未来信息定 bucket 边界。
- 这是【诊断】不是【可下注业绩】：无手续费 / 冲击成本 / 容量约束，单调即「方向证据」，
  不等于「能赚钱」——裁决文案不染绿。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import polars as pl

from .ic import attach_forward_returns
from .panel_source import factor_panel


@dataclass
class LayeredBucket:
    quantile: int          # 1..n_quantiles（1=因子最低组）
    mean_return: float     # 跨期平均的组内等权 forward-return
    n_obs: int             # 参与该组的 (ts, symbol) 观测数


@dataclass
class LayeredReport:
    horizon: int
    n_quantiles: int           # 请求的分位数
    effective_quantiles: int   # 实际生效分位数（截面 symbol 不足时被下调）
    buckets: list[LayeredBucket]
    long_short_spread: float   # QN.mean_return − Q1.mean_return
    monotonic: bool            # Q1→QN 是否单调（升或降）
    sample_count: int          # 参与的有效截面期数
    note: str

    def to_dict(self) -> dict:
        return {
            "horizon": self.horizon,
            "n_quantiles": self.n_quantiles,
            "effective_quantiles": self.effective_quantiles,
            "buckets": [asdict(b) for b in self.buckets],
            "long_short_spread": self.long_short_spread,
            "monotonic": self.monotonic,
            "sample_count": self.sample_count,
            "note": self.note,
        }


class LayeredError(ValueError):
    """分层回测口径违规（分位数过大 / 截面 symbol 不足分组）。"""


_NOTE = (
    "分层=每截面按因子值分 N 组取组内等权 fwd-return 跨期平均；多空价差=QN−Q1。"
    "无费用/冲击/容量约束，单调=方向证据≠可下注业绩。forward-return 走单一滞后源（不前视）。"
)


def _is_monotonic(values: list[float]) -> bool:
    if len(values) < 2:
        return False
    inc = all(values[i] <= values[i + 1] for i in range(len(values) - 1))
    dec = all(values[i] >= values[i + 1] for i in range(len(values) - 1))
    return inc or dec


def layered_backtest(
    market: str,
    formula: str,
    *,
    horizon: int = 5,
    n_quantiles: int = 5,
) -> LayeredReport:
    """对单因子在 market 上做 N 分位分层回测。"""

    if n_quantiles < 2:
        raise LayeredError("n_quantiles 必须 ≥ 2")
    factor_col = "factor_value"
    fp = factor_panel(market, formula, horizon=horizon, factor_alias=factor_col)
    fwd_col = f"forward_return_h{horizon}"
    panel = attach_forward_returns(fp, [horizon])
    df = panel.select(["ts", "symbol", factor_col, fwd_col]).drop_nulls()
    if df.is_empty():
        raise LayeredError("对齐后无有效 (因子, forward-return) 观测")
    # 截面 symbol 数不足请求分位数时，5 分位会有空桶（伪精确）。下调到最小截面 breadth，
    # 并在 effective_quantiles + note 披露（绝不假装分了 5 组）。
    min_breadth = int(
        df.group_by("ts").agg(pl.len().alias("n")).get_column("n").min() or 0
    )
    effective_q = min(n_quantiles, max(2, min_breadth)) if min_breadth >= 2 else 2
    if min_breadth < 2:
        raise LayeredError(f"截面 symbol 不足分组（min breadth={min_breadth} < 2）")
    # 每截面内按因子值分位：用 rank/count 映射到 1..effective_q（point-in-time）。
    # rank(method='ordinal') 0-based → 桶 = floor(rank * n / count) + 1，clamp 到 [1,n]。
    binned = df.with_columns(
        (
            (
                (pl.col(factor_col).rank(method="ordinal").over("ts") - 1)
                * effective_q
                / pl.len().over("ts")
            )
            .floor()
            .clip(0, effective_q - 1)
            .cast(pl.Int64)
            + 1
        ).alias("quantile")
    )
    # 每 (ts, quantile) 组内等权平均 → 每 quantile 跨期平均。
    by_q = (
        binned.group_by("quantile")
        .agg(
            pl.col(fwd_col).mean().alias("mean_return"),
            pl.len().alias("n_obs"),
        )
        .sort("quantile")
    )
    rows = by_q.to_dicts()
    present = {int(r["quantile"]): r for r in rows}
    buckets: list[LayeredBucket] = []
    for q in range(1, effective_q + 1):
        r = present.get(q)
        if r is None:
            buckets.append(LayeredBucket(quantile=q, mean_return=0.0, n_obs=0))
        else:
            buckets.append(
                LayeredBucket(
                    quantile=q,
                    mean_return=round(float(r["mean_return"]), 8),
                    n_obs=int(r["n_obs"]),
                )
            )
    q1 = buckets[0].mean_return
    qn = buckets[-1].mean_return
    spread = round(qn - q1, 8)
    monotonic = _is_monotonic([b.mean_return for b in buckets])
    sample_count = int(df.select("ts").n_unique())
    note = _NOTE
    if effective_q != n_quantiles:
        note = (
            f"⚠ 截面 symbol 仅 {min_breadth} 个 < 请求 {n_quantiles} 分位，已下调到 "
            f"{effective_q} 组（避免空桶伪精确）。" + _NOTE
        )
    return LayeredReport(
        horizon=horizon,
        n_quantiles=n_quantiles,
        effective_quantiles=effective_q,
        buckets=buckets,
        long_short_spread=spread,
        monotonic=monotonic,
        sample_count=sample_count,
        note=note,
    )


__all__ = ["LayeredBucket", "LayeredError", "LayeredReport", "layered_backtest"]
