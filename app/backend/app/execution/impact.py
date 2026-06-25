"""R18 · 平方根市场冲击成本（size-aware impact）——**单一公式源**。

GOAL §4「平方根冲击 δ=0.5 窄带（R18）」。设计/推导见
`dev/research/findings/dreaminate/sqrt-impact-backtest-cost.md`。

冲击成本（占成交名义比例）= Y·σ·(Q/ADV)^δ，δ=0.5 锁定（R18 窄带）。理论：Kyle-λ/propagator + 海量实证
给出冲击对单量**凹**（指数≈0.5）；总冲击 ∝ Q^1.5 ⇒ 大单边际成本升（容量约束的微观来源）。

**命门一致性**：本函数是回测成本模型（`backtest_venue.BacktestCostModel`）与 §3 容量度量
（`factor_factory.lifecycle_metrics.strategy_capacity`）共用的同一 sqrt-impact 物理——策略在容量 C 处单期
冲击成本（占 AUM 比）恒等于毛 alpha（容量定义）。交叉校验测试钉死两路一致。
"""

from __future__ import annotations

import math

IMPACT_DELTA = 0.5   # R18 锁定：平方根冲击 δ=0.5 窄带（改离须显式、文档标）


def square_root_impact_fraction(
    participation: float,
    volatility: float,
    impact_coef: float,
    delta: float = IMPACT_DELTA,
) -> float:
    """平方根冲击成本占成交名义的比例 = Y·σ·participation^δ。

    `participation`=Q/ADV（本笔成交量 / 日均成交量，无量纲）；`volatility`=σ；`impact_coef`=Y。
    退化安全（绝不返 NaN/负冲击）：participation≤0 / σ≤0 / Y≤0 → 0.0（无冲击，非假数）。
    """

    if not all(math.isfinite(v) for v in (participation, volatility, impact_coef, delta)):
        return 0.0
    if participation <= 0.0 or volatility <= 0.0 or impact_coef <= 0.0 or delta <= 0.0:
        return 0.0
    return float(impact_coef * volatility * participation ** delta)


__all__ = ["IMPACT_DELTA", "square_root_impact_fraction"]
