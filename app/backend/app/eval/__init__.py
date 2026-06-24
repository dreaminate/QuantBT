"""M10 · 评估：PBO / DSR / PSR / Bootstrap Sharpe + Brinson 归因 + R23 conformal 区间。"""

from __future__ import annotations

from .bootstrap import BootstrapCI, bootstrap_sharpe_ci
from .brinson import BrinsonResult, brinson_attribution
from .conformal import (
    AdaptiveConformalInference,
    ConformalInterval,
    SplitConformalCalibrator,
    cqr_interval,
    split_conformal_interval,
)
from .dsr import deflated_sharpe_ratio, probabilistic_sharpe_ratio, sharpe_ratio
from .n_eff import NEffResult, n_eff_from_matrix
from .overfit_gate import GateVerdict, run_overfit_gate
from .pbo import cscv_pbo

__all__ = [
    "AdaptiveConformalInference",
    "BootstrapCI",
    "BrinsonResult",
    "ConformalInterval",
    "GateVerdict",
    "NEffResult",
    "SplitConformalCalibrator",
    "bootstrap_sharpe_ci",
    "brinson_attribution",
    "cqr_interval",
    "cscv_pbo",
    "deflated_sharpe_ratio",
    "n_eff_from_matrix",
    "probabilistic_sharpe_ratio",
    "run_overfit_gate",
    "sharpe_ratio",
    "split_conformal_interval",
]
