"""Bootstrap Sharpe 95% CI（GOAL §6.1 要求）。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dsr import sharpe_ratio


@dataclass
class BootstrapCI:
    estimate: float
    lower: float
    upper: float
    n_boot: int
    method: str = "iid"   # "iid"（独立重抽）| "block"（moving-block，保留序列相关）

    def to_dict(self) -> dict:
        return {"estimate": self.estimate, "lower": self.lower, "upper": self.upper,
                "n_boot": self.n_boot, "method": self.method}

    def to_tuple(self) -> tuple[float, float]:
        return (self.lower, self.upper)


def _moving_block_sample(arr: np.ndarray, block_size: int, rng: np.random.Generator) -> np.ndarray:
    """moving-block 重抽：抽连续块拼接到原长度，保留块内自相关（iid 会抹掉序列结构）。"""

    t = arr.size
    n_blocks = -(-t // block_size)   # ceil
    max_start = max(1, t - block_size + 1)
    starts = rng.integers(0, max_start, size=n_blocks)
    pieces = [arr[s : s + block_size] for s in starts]
    return np.concatenate(pieces)[:t]


def bootstrap_sharpe_ci(
    returns: np.ndarray,
    n_boot: int = 1000,
    confidence: float = 0.95,
    periods_per_year: int = 252,
    seed: int | None = 42,
    block_size: int | None = None,
) -> BootstrapCI:
    """Bootstrap Sharpe CI。

    `block_size=None` → iid 重抽（向后兼容；dossier §6 点名 iid 会低估方差，因为抹掉了
    收益的序列相关）。给值 → moving-block 重抽，保留自相关，CI 更诚实（更宽）。
    """

    rng = np.random.default_rng(seed)
    arr = np.asarray(returns, dtype=float)
    method = "block" if block_size and block_size >= 1 else "iid"
    if arr.size < 5:
        sr = sharpe_ratio(arr, periods_per_year)
        return BootstrapCI(sr, sr, sr, n_boot, method)
    eff_block = int(block_size) if method == "block" else 0
    # block ≥ T 会让每个重抽样≈整条序列 → 零宽（伪精确）CI；上限 T//2 保证块间仍有变异。
    if eff_block >= arr.size:
        eff_block = max(1, arr.size // 2)
    sharpes = np.empty(n_boot)
    for i in range(n_boot):
        if method == "block":
            sample = _moving_block_sample(arr, eff_block, rng)
        else:
            sample = rng.choice(arr, size=arr.size, replace=True)
        sharpes[i] = sharpe_ratio(sample, periods_per_year)
    alpha = (1 - confidence) / 2
    lower = float(np.quantile(sharpes, alpha))
    upper = float(np.quantile(sharpes, 1 - alpha))
    return BootstrapCI(estimate=float(sharpe_ratio(arr, periods_per_year)),
                       lower=lower, upper=upper, n_boot=n_boot, method=method)


__all__ = ["BootstrapCI", "bootstrap_sharpe_ci"]
