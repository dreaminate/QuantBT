"""M5 · 标签构建。

GOAL §M5 列出的 6 类标签全部在此实现，均接受 panel DataFrame (ts, symbol, close, ...)
并返回 (ts, symbol, label, label_meta...)。

- raw_return / excess_return：回归标签
- xs_rank：截面排名标签
- triple_barrier：López de Prado 三重障碍（多/空/超时三分类）
- meta_label：基于 base direction 与实际结果决定是否下单
- vol_adjusted：波动率调整收益（跨标的可比）

避免 mlfinlab 依赖；triple_barrier 自写 < 200 行实现。
"""

from __future__ import annotations

from .core import (
    LabelStats,
    excess_return_label,
    meta_label,
    raw_return_label,
    triple_barrier_label,
    vol_adjusted_return_label,
    xs_rank_label,
)

__all__ = [
    "LabelStats",
    "excess_return_label",
    "meta_label",
    "raw_return_label",
    "triple_barrier_label",
    "vol_adjusted_return_label",
    "xs_rank_label",
]
