"""Combinatorial Symmetric Cross Validation (CSCV) → PBO。

López de Prado 2014 算法（简化版）：
- 把样本按时间划分成 S 段；从 S 段中选 S/2 训练，剩 S/2 测试，组合 C(S, S/2)
- 每个 split 上对若干策略评估 SR；取训练集 argmax，看其在测试集的 SR 排名
- PBO = 训练 argmax 在测试集排名 <= median 的频率

简化：当策略数 N 大、S 大时组合爆炸，工程上 cap n_combinations 上限。
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class PBOResult:
    pbo: float
    n_strategies: int
    n_combinations: int
    s_blocks: int
    # v0.8.7.1 学术 audit 字段
    lambda_logit_mean: float = float("nan")  # Bailey-LdP logit 形式均值
    expected_combinations_full: int = 0       # 完整 C(S, S/2) 应有组合数
    enumerated_full: bool = False             # 是否真全枚举（未采样）

    def to_dict(self) -> dict:
        return {
            "pbo": float(self.pbo),
            "n_strategies": int(self.n_strategies),
            "n_combinations": int(self.n_combinations),
            "s_blocks": int(self.s_blocks),
            "lambda_logit_mean": float(self.lambda_logit_mean),
            "expected_combinations_full": int(self.expected_combinations_full),
            "enumerated_full": bool(self.enumerated_full),
        }


def _sharpe_per_period(returns: np.ndarray) -> np.ndarray:
    """对每列策略算 Sharpe（per-period，未年化）。"""

    means = returns.mean(axis=0)
    stds = returns.std(axis=0, ddof=1)
    out = np.zeros_like(means)
    mask = stds > 1e-12
    out[mask] = means[mask] / stds[mask]
    return out


class PBOConfigError(ValueError):
    """PBO 配置违反 Bailey-LdP CSCV 约束（S 奇 / N 过小 / 完整枚举不可行）。"""


def cscv_pbo(
    returns_matrix: np.ndarray,
    s_blocks: int = 8,
    max_combinations: int = 200,
    *,
    min_n_strategies: int = 10,
    enumerate_all: bool = False,
    strict: bool = False,
) -> PBOResult:
    """returns_matrix: shape (T, N_strategies)；每列一条策略的逐期收益。

    v0.8.7.1 学术 audit (patch1 §G.a #1 / §G.d):
    - s_blocks 必须为偶数（CSCV 要求对称分割）
    - n_strategies < min_n_strategies (默认 10) → 估计噪声太大，strict 模式拒绝
    - enumerate_all=True 时强制全枚举所有 C(S, S/2) 组合；S=8→70, S=16→12870
    - strict=True 时违反任意约束 raise PBOConfigError
    - PBOResult 增加 lambda_logit_mean 字段 (Bailey-LdP logit form)
    """

    rm = np.asarray(returns_matrix, dtype=float)
    if rm.ndim != 2:
        if strict:
            raise PBOConfigError(f"returns_matrix 必须是 2D，得到 ndim={rm.ndim}")
        return PBOResult(pbo=float("nan"), n_strategies=0, n_combinations=0, s_blocks=s_blocks)

    if s_blocks % 2 != 0:
        if strict:
            raise PBOConfigError(f"s_blocks 必须为偶数 (CSCV 要求)，得到 {s_blocks}")
        return PBOResult(pbo=float("nan"), n_strategies=rm.shape[1], n_combinations=0, s_blocks=s_blocks)

    if s_blocks < 4:
        if strict:
            raise PBOConfigError(f"s_blocks 必须 >= 4，得到 {s_blocks}")
        return PBOResult(pbo=float("nan"), n_strategies=rm.shape[1], n_combinations=0, s_blocks=s_blocks)

    if rm.shape[0] < s_blocks * 2 or rm.shape[1] < 2:
        if strict:
            raise PBOConfigError(
                f"returns_matrix 行数 {rm.shape[0]} < s_blocks*2 ({s_blocks*2}) 或 列数 {rm.shape[1]} < 2"
            )
        return PBOResult(pbo=float("nan"), n_strategies=rm.shape[1], n_combinations=0, s_blocks=s_blocks)

    if rm.shape[1] < min_n_strategies and strict:
        raise PBOConfigError(
            f"n_strategies={rm.shape[1]} < min_n_strategies={min_n_strategies}；"
            f"PBO 衡量的是 *策略选择程序* 的可靠性，单策略或少策略输出无意义"
        )

    t, n = rm.shape
    block_size = t // s_blocks
    blocks = [rm[i * block_size : (i + 1) * block_size] for i in range(s_blocks)]
    half = s_blocks // 2

    # 完整枚举或采样：enumerate_all=True 强制全枚举
    all_combos = list(itertools.combinations(range(s_blocks), half))
    target = len(all_combos)
    if enumerate_all:
        combos = all_combos  # 不采样
    elif len(all_combos) > max_combinations:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(all_combos), size=max_combinations, replace=False)
        combos = [all_combos[i] for i in idx]
    else:
        combos = all_combos

    losses: list[int] = []
    logits: list[float] = []
    for is_train in combos:
        train_idx = set(is_train)
        test_idx = [i for i in range(s_blocks) if i not in train_idx]
        train_returns = np.concatenate([blocks[i] for i in is_train], axis=0)
        test_returns = np.concatenate([blocks[i] for i in test_idx], axis=0)
        train_sr = _sharpe_per_period(train_returns)
        test_sr = _sharpe_per_period(test_returns)
        best_strategy = int(np.argmax(train_sr))
        # 计算 OOS 相对排名 ω̄ ∈ (0, 1)（排名 / N）；patch1 公式 lambda = logit(ω̄)
        # argsort negative → 排名 0 = OOS 最高
        ranks = np.argsort(np.argsort(-test_sr))  # 0=best
        rank_best_is = int(ranks[best_strategy])  # 0..N-1
        omega_bar = 1.0 - (rank_best_is + 0.5) / n  # 越高 = OOS 越好
        omega_bar = min(max(omega_bar, 1e-6), 1 - 1e-6)
        lambda_logit = math.log(omega_bar / (1 - omega_bar))
        logits.append(lambda_logit)
        losses.append(1 if lambda_logit < 0 else 0)

    pbo = float(sum(losses) / len(losses)) if losses else float("nan")
    lambda_mean = float(sum(logits) / len(logits)) if logits else float("nan")
    expected_combos = target  # 完整 C(S, S/2)
    return PBOResult(
        pbo=pbo,
        n_strategies=n,
        n_combinations=len(combos),
        s_blocks=s_blocks,
        lambda_logit_mean=lambda_mean,
        expected_combinations_full=expected_combos,
        enumerated_full=(len(combos) == expected_combos),
    )


__all__ = ["PBOConfigError", "PBOResult", "cscv_pbo"]
