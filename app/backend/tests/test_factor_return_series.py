"""单因子 per-period 多空收益序列 F_t 对抗测试（北极星「归因」阶段的真实因子收益物料）。

门必抓：
- **per-period 多空价差正确**：F_t = 顶分位组内等权 fwd-return − 底分位组内等权（合成 binned → 已知 F_t）。
- **缺一端不臆造**：某 ts 只有一端分位 → inner join 丢弃（不补 0·不假绿灯）。
- **不前视**：复用 `_binned_factor_panel`（同 layered 单一滞后源 + point-in-time 分桶），不另起 forward 列。
- **端到端**：factor_return_series 产的序列喂 attribution_from_series → 命门加总恒等式仍闭合。
"""

from __future__ import annotations

import math

import polars as pl
import pytest

from app.eval.attribution import attribution_from_series
from app.factor_factory.layered import (
    LayeredError,
    _per_period_long_short,
    factor_return_series,
)


def test_per_period_long_short_known_values():
    """合成 binned（已知分位/fwd）→ F_t = QN_t − Q1_t 逐期精确（顶/底分位组内等权之差）。"""
    fwd = "forward_return_h5"
    binned = pl.DataFrame({
        "ts": ["d1", "d1", "d1", "d1", "d2", "d2", "d2", "d2"],
        "quantile": [3, 3, 1, 1, 3, 3, 1, 1],
        fwd: [0.10, 0.20, 0.00, 0.02, 0.05, 0.05, 0.03, 0.03],
    })
    # d1: QN=mean(0.10,0.20)=0.15, Q1=mean(0.00,0.02)=0.01 → F=0.14
    # d2: QN=0.05, Q1=0.03 → F=0.02
    out = _per_period_long_short(binned, fwd, effective_q=3)
    assert out == [("d1", 0.14), ("d2", 0.02)]


def test_per_period_long_short_drops_ts_missing_one_tail():
    """某 ts 只有一端分位（缺顶或缺底）→ inner join 丢弃，绝不补 0（无价差≠零价差·不假绿灯）。"""
    fwd = "forward_return_h5"
    binned = pl.DataFrame({
        "ts": ["d1", "d1", "d2", "d3"],     # d2 只有 q3、d3 只有 q1
        "quantile": [3, 1, 3, 1],
        fwd: [0.10, 0.02, 0.07, 0.01],
    })
    out = _per_period_long_short(binned, fwd, effective_q=3)
    assert out == [("d1", round(0.10 - 0.02, 10))]   # 仅 d1 两端齐备


def test_per_period_long_short_sorted_by_ts():
    """输出按 ts 升序（喂 attribution_from_series 的对齐前置）。"""
    fwd = "forward_return_h5"
    binned = pl.DataFrame({
        "ts": ["d3", "d3", "d1", "d1", "d2", "d2"],
        "quantile": [2, 1, 2, 1, 2, 1],
        fwd: [0.3, 0.1, 0.10, 0.00, 0.2, 0.05],
    })
    out = _per_period_long_short(binned, fwd, effective_q=2)
    assert [t for t, _ in out] == ["d1", "d2", "d3"]


def test_factor_return_series_real_data_structure():
    """集成（真数据·equity_cn 4 symbol）：factor_return_series 产非空 [(ts, finite float)]，复用 layered 分桶不前视。"""
    try:
        series = factor_return_series("equity_cn", "ts_zscore(close, 20)", horizon=5, n_quantiles=4)
    except LayeredError as e:
        pytest.skip(f"测试市场数据不足以分层：{e}")
    assert isinstance(series, list) and len(series) > 0
    for ts, val in series:
        assert isinstance(ts, str) and isinstance(val, float) and math.isfinite(val)
    # 每期唯一（不重复截面）——排序正确性由纯测试 test_per_period_long_short_sorted_by_ts 覆盖
    # （真数据 ts 此处为整数索引串，polars 按列原生类型排序，非 Python 字典序）。
    tss = [t for t, _ in series]
    assert len(tss) == len(set(tss))


def test_factor_return_series_feeds_attribution_end_to_end():
    """端到端：factor_return_series → attribution_from_series（自归因 sanity：组合=因子本身 → β≈1、R²≈1）。

    用因子自身序列当『组合收益』回归该因子 → β̂≈1、几乎全解释（证物料可真喂归因、加总恒等式闭合）。
    """
    try:
        series = factor_return_series("equity_cn", "ts_zscore(close, 20)", horizon=5, n_quantiles=4)
    except LayeredError as e:
        pytest.skip(f"测试市场数据不足以分层：{e}")
    if len(series) < 4:
        pytest.skip("有效截面期不足以回归")
    port = {ts: val for ts, val in series}          # 组合收益 = 因子收益本身（自归因）
    r = attribution_from_series(port, {"selffac": series})
    # 命门加总恒等式闭合
    recomposed = sum(r.factor_contributions.values()) + r.specific_contribution
    assert abs(recomposed - r.total_return) <= 1e-9 * max(1.0, abs(r.total_return)) + 1e-9
    if r.status == "ok":
        assert abs(r.betas["selffac"] - 1.0) < 1e-6   # 自归因 β≈1
