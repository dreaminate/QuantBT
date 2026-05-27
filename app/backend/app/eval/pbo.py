"""Combinatorial Symmetric Cross Validation (CSCV) → PBO。

López de Prado 2014 算法（简化版）：
- 把样本按时间划分成 S 段；从 S 段中选 S/2 训练，剩 S/2 测试，组合 C(S, S/2)
- 每个 split 上对若干策略评估 SR；取训练集 argmax，看其在测试集的 SR 排名
- PBO = 训练 argmax 在测试集排名 <= median 的频率

简化：当策略数 N 大、S 大时组合爆炸，工程上 cap n_combinations 上限。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np


@dataclass
class PBOResult:
    pbo: float
    n_strategies: int
    n_combinations: int
    s_blocks: int

    def to_dict(self) -> dict:
        return {
            "pbo": float(self.pbo),
            "n_strategies": int(self.n_strategies),
            "n_combinations": int(self.n_combinations),
            "s_blocks": int(self.s_blocks),
        }


def _sharpe_per_period(returns: np.ndarray) -> np.ndarray:
    """对每列策略算 Sharpe（per-period，未年化）。"""

    means = returns.mean(axis=0)
    stds = returns.std(axis=0, ddof=1)
    out = np.zeros_like(means)
    mask = stds > 1e-12
    out[mask] = means[mask] / stds[mask]
    return out


def cscv_pbo(
    returns_matrix: np.ndarray,
    s_blocks: int = 8,
    max_combinations: int = 200,
) -> PBOResult:
    """returns_matrix: shape (T, N_strategies)；每列一条策略的逐期收益。"""

    rm = np.asarray(returns_matrix, dtype=float)
    if rm.ndim != 2 or rm.shape[0] < s_blocks * 2 or rm.shape[1] < 2:
        return PBOResult(pbo=float("nan"), n_strategies=rm.shape[1] if rm.ndim == 2 else 0,
                         n_combinations=0, s_blocks=s_blocks)
    t, n = rm.shape
    block_size = t // s_blocks
    blocks = [rm[i * block_size : (i + 1) * block_size] for i in range(s_blocks)]
    half = s_blocks // 2
    all_combos = list(itertools.combinations(range(s_blocks), half))
    if len(all_combos) > max_combinations:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(all_combos), size=max_combinations, replace=False)
        all_combos = [all_combos[i] for i in idx]
    losses: list[int] = []
    for is_train in all_combos:
        train_idx = set(is_train)
        test_idx = [i for i in range(s_blocks) if i not in train_idx]
        train_returns = np.concatenate([blocks[i] for i in is_train], axis=0)
        test_returns = np.concatenate([blocks[i] for i in test_idx], axis=0)
        train_sr = _sharpe_per_period(train_returns)
        test_sr = _sharpe_per_period(test_returns)
        best_strategy = int(np.argmax(train_sr))
        test_ranks = np.argsort(np.argsort(-test_sr))  # 排名 0=最好
        rank = int(test_ranks[best_strategy])
        losses.append(1 if rank > n // 2 else 0)
    pbo = float(sum(losses) / len(losses)) if losses else float("nan")
    return PBOResult(pbo=pbo, n_strategies=n, n_combinations=len(all_combos), s_blocks=s_blocks)


__all__ = ["PBOResult", "cscv_pbo"]
