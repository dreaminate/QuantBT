"""M4b · "Alpha101-lite" — 30 个 WorldQuant 风格的简化经典因子。

为什么是 lite：WorldQuant 原 paper 中很多 alpha 含嵌套 cs_rank() 或自定义辅助
量（vwap / adv / returns），不能 1:1 平移到当前两阶段 evaluator 里。我们选取
30 个"概念清晰、可白盒表达式、能直接跑 IC"的近亲，每个都标注原 alpha 编号或
类别（动量/反转/波动率/量价背离/流动性）。

每个条目都通过 `register_alpha_lite(registry)` 加入 FactorRegistry，初始
lifecycle_state=NEW，等待 M11 状态机判定。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .registry import FactorRegistry


@dataclass(frozen=True)
class _AlphaSpec:
    factor_id: str
    formula: str
    description: str


_SPECS: tuple[_AlphaSpec, ...] = (
    # ── 动量族 ──
    _AlphaSpec("alpha_mom_1d", "ts_pct_change(close, 1)", "1 日动量"),
    _AlphaSpec("alpha_mom_5d", "ts_pct_change(close, 5)", "1 周动量"),
    _AlphaSpec("alpha_mom_20d", "ts_pct_change(close, 20)", "1 月动量"),
    _AlphaSpec("alpha_mom_60d", "ts_pct_change(close, 60)", "3 月动量"),
    _AlphaSpec("alpha_mom_xs_20d", "rank(ts_pct_change(close, 20))", "1 月动量截面排名"),
    _AlphaSpec("alpha_mom_xs_60d", "rank(ts_pct_change(close, 60))", "3 月动量截面排名"),
    # ── 反转族 ──
    _AlphaSpec("alpha_reversal_5d", "neg(ts_pct_change(close, 5))", "1 周反转"),
    _AlphaSpec("alpha_reversal_xs_1d", "rank(neg(ts_pct_change(close, 1)))", "日反转截面排名"),
    _AlphaSpec(
        "alpha_reversal_residual_20d",
        "neg(ts_zscore(close, 20))",
        "20 日 z-score 反转（高于均值看空）",
    ),
    # ── 波动率族 ──
    _AlphaSpec("alpha_vol_20d", "ts_std(ts_pct_change(close, 1), 20)", "20 日已实现波动率"),
    _AlphaSpec("alpha_vol_xs_20d", "rank(ts_std(ts_pct_change(close, 1), 20))", "波动率截面排名"),
    _AlphaSpec(
        "alpha_vol_ratio",
        "ts_std(ts_pct_change(close, 1), 5) / ts_std(ts_pct_change(close, 1), 60)",
        "短/长期波动率比",
    ),
    _AlphaSpec("alpha_drawdown_60d", "ts_min(close, 60) / ts_max(close, 60)", "60 日最大回撤近似"),
    # ── 均线偏离 ──
    _AlphaSpec("alpha_sma_dev_20d", "(close - ts_mean(close, 20)) / ts_mean(close, 20)", "20 日均线偏离"),
    _AlphaSpec("alpha_sma_dev_60d", "(close - ts_mean(close, 60)) / ts_mean(close, 60)", "60 日均线偏离"),
    _AlphaSpec("alpha_ema_cross", "ts_ema(close, 5) - ts_ema(close, 20)", "EMA 5-20 金叉"),
    # ── 量能 / 流动性 ──
    _AlphaSpec("alpha_volume_growth_5d", "ts_pct_change(volume, 5)", "成交量 5 日变化"),
    _AlphaSpec("alpha_volume_xs_5d", "rank(ts_pct_change(volume, 5))", "成交量变化截面排名"),
    _AlphaSpec("alpha_amount_zscore_20d", "ts_zscore(amount, 20)", "成交额 20 日 z-score"),
    _AlphaSpec("alpha_vol_to_avg_20d", "volume / ts_mean(volume, 20)", "量比"),
    # ── 量价 ──
    _AlphaSpec(
        "alpha_close_to_volume_ratio",
        "ts_zscore(close / (volume + 1), 20)",
        "(close/volume) 20 日 z-score",
    ),
    _AlphaSpec(
        "alpha_price_volume_corr_20d",
        "ts_corr(close, volume, 20)",
        "20 日价量相关性（Alpha#6 近亲）",
    ),
    _AlphaSpec(
        "alpha_high_low_range_5d",
        "(ts_max(high, 5) - ts_min(low, 5)) / close",
        "5 日真实波幅 / 收盘",
    ),
    _AlphaSpec(
        "alpha_close_in_range_5d",
        "(close - ts_min(low, 5)) / (ts_max(high, 5) - ts_min(low, 5))",
        "Stochastic K 形式",
    ),
    # ── 横截面打分 ──
    _AlphaSpec("alpha_xs_zscore_close", "zscore(close)", "收盘价截面 z-score（市值代理）"),
    _AlphaSpec(
        "alpha_xs_demean_log_volume",
        "cs_demean(log(volume + 1))",
        "成交量对数截面去均值（Alpha#2 近亲）",
    ),
    _AlphaSpec(
        "alpha_xs_winsor_mom20",
        "cs_winsorize(ts_pct_change(close, 20))",
        "1 月动量截面截尾",
    ),
    # ── 量化 + 波动调整 ──
    _AlphaSpec(
        "alpha_vol_adj_mom_20d",
        "ts_pct_change(close, 20) / ts_std(ts_pct_change(close, 1), 20)",
        "波动调整 1 月动量（夏普风格）",
    ),
    _AlphaSpec(
        "alpha_decay_close",
        "ts_decay_linear(close, 10)",
        "线性衰减加权收盘",
    ),
    _AlphaSpec(
        "alpha_skew_returns_60d",
        "ts_skew(ts_pct_change(close, 1), 60)",
        "60 日收益偏度",
    ),
)


def alpha_lite_specs() -> Iterable[_AlphaSpec]:
    return _SPECS


def register_alpha_lite(registry: FactorRegistry, *, author: str = "quantbt_seed") -> list[str]:
    """把 30 个内置因子注册到给定 registry；返回因子 id 列表。"""

    out: list[str] = []
    for spec in _SPECS:
        registry.register(
            factor_id=spec.factor_id,
            formula=spec.formula,
            author=author,
            description=spec.description,
        )
        out.append(spec.factor_id)
    return out


__all__ = ["alpha_lite_specs", "register_alpha_lite"]
