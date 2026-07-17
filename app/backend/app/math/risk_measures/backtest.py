"""Kupiec Proportion-of-Failures (POF) VaR backtest.

数学先行: given N one-step forecasts with x exceedances (a loss beyond the reported
VaR), and an expected failure rate ``p = alpha = 1 - c`` under a correct model, the POF
likelihood-ratio statistic is

    LR_POF = -2 * [ (N-x)*ln(1-p) + x*ln(p) - ( (N-x)*ln(1-pihat) + x*ln(pihat) ) ]

with ``pihat = x/N`` the observed failure rate. Under H0 (true rate = p),
``LR_POF ~ chi^2(1)``; reject unconditional coverage when ``LR_POF > chi2_{1,c}``.

Edge cases (checked against an independent scipy power_divergence G-test oracle in the spine
binding, not self-certified): x=0 → the ``x*ln(pihat)`` term is 0 by the limit (0*ln(0)=0),
so only ``(N-x)*ln(1-pihat)=N*ln(1)=0`` survives on the alt side; x=N symmetric.
Well-calibrated (pihat==p) → LR=0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import chi2


def _bd0(x: float, mean: float, x_minus_mean: float) -> float:
    """Loader (2000) binomial/Poisson deviance term ``bd0(x, m) = x*ln(x/m) - (x - m)`` (>= 0).

    Computing the Kupiec LR as ``2*(bd0(x, n*p) + bd0(n-x, n*(1-p)))`` sums two NON-NEGATIVE
    deviance components, so — unlike ``x*ln(pihat/p) + (n-x)*ln((1-pihat)/(1-p))`` — there is no
    catastrophic cancellation of two opposite-sign O(N) terms near the null at large N (codex R10:
    the sum-of-log-ratios form false-accepted and false-rejected at n~1e35/1e24).

    ``x_minus_mean = x - mean`` is passed in computed EXACTLY (from the integer numerator) so the
    stable series is accurate at huge scale where ``float(x) - mean`` would cancel. Near ``x≈mean``
    a convergent series is used; far away, a log difference (``ln x - ln m``) avoids ratio overflow.

    Overflow-safe at the float upper edge (codex R11): ``v`` is computed with scaling so ``x + mean``
    is never formed directly (it can exceed float max ~1.8e308), and ``ej`` multiplies ``2*v`` (< 0.2)
    by ``x`` LAST, so no intermediate ``2*x`` overflows. The series loop is bounded and fails closed
    on any non-finite intermediate rather than spinning forever on a ``nan`` (which never == itself).
    Ref: C. Loader, "Fast and Accurate Computation of Binomial Probabilities" (2000).
    """

    if x == 0.0:
        return mean  # limit: 0*ln(0/m) - (0 - m) = m  (m >= 0)
    if not math.isfinite(x) or not math.isfinite(mean) or mean <= 0.0:
        raise ValueError(f"bd0 needs finite x and mean > 0, got x={x} mean={mean}")
    scale = x if x >= mean else mean  # = max(x, mean); avoids forming x+mean directly
    v = (x_minus_mean / scale) / (x / scale + mean / scale)  # = (x-mean)/(x+mean), overflow-safe
    if abs(v) < 0.1:
        # Loader's convergent series: bd0 = (x-m)*v + 2x*(v^3/3 + v^5/5 + ...), v = (x-m)/(x+m).
        s = x_minus_mean * v
        ej = (2.0 * v) * x  # 2*v < 0.2 first, then *x — no intermediate 2*x overflow
        v2 = v * v
        for j in range(1, 100_000):  # |v|<0.1 ⇒ geometric convergence in ~dozens; the cap is a backstop
            ej *= v2
            s1 = s + ej / (2 * j + 1)
            if not math.isfinite(s1):
                raise ValueError("bd0 series produced a non-finite term — fail-closed")
            if s1 == s:  # converged (further terms below ULP)
                return s1 if s1 >= 0.0 else 0.0  # bd0 >= 0 by construction; clamp a ULP-level negative
            s = s1
        raise ValueError("bd0 series did not converge within the iteration cap — fail-closed")
    r = x * (math.log(x) - math.log(mean)) - x_minus_mean  # far from mean: log difference
    if not math.isfinite(r):
        raise ValueError("bd0 (far-from-mean branch) is non-finite — fail-closed")
    return r if r >= 0.0 else 0.0


def _finite(value: float, what: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{what} is non-finite ({value}) — fail-closed")
    return value


def _to_float(value: int, what: str) -> float:
    """``float(value)`` for a possibly-huge integer count, failing closed on overflow rather than
    leaking a raw ``OverflowError: int too large to convert to float`` (codex R11)."""

    try:
        return float(value)
    except OverflowError as exc:
        raise ValueError(f"{what} exceeds float range (n astronomically large) — fail-closed") from exc


def _int_ratio(num: int, den: int, what: str) -> float:
    """``num/den`` as a float, failing closed on overflow (astronomically large n) rather than
    letting Python raise a raw ``OverflowError: integer division result too large`` (codex R10)."""

    try:
        v = num / den
    except OverflowError as exc:
        raise ValueError(f"{what} overflows float (n astronomically large) — fail-closed") from exc
    return _finite(v, what)


def count_exceedances(returns, var_forecast, *, convention: str = "strict") -> int:
    """Count VaR exceedances = periods where the realized LOSS breached the reported VaR.

    A loss ``L = -r`` breaches VaR when ``L > VaR`` (``r < -VaR``). ``var_forecast`` may be
    a scalar (constant VaR) or a per-period array aligned to ``returns`` (rolling
    forecast). ``convention``: "strict" (``r < -VaR``) or "inclusive" (``r <= -VaR``);
    the boundary ``r == -VaR`` is measure-zero for continuous returns but pinned here so
    the exceedance count is never silently convention-dependent (cross-vendor duet — codex).
    """

    r = np.asarray(returns, dtype=float)
    v = np.asarray(var_forecast, dtype=float)
    if r.ndim != 1 or r.size == 0:
        raise ValueError("returns must be a non-empty 1-D array")
    if not np.all(np.isfinite(r)):
        raise ValueError("returns contains non-finite values — fail-closed")
    if v.ndim == 0:
        v = np.full(r.shape, float(v))
    elif v.shape != r.shape:
        raise ValueError(f"var_forecast shape {v.shape} must be scalar or match returns {r.shape}")
    if not np.all(np.isfinite(v)):
        raise ValueError("var_forecast contains non-finite values — fail-closed")
    if convention == "strict":
        return int(np.sum(r < -v))
    if convention == "inclusive":
        return int(np.sum(r <= -v))
    raise ValueError(f"convention must be 'strict' or 'inclusive', got {convention!r}")


@dataclass(frozen=True)
class KupiecResult:
    """Outcome of a Kupiec POF test. ``reject`` = unconditional coverage rejected."""

    n_obs: int
    n_exceedances: int
    expected_rate: float       # p = 1 - c
    observed_rate: float       # pihat = x / N
    lr_stat: float
    p_value: float
    reject: bool               # LR_stat > chi2_{1, test_confidence}


def kupiec_pof_test(
    n_obs: int,
    n_exceedances: int,
    var_confidence: float,
    *,
    test_confidence: float = 0.95,
) -> KupiecResult:
    """Run the Kupiec POF (unconditional-coverage) test. FAIL-CLOSED on nonsensical counts.

    ``var_confidence`` is the c of the VaR being tested (so expected failure rate
    ``p = 1 - c``). ``test_confidence`` is the CONFIDENCE LEVEL of the LR test (reject when
    ``LR > chi2.ppf(test_confidence, 1)`` ⟺ ``p_value < 1 - test_confidence``).

    Applicability: the ``chi2(1)`` null is ASYMPTOTIC — it is unreliable for very small N or
    very few expected exceedances (``N*p`` small); an exact-binomial coverage test is the
    registered small-sample follow-on. Counts must be exact non-negative integers (no silent
    truncation — cross-vendor floor finding, codex).
    """

    if isinstance(n_obs, bool) or not isinstance(n_obs, (int, np.integer)):
        raise ValueError(f"n_obs must be an integer, got {n_obs!r} (no silent truncation)")
    if isinstance(n_exceedances, bool) or not isinstance(n_exceedances, (int, np.integer)):
        raise ValueError(f"n_exceedances must be an integer, got {n_exceedances!r}")
    n = int(n_obs)
    x = int(n_exceedances)
    if n <= 0:
        raise ValueError("n_obs must be positive")
    if not (0 <= x <= n):
        raise ValueError(f"n_exceedances must be in [0, n_obs], got x={x} n={n}")
    c = float(var_confidence)
    if not (0.0 < c < 1.0):
        raise ValueError(f"var_confidence must be in (0, 1), got {c}")
    tc = float(test_confidence)
    if not (0.0 < tc < 1.0):
        raise ValueError(f"test_confidence must be in (0, 1), got {tc}")

    p = 1.0 - c
    pihat = x / n
    # Exact rational for the confidence: c = pc/qc, so p = 1-c = (qc-pc)/qc and 1-p = c = pc/qc.
    pc, qc = c.as_integer_ratio()
    dev_num = x * qc - n * (qc - pc)  # exact int = (x - n*p) * qc

    # Exact INTEGER null (x/n == 1-c ⇔ dev_num == 0): the observed and expected rates are equal, so
    # LR = 0 exactly and the model is not rejected at any test confidence (crit > 0). Short-circuit —
    # this is unambiguous and avoids the ambiguity gate mis-flagging it at extreme tc (codex R14).
    if dev_num == 0:
        return KupiecResult(
            n_obs=n, n_exceedances=x, expected_rate=p, observed_rate=pihat,
            lr_stat=0.0, p_value=1.0, reject=False,
        )

    # LR = 2*[bd0(x, n*p) + bd0(n-x, n*(1-p))]: a sum of two NON-NEGATIVE Loader deviance components
    # (codex R10). Each mean and each (count - mean) is derived from EXACT integer numerators, so the
    # near-null series is accurate and there is NO opposite-sign O(N) cancellation (which false-
    # accepted/rejected at n~1e35). LR >= 0 by construction — no clamp. Fail closed if a mean or the
    # LR overflows (astronomically large n) instead of returning a wrong finite value.
    mean_fail = _int_ratio(n * (qc - pc), qc, "Kupiec n*p")        # n*p = n*(1-c)
    mean_ok = _int_ratio(n * pc, qc, "Kupiec n*(1-p)")            # n*(1-p) = n*c
    x_minus_mean_fail = _int_ratio(dev_num, qc, "Kupiec x - n*p")        # exact-rounded x - n*p
    nx_minus_mean_ok = _int_ratio(-dev_num, qc, "Kupiec (n-x) - n*(1-p)")  # exact-rounded (n-x) - n*(1-p)
    lr = 2.0 * (
        _bd0(_to_float(x, "x"), mean_fail, x_minus_mean_fail)
        + _bd0(_to_float(n - x, "n-x"), mean_ok, nx_minus_mean_ok)
    )
    lr = _finite(lr, "Kupiec LR")
    if lr < 0.0:
        # each bd0 is clamped >= 0, so LR >= 0 by construction; a negative here is an invariant
        # violation (a genuine logic error), NOT something to silently clamp (codex R11).
        raise ValueError(f"Kupiec LR {lr} < 0 — deviance non-negativity invariant violated → fail-closed")
    p_value = float(chi2.sf(lr, df=1))
    crit = float(chi2.ppf(tc, df=1))
    reject_by_lr = lr > crit
    # p-space decision in the numerically-STABLE tail: for small tc compare cdf(lr) to tc (tc is the
    # well-represented threshold); for large tc compare sf(lr) to 1-tc. This avoids `1-tc` rounding to
    # exactly 1.0 at tiny tc, which used to mis-flag an exact null as ambiguous (codex R14).
    if tc <= 0.5:
        reject_by_p = float(chi2.cdf(lr, df=1)) > tc
    else:
        reject_by_p = p_value < (1.0 - tc)
    # Fail closed in the numerical-ambiguity zone (codex R12/R13/R14). ``env`` (inlined so it is part of
    # the fingerprinted function source) is the validated relative error envelope: the Loader deviance
    # LR has a fuzz-validated worst-case relative error ~3e-13 (700/160-digit, thousands of samples) and
    # chi2.ppf/sf add a few ULP, so 1e-11 sits comfortably above the true computation error and ~1e10x
    # below the smallest non-borderline LR↔crit gap (~0.19). The window is scaled by the comparison
    # MAGNITUDE (max(|lr|,|crit|)), NOT a fixed 1.0, so a tiny crit (extreme tc) does not fail-close a
    # clearly-decidable result. The two equivalent float forms can AGREE yet both be wrong (codex R13),
    # so this explicit neighborhood test — plus a predicate-mismatch check — is required.
    env = 1e-11
    scale = max(abs(lr), abs(crit))
    # Fail closed across the ENTIRE subnormal comparison domain (scale < smallest NORMAL double, 2^-1022).
    # The exact integer null is short-circuited above, so a subnormal scale here means the decision
    # magnitude has underflowed into the range where floats lose relative precision AND `env*scale`
    # itself underflows to 0, collapsing the relative window — the verdict is not reliably decidable
    # (codex R15: LR & crit both round to 0; codex R16: LR rounds to 0 while crit is a nonzero subnormal
    # so scale != 0 yet true LR > true crit — a silent false accept). Normal-range floats are unaffected.
    _SMALLEST_NORMAL = float.fromhex("0x1.0p-1022")
    lr_ambiguous = scale < _SMALLEST_NORMAL or abs(lr - crit) <= env * scale
    if lr_ambiguous or (reject_by_lr != reject_by_p):
        raise ValueError(
            f"Kupiec verdict ambiguous: LR={lr!r} is within the double-precision error envelope of "
            f"the critical value {crit!r} (|LR-crit|={abs(lr - crit):g}) — borderline result not "
            "reliably decidable in float without higher precision → fail-closed"
        )
    return KupiecResult(
        n_obs=n,
        n_exceedances=x,
        expected_rate=p,
        observed_rate=pihat,
        lr_stat=float(lr),
        p_value=p_value,
        reject=reject_by_p,  # self-consistent with p_value < (1-tc)
    )


def kupiec_from_returns(
    returns,
    var_forecast,
    var_confidence: float,
    *,
    convention: str = "strict",
    test_confidence: float = 0.95,
) -> KupiecResult:
    """End-to-end Kupiec POF: count exceedances of ``var_forecast`` in ``returns``, test."""

    import numpy as _np

    n = int(_np.asarray(returns, dtype=float).size)
    x = count_exceedances(returns, var_forecast, convention=convention)
    return kupiec_pof_test(n, x, var_confidence, test_confidence=test_confidence)
