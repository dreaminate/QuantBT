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

    def to_dict(self) -> dict:
        return {"estimate": self.estimate, "lower": self.lower, "upper": self.upper, "n_boot": self.n_boot}


def bootstrap_sharpe_ci(
    returns: np.ndarray,
    n_boot: int = 1000,
    confidence: float = 0.95,
    periods_per_year: int = 252,
    seed: int | None = 42,
) -> BootstrapCI:
    rng = np.random.default_rng(seed)
    arr = np.asarray(returns, dtype=float)
    if arr.size < 5:
        sr = sharpe_ratio(arr, periods_per_year)
        return BootstrapCI(sr, sr, sr, n_boot)
    sharpes = np.empty(n_boot)
    for i in range(n_boot):
        sample = rng.choice(arr, size=arr.size, replace=True)
        sharpes[i] = sharpe_ratio(sample, periods_per_year)
    alpha = (1 - confidence) / 2
    lower = float(np.quantile(sharpes, alpha))
    upper = float(np.quantile(sharpes, 1 - alpha))
    return BootstrapCI(estimate=float(sharpe_ratio(arr, periods_per_year)), lower=lower, upper=upper, n_boot=n_boot)


__all__ = ["BootstrapCI", "bootstrap_sharpe_ci"]
