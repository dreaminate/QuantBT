"""VaR / ES market-risk measures (financial-math kernel P0-A #1).

Computes downside risk measures from a RETURN SERIES — orthogonal to:
- ``app/risk/checks.py`` (pre-trade operational limits / kill-switch — not a measure), and
- ``app/eval/risk_summary.py`` (evidence flags on run-summary metrics — not a computation).

Math is derived before implementation (数学先行), checked against an INDEPENDENT oracle on
fixtures, and cross-vendor floor-reviewed by codex/GPT-5.6-sol (the authorized math decider).
Every measure is pinned to analytical/coherence goldens (``tests/test_math_risk_measures.py``).

命门 (consistency gate): each measure is bound to the CANONICAL spine (``spine_binding.py`` →
``app/lineage/spine*``) — VaR/ES/Kupiec carry a ``MathematicalArtifact`` + a real source-chain
fingerprint + an independent-oracle ``ConsistencyCheck``, and ``evaluate_promotion`` refuses a
strong label if the implementation drifts from the definition or the fingerprint goes stale.
This is NOT a parallel self-certifying gate — it reuses the same machinery as the eval spine.

Sign convention: VaR/ES are in LOSS UNITS at confidence ``c`` (alpha = 1 - c the tail prob);
they may be negative (all-positive returns) — not clamped, preserving translation equivariance.
"""

from .var_es import (
    historical_es,
    historical_var,
    parametric_gaussian_es,
    parametric_gaussian_var,
)
from .backtest import KupiecResult, count_exceedances, kupiec_from_returns, kupiec_pof_test
from .spec import RiskMeasureSpec, compute_measure
from .spine_binding import (
    verify_es_consistency,
    verify_kupiec_consistency,
    verify_var_consistency,
)

__all__ = [
    "historical_var",
    "historical_es",
    "parametric_gaussian_var",
    "parametric_gaussian_es",
    "kupiec_pof_test",
    "kupiec_from_returns",
    "count_exceedances",
    "KupiecResult",
    "RiskMeasureSpec",
    "compute_measure",
    "verify_var_consistency",
    "verify_es_consistency",
    "verify_kupiec_consistency",
]
