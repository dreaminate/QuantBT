"""M10 · 评估：PBO / DSR / Bootstrap Sharpe + Brinson 归因。"""

from __future__ import annotations

from .bootstrap import BootstrapCI, bootstrap_sharpe_ci
from .brinson import BrinsonResult, brinson_attribution
from .dsr import deflated_sharpe_ratio, sharpe_ratio
from .n_eff import NEffResult, n_eff_from_matrix
from .overfit_gate import GateVerdict, run_overfit_gate
from .pbo import cscv_pbo

__all__ = [
    "BootstrapCI",
    "BrinsonResult",
    "GateVerdict",
    "NEffResult",
    "bootstrap_sharpe_ci",
    "brinson_attribution",
    "cscv_pbo",
    "deflated_sharpe_ratio",
    "n_eff_from_matrix",
    "run_overfit_gate",
    "sharpe_ratio",
]
