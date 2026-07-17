"""Value-at-Risk (VaR) and Expected Shortfall (ES) — historical + parametric-Gaussian.

数学先行: derivations are worked out before implementation, then checked against an INDEPENDENT
oracle on fixtures through the canonical spine ConsistencyCheck (see ``spine_binding.py``) and
cross-vendor floor-reviewed by codex/GPT-5.6-sol as the authorized math decider. "Checked on
fixtures against an oracle" is NOT "proven for all inputs" — the spine gate reports label
strength from declared evidence; it does not itself prove any mathematical proposition.

Sign convention: a per-period return ``r``; the LOSS is ``L = -r``. VaR/ES are reported in
LOSS UNITS at confidence ``c`` (0<c<1), tail probability ``alpha = 1 - c``. They may be
NEGATIVE (e.g. an all-positive return series) — a risk measure is not clamped to zero, so
translation equivariance is preserved (VaR(r + k) = VaR(r) - k).

- Historical VaR:  ``VaR_c = -F_n^{-1}(alpha)`` with the empirical inverse CDF (inverted_cdf).
- Historical ES:   ``ES_c = -(1/alpha) * integral_0^alpha F_n^{-1}(u) du``, computed via
  tie-aware interval-overlap weights over the order statistics. VaR and ES are derived from
  ONE shared tail decomposition (``_historical_tail``). ES is written in the STRUCTURALLY
  coherent form ``ES = VaR + dot(w, L_tail - VaR)/alpha`` where every tail loss ``L >= VaR``,
  so the added term is a sum of non-negative products and ``ES >= VaR`` holds at the float
  level with no empirical tolerance (codex R2/R3: the raw ``-dot(w,srt)/alpha`` could dip below
  VaR by ~1 ULP because ``sum(w) == alpha`` and the dot product both round). A residual
  ``ES < VaR`` is then impossible for finite output and fails closed if it ever occurs.
- Parametric-Gaussian (r ~ N(mu, sigma^2)), h-day horizon (i.i.d. scaling: drift ~ h,
  vol ~ sqrt(h)):  ``VaR = -h*mu + sqrt(h)*sigma*Phi^{-1}(c)`` ;
  ``ES = -h*mu + sqrt(h)*sigma*phi(Phi^{-1}(alpha))/alpha``.  (A generic ``sqrt(h) * measure``
  is WRONG for mu != 0 — it mis-scales the drift; codex.)

Invariant (a necessary property the spine ConsistencyCheck asserts on adversarial fixtures):
ES_c >= VaR_c for the same c and horizon. scipy.stats.norm + numpy only — numpy is a declared
dependency.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import numpy as np
from scipy.stats import norm

# Historical quantile method: "inverted_cdf" = the empirical generalized inverse CDF,
# consistent with the ES interval integral below. NOT numpy's default "linear".
_QUANTILE_METHOD = "inverted_cdf"


def _exact_alpha(confidence: float) -> Fraction:
    """The tail probability ``1 - c`` as an EXACT unbounded rational (codex R6).

    ``Decimal(str(c))`` is the float's canonical shortest-decimal serialization (``0.95``, not
    ``0.9500000000000000111...``) and is exact regardless of the Decimal arithmetic context
    (string CONSTRUCTION never rounds). ``Fraction`` of that is an unbounded rational, so all
    downstream tail-mass arithmetic is exact for ANY ``n`` and immune to the Decimal context
    precision that made ``Decimal(n)*Decimal(alpha)`` round for large ``n`` (codex R6/R7).
    """

    return Fraction(1) - Fraction(Decimal(str(confidence)))


def _exact_tail_split(n: int, confidence: float) -> tuple[int, Fraction, int]:
    """Return ``(floor_m, frac, rank)`` for the exact tail mass ``m = n*(1-c)`` (all exact rationals).

    ``rank = ceil(m)`` is the 1-indexed count of order statistics in the ``(0, alpha]`` tail. No
    numpy array is allocated, so this is testable at astronomically large ``n`` (codex R6).
    """

    m = n * _exact_alpha(confidence)  # exact Fraction; n an int → exact
    floor_m = m.numerator // m.denominator  # exact floor for m >= 0
    frac = m - floor_m
    rank = floor_m if frac == 0 else floor_m + 1  # ceil(m)
    rank = max(1, min(rank, n))
    return floor_m, frac, rank


def _clean_returns(returns) -> np.ndarray:
    """Coerce to a 1-D float array and FAIL-CLOSED on bad input (correctness red-line).

    Non-finite (NaN/±inf) values, an empty series, or a non-1-D shape are rejected — a
    risk measure over silently-dropped NaNs would understate risk.
    """

    arr = np.asarray(returns, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"returns must be 1-D, got shape {arr.shape}")
    if arr.size == 0:
        raise ValueError("returns is empty — cannot compute a risk measure")
    if not np.all(np.isfinite(arr)):
        raise ValueError("returns contains non-finite values (NaN/inf) — fail-closed")
    return arr


def _check_confidence(confidence: float) -> float:
    c = float(confidence)
    if not (0.0 < c < 1.0):
        raise ValueError(f"confidence must be in (0, 1), got {c}")
    return c


def _check_horizon(horizon: int) -> int:
    if isinstance(horizon, bool) or not isinstance(horizon, (int, np.integer)):
        raise ValueError(f"horizon must be an integer, got {horizon!r} (no silent truncation)")
    h = int(horizon)
    if h < 1:
        raise ValueError(f"horizon must be >= 1, got {h}")
    return h


def _finite(value: float, what: str) -> float:
    if not np.isfinite(value):
        raise ValueError(f"{what} is non-finite ({value}) — fail-closed (overflow / degenerate input)")
    return float(value)


def _historical_tail(srt: np.ndarray, confidence: float) -> tuple[np.ndarray, int, float]:
    """Shared EXACT tail decomposition for historical VaR AND ES (single source → coherent).

    ``srt`` is the ascending-sorted return series. Returns ``(weights, var_index, alpha)``:
    - ``weights[i]`` = exact overlap of order statistic i's CDF interval ``((i-1)/n, i/n]`` with
      ``(0, alpha]``: ``1/n`` for ``i < floor(m)``, ``frac(m)/n`` for ``i == floor(m)``, else 0
      (``m = n*alpha`` the exact decimal tail mass). ``sum(weights) == alpha``.
    - ``var_index`` = ``ceil(m) - 1`` (0-indexed boundary order statistic ``F_n^{-1}(alpha)``).
    - ``alpha`` = the exact tail probability as float, for the ES ``1/alpha`` normalization.

    VaR rank and ES weights come from the SAME exact ``m`` — no float ``n*alpha``, no ULP snap,
    so there is no boundary off-by-one (codex R5) and coherence is decided by one object.
    """

    n = srt.size
    floor_m, frac, rank = _exact_tail_split(n, confidence)
    w = np.zeros(n, dtype=float)
    full = min(floor_m, n)
    w[:full] = 1.0 / n
    if frac != 0 and floor_m < n:
        w[floor_m] = float(frac / n)  # Fraction division THEN one rounding (codex R7: float(frac)/n double-rounds)
    return w, rank - 1, float(_exact_alpha(confidence))


def historical_var(returns, confidence: float) -> float:
    """Historical VaR = ``-F_n^{-1}(alpha)`` (empirical inverse CDF), from the exact tail."""

    arr = _clean_returns(returns)
    c = _check_confidence(confidence)
    srt = np.sort(arr)
    _w, j, _alpha = _historical_tail(srt, c)
    return _finite(-float(srt[j]), "historical VaR")


def historical_es(returns, confidence: float) -> float:
    """Historical ES = ``-(1/alpha) * integral_0^alpha F_n^{-1}(u) du`` via interval weights.

    Written in the STRUCTURALLY coherent form ``ES = VaR + dot(w_tail, L_tail - VaR)/alpha``
    (codex R3): every tail loss ``L_tail[i] = -srt[i] >= VaR`` because ``srt[i] <= srt[var_index]``,
    so ``L_tail - VaR >= 0`` and the added term is a sum of non-negative products divided by
    ``alpha > 0`` — hence ``ES >= VaR`` at the float level with NO empirical tolerance (adding a
    non-negative float to VaR never rounds below VaR). This is algebraically identical to
    ``-(1/alpha)*dot(w, srt)`` but is coherence-preserving where the raw quotient is not.
    """

    arr = _clean_returns(returns)
    c = _check_confidence(confidence)
    srt = np.sort(arr)
    w, j, alpha = _historical_tail(srt, c)  # alpha = exact tail probability
    var = -float(srt[j])
    tail_w = w[: j + 1]
    tail_excess_losses = (-srt[: j + 1]) - var  # L_tail - VaR, each >= 0 (srt[:j+1] <= srt[j])
    es = _finite(var + float(np.dot(tail_w, tail_excess_losses)) / alpha, "historical ES")
    if es < var:  # unreachable for finite output (excess term >= 0) — fail-closed defense
        raise ValueError(
            f"historical ES {es} < VaR {var} — coherence invariant violated (logic error) → fail-closed"
        )
    return es


def parametric_gaussian_var(returns, confidence: float, *, horizon: int = 1) -> float:
    """Parametric VaR, r ~ N(mu, sigma^2), h-day: ``-h*mu + sqrt(h)*sigma*Phi^{-1}(c)``.

    SAMPLE mean and SAMPLE std (ddof=1, unbiased variance). i.i.d. scaling: drift ~ h,
    volatility ~ sqrt(h) — a generic sqrt(h)*measure would mis-scale the drift.
    """

    arr = _clean_returns(returns)
    c = _check_confidence(confidence)
    h = _check_horizon(horizon)
    if arr.size < 2:
        raise ValueError("parametric estimators need >= 2 observations (sample std)")
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=1))
    return _finite(-h * mu + np.sqrt(h) * sigma * norm.ppf(c), "parametric VaR")


def parametric_gaussian_es(returns, confidence: float, *, horizon: int = 1) -> float:
    """Parametric ES, r ~ N(mu, sigma^2), h-day: ``-h*mu + sqrt(h)*sigma*phi(Phi^{-1}(alpha))/alpha``."""

    arr = _clean_returns(returns)
    c = _check_confidence(confidence)
    h = _check_horizon(horizon)
    if arr.size < 2:
        raise ValueError("parametric estimators need >= 2 observations (sample std)")
    alpha = 1.0 - c
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=1))
    z_alpha = norm.ppf(alpha)
    return _finite(-h * mu + np.sqrt(h) * sigma * norm.pdf(z_alpha) / alpha, "parametric ES")
