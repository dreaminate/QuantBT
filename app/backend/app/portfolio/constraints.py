"""M8 · 组合约束实施。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np


@dataclass
class PortfolioConstraints:
    single_pos_max: float = 0.10
    leverage_max: float = 1.0
    short_allowed: bool = False
    sector_cap: float | None = None
    sector_map: Mapping[str, str] | None = None
    pair_corr_cap: float | None = None


def apply_constraints(
    weights: dict[str, float],
    constraints: PortfolioConstraints,
    *,
    correlations: dict[tuple[str, str], float] | None = None,
) -> dict[str, float]:
    """对一组 (symbol → weight) 做截断 + 行业上限 + 强相关二选一 + 杠杆归一。"""

    cleaned: dict[str, float] = {}
    for sym, w in weights.items():
        if not np.isfinite(w):
            continue
        if not constraints.short_allowed and w < 0:
            w = 0.0
        # 单标的上限
        if w > 0:
            w = min(w, constraints.single_pos_max)
        else:
            w = max(w, -constraints.single_pos_max)
        cleaned[sym] = w

    # 行业上限
    if constraints.sector_cap and constraints.sector_map:
        sector_total: dict[str, float] = {}
        for sym, w in cleaned.items():
            sector = constraints.sector_map.get(sym, "_other")
            sector_total[sector] = sector_total.get(sector, 0.0) + abs(w)
        for sector, total in sector_total.items():
            if total > constraints.sector_cap and total > 0:
                scale = constraints.sector_cap / total
                for sym in list(cleaned):
                    if constraints.sector_map.get(sym, "_other") == sector:
                        cleaned[sym] *= scale

    # 强相关二选一：保留绝对权重较大者
    if constraints.pair_corr_cap is not None and correlations:
        drop: set[str] = set()
        for (a, b), c in correlations.items():
            if a in drop or b in drop:
                continue
            if abs(c) >= constraints.pair_corr_cap:
                if abs(cleaned.get(a, 0.0)) >= abs(cleaned.get(b, 0.0)):
                    drop.add(b)
                else:
                    drop.add(a)
        for sym in drop:
            cleaned[sym] = 0.0

    # 杠杆归一
    gross = sum(abs(w) for w in cleaned.values())
    if gross > constraints.leverage_max and gross > 0:
        scale = constraints.leverage_max / gross
        cleaned = {k: v * scale for k, v in cleaned.items()}
    return cleaned


__all__ = ["PortfolioConstraints", "apply_constraints"]
