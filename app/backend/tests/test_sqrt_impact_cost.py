"""R18 平方根市场冲击 回测成本项 对抗测试。

设计/推导见 `dev/research/findings/dreaminate/sqrt-impact-backtest-cost.md`。门必抓：
- 向后兼容：impact_coef=0（默认）→ 成本与改前逐位相等（现有回测不破）。
- 平方根标度：participation×4 → impact_frac×2（δ=0.5）；写成线性/常数 → 抓。
- 大单惩罚：高 participation 单位成本 > 低 participation。
- 命门交叉校验：容量 C 处单期冲击占 AUM 比 == 毛 alpha（绑 strategy_capacity）。
- 不假绿灯：impact_coef>0 但无 volume → init raise（绝不静默 0 冲击）。
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from app.execution.backtest_venue import BacktestCostModel, BacktestVenue
from app.execution.impact import IMPACT_DELTA, square_root_impact_fraction
from app.factor_factory.lifecycle_metrics import strategy_capacity


def _panel(n=60, sigma=0.02, seed=0, with_volume=True):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.standard_normal(n) * sigma))
    cols = {
        "ts": list(range(n)), "symbol": ["BTC"] * n,
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
    }
    if with_volume:
        cols["volume"] = [1000.0] * n
    return pl.DataFrame(cols)


# ===========================================================================
# square_root_impact_fraction（单一公式源）
# ===========================================================================


def test_impact_fraction_sqrt_scaling():
    """participation×4 → impact_frac×2（δ=0.5 √律）。写成 δ=1 线性会得 ×4。"""
    f1 = square_root_impact_fraction(0.01, 0.02, 0.1)
    f4 = square_root_impact_fraction(0.04, 0.02, 0.1)
    assert abs(f4 / f1 - 2.0) < 1e-9


def test_impact_fraction_monotone_in_participation():
    fr = [square_root_impact_fraction(p, 0.02, 0.1) for p in (0.001, 0.01, 0.1, 0.3)]
    for i in range(len(fr) - 1):
        assert fr[i] < fr[i + 1]


def test_impact_fraction_degenerate_safe():
    assert square_root_impact_fraction(0.0, 0.02, 0.1) == 0.0          # participation 0
    assert square_root_impact_fraction(0.01, 0.0, 0.1) == 0.0          # σ 0
    assert square_root_impact_fraction(0.01, 0.02, 0.0) == 0.0         # coef 0
    assert square_root_impact_fraction(-0.5, 0.02, 0.1) == 0.0         # 负 participation
    assert square_root_impact_fraction(float("nan"), 0.02, 0.1) == 0.0


def test_impact_delta_locked_default_half():
    assert IMPACT_DELTA == 0.5


# ===========================================================================
# 回测成本集成
# ===========================================================================


def test_backward_compatible_impact_off_byte_identical():
    """默认 impact_coef=0 → 成本 = commission+slippage+stamp+transfer（无冲击项），与改前逐位相等。"""
    v = BacktestVenue(_panel(), BacktestCostModel())   # 默认 impact_coef=0
    cost = v._cost_for_trade("buy", 10, 100.0, "BTC")
    legacy = 10 * 100 * (5e-4) + 10 * 100 * (5e-4)     # commission 5bps + slippage 5bps
    assert abs(cost - legacy) < 1e-12


def test_large_order_costs_more_per_notional():
    """启用冲击：大单（高 participation）单位名义成本 > 小单（平 slippage 不会有此差）。"""
    v = BacktestVenue(_panel(sigma=0.03), BacktestCostModel(commission_bps=0, slippage_bps=0, impact_coef=0.5))
    small = v._cost_for_trade("buy", 10, 100.0, "BTC") / (10 * 100)     # participation=0.01
    big = v._cost_for_trade("buy", 300, 100.0, "BTC") / (300 * 100)     # participation=0.3
    assert big > small > 0.0
    assert abs((big / small) - (0.3 / 0.01) ** 0.5) < 1e-6              # 单位成本比 = √(part 比)


def test_impact_enabled_without_volume_raises():
    """不假绿灯：impact_coef>0 但 prices 无 volume → init raise（绝不静默当 0 冲击）。"""
    with pytest.raises(ValueError, match="volume"):
        BacktestVenue(_panel(with_volume=False), BacktestCostModel(impact_coef=0.5))


def test_impact_off_without_volume_ok():
    """impact 关时无 volume 不报错（向后兼容：现有无 volume 回测照跑）。"""
    v = BacktestVenue(_panel(with_volume=False), BacktestCostModel())
    assert v._cost_for_trade("buy", 10, 100.0, "BTC") > 0


# ===========================================================================
# 命门：与 §3 容量交叉校验（同一 sqrt-impact 物理）
# ===========================================================================


def test_impact_enabled_invalid_adv_fails_fast_not_silent_zero():
    """codex P2：冲击启用但 symbol volume 全 0 → ADV 无效 → 成交时 raise，绝不静默当 0 冲击（假绿灯）。"""
    df = _panel()
    df = df.with_columns(pl.lit(0.0).alias("volume"))   # volume 全 0 → ADV=0
    v = BacktestVenue(df, BacktestCostModel(impact_coef=0.5))
    with pytest.raises(ValueError, match="ADV|无效|volume"):
        v._cost_for_trade("buy", 10, 100.0, "BTC")


def test_intraday_volume_aggregated_to_daily_adv():
    """codex P2：日内 datetime 数据按**日**聚合 ADV（非每 bar 均量）——否则参与率抬高 √(bars/日)、冲击高估。"""
    import datetime as dt

    rows = []
    for d in (1, 2, 3, 4):
        for h in range(24):                              # 24 根 1h bar/日，每根量 100
            rows.append((dt.datetime(2020, 1, d, h), "ETH", 50.0, 50.5, 49.5, 50.0, 100.0))
    df = pl.DataFrame(rows, schema=["ts", "symbol", "open", "high", "low", "close", "volume"], orient="row")
    v = BacktestVenue(df, BacktestCostModel(impact_coef=0.3))
    assert abs(v._impact_adv["ETH"] - 24 * 100.0) < 1e-6   # 日 ADV=2400，非每 bar 100


def test_auto_estimate_emits_lookahead_warning():
    """评审 high·前视红线 §7 处置：自估 ADV/σ 用全样本含未来 → 启用即 emit 响亮 warning（残余代码可见、标用户自负）。"""
    with pytest.warns(UserWarning, match="前视|look-ahead|未来"):
        BacktestVenue(_panel(), BacktestCostModel(impact_coef=0.5))


def test_explicit_adv_sigma_no_warning_and_used():
    """无泄露路径：调用方传点位 ADV/σ → 不触发前视 warning + 冲击用所传 ADV（绕开自估）。"""
    import warnings as _w

    cm = BacktestCostModel(commission_bps=0, slippage_bps=0, impact_coef=0.5,
                           impact_adv={"BTC": 2000.0}, impact_sigma={"BTC": 0.03})
    with _w.catch_warnings():
        _w.simplefilter("error")            # 若 emit 任何 warning 即失败
        v = BacktestVenue(_panel(), cm)     # 显式口径 → 无 warning
    # 冲击用所传 ADV=2000：participation=100/2000=0.05
    cost = v._cost_for_trade("buy", 100, 100.0, "BTC")
    expected = 100 * 100 * square_root_impact_fraction(100 / 2000.0, 0.03, 0.5)
    assert abs(cost - expected) < 1e-9


def test_default_off_emits_no_warning():
    """向后兼容：默认 impact_coef=0 → 不预算、不 warn（现有回测零噪声）。"""
    import warnings as _w

    with _w.catch_warnings():
        _w.simplefilter("error")
        BacktestVenue(_panel(), BacktestCostModel())   # 默认关 → 无 warning


def test_impact_at_capacity_equals_gross_alpha_cross_check():
    """**命门交叉校验**：策略在 §3 容量 C 处，单期冲击成本（占 AUM 比）== 毛 alpha（容量定义：净 alpha=0）。

    绑回测冲击模型于已验证的 strategy_capacity——同一 Y/σ/δ 物理，口径漂移则崩。
    """
    for a, tau, adv, sig, Y in [(0.0015, 0.08, 5e7, 0.015, 0.1), (0.003, 0.2, 1e8, 0.02, 0.2),
                                 (0.0008, 0.05, 2e7, 0.01, 0.15)]:
        C = strategy_capacity(a, tau, adv, sig, impact_coef=Y).capacity
        participation = tau * C / adv
        frac = square_root_impact_fraction(participation, sig, Y)   # 占成交名义比
        per_period_cost_of_aum = tau * frac                          # 交易 τ·C 名义、÷ C
        assert abs(per_period_cost_of_aum - a) < 1e-9, f"α={a} 冲击↔容量不一致"
