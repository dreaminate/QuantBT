"""Oracle + adversarial tests for the VaR/ES market-risk kernel (financial-math P0-A #1).

Every measure is pinned to an ANALYTICAL / hand-computed golden (数学先行 → 黄金测试). An earlier
version of these tests was fake-green (cross-vendor floor finding — codex R1/R2): naive-ES and
broken-Kupiec mutations passed. This version was rebuilt with DISCRIMINATING goldens and each
named mutation was injected into the SOURCE and re-run (RED-then-revert) to prove it reddens.

Empirically RED-then-revert verified (mutation → test that goes RED):
- historical ES → naive ``mean(r[r<=q])`` tail-mean → ``test_historical_es_fractional_boundary_golden``
  (Acerbi-Tasche 0.0914285714 vs naive 0.085 on a fractional-boundary sample).
- historical ES → raw ``-dot(w,srt)/alpha`` (drop the structural VaR+excess form) → dips below VaR
  on huge equal magnitudes → ``test_historical_es_structural_coherence_degenerate`` (both signs).
- ``max(0,·)`` clamp on any measure → ``test_all_positive_returns_measures_may_be_negative_not_clamped``
  (all four functions, negative loss preserved) + the negative-territory case in the degenerate test.
- shared tail ``np.unique``-dedups ties → ``test_historical_es_tie_multiplicity_golden`` (0.10 vs 0.0733)
  and the spine ES numerical consistency check.
- parametric multi-day ES → ``sqrt(h)*(1-day ES)`` (mis-scales drift, mu!=0) → ``test_horizon_es_drift_aware_golden``.
- parametric VaR/ES → drop a sign → ``test_parametric_gaussian_closed_form_golden``.
- Kupiec p_value → constant for x!=50 → ``test_kupiec_p_value_exact_for_all_x_not_just_x50``.
- Kupiec ``reject`` → hardcoded test_confidence=0.95 → ``test_kupiec_non_default_test_confidence_golden``.
- Kupiec LR / boundary → constant → ``test_kupiec_exact_golden``.
- remove ``count_exceedances`` NaN/inf guard → ``test_count_exceedances_rejects_non_finite``.

Note (codex R3): an earlier version claimed two mutations were "equivalent / no input distinguishes";
that was wrong — the ``max(0,·)`` clamp IS reachable in the negative-loss regime (all-positive returns
and the +1e12 degenerate case), and both are now pinned above. ES is written in a structurally
coherent form (VaR + non-negative excess), so no empirical coherence tolerance is used.
命门 (consistency gate) is CONNECTED to the canonical spine — see ``test_math_risk_measures_spine.py``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import chi2, norm

from app.math.risk_measures import (
    RiskMeasureSpec,
    compute_measure,
    count_exceedances,
    historical_es,
    historical_var,
    kupiec_from_returns,
    kupiec_pof_test,
    parametric_gaussian_es,
    parametric_gaussian_var,
)

# --- Parametric-Gaussian closed-form golden --------------------------------


def test_parametric_gaussian_closed_form_golden():
    # data {-1,3}: sample mean=1, sample std(ddof=1)=sqrt(8). Exact closed form.
    data = np.array([-1.0, 3.0])
    mu, sig = data.mean(), data.std(ddof=1)
    for c in (0.95, 0.99):
        exp_var = -mu + sig * norm.ppf(c)
        exp_es = -mu + sig * norm.pdf(norm.ppf(1 - c)) / (1 - c)
        assert parametric_gaussian_var(data, c) == pytest.approx(exp_var, abs=1e-12)
        assert parametric_gaussian_es(data, c) == pytest.approx(exp_es, abs=1e-12)
        assert parametric_gaussian_es(data, c) > parametric_gaussian_var(data, c)


# --- Historical golden (hand-computed Acerbi-Tasche integral) ---------------


def test_historical_var_es_golden():
    r = np.array([-0.10, -0.08, -0.05, -0.02, 0.0, 0.01, 0.03, 0.05, 0.07, 0.10])  # N=10
    # c=0.80, alpha=0.20, integer boundary: VaR=-r_(2)=0.08, ES=-(r_(1)+r_(2))/10 /0.20=0.09
    assert historical_var(r, 0.80) == pytest.approx(0.08, abs=1e-12)
    assert historical_es(r, 0.80) == pytest.approx(0.09, abs=1e-12)
    # inverted_cdf (order statistic), NOT numpy 'linear' interpolation
    assert historical_var(r, 0.80) != pytest.approx(-np.quantile(r, 0.20, method="linear"))


def test_historical_es_fractional_boundary_golden():
    """THE discriminating test: on a FRACTIONAL alpha*N, Acerbi-Tasche ES differs from a
    naive tail-mean. N=7, c=0.80 (alpha*N=1.4): AT ES = 0.0914285714..., naive = 0.085."""
    r = np.array([-0.10, -0.07, -0.05, -0.02, 0.01, 0.03, 0.06])  # N=7
    assert historical_var(r, 0.80) == pytest.approx(0.07, abs=1e-12)
    assert historical_es(r, 0.80) == pytest.approx(0.0914285714285714, abs=1e-12)
    # the naive tail-mean would be 0.085 — the golden above rejects it.
    naive = -r[r <= np.quantile(r, 0.20, method="inverted_cdf")].mean()
    assert naive == pytest.approx(0.085) and historical_es(r, 0.80) != pytest.approx(naive)


def test_historical_boundary_alpha_n_lt_one_es_equals_var():
    r = np.random.default_rng(1).normal(0, 1, 50)  # c=0.99, alpha*N=0.5 < 1
    assert historical_es(r, 0.99) == pytest.approx(historical_var(r, 0.99), abs=1e-12)
    assert historical_var(r, 0.99) == pytest.approx(-float(np.min(r)), abs=1e-12)  # worst loss


@pytest.mark.parametrize(
    "fn", [historical_var, historical_es, parametric_gaussian_var, parametric_gaussian_es]
)
def test_all_positive_returns_measures_may_be_negative_not_clamped(fn):
    """Sign convention: risk measure is in loss units and NOT clamped — an all-positive series
    has a NEGATIVE VaR/ES (translation equivariance preserved). ALL FOUR functions: a max(0,·)
    clamp on any of them is a fake-green unless every one is pinned (codex R3 P1-3)."""
    r = np.array([0.01, 0.02, 0.03, 0.05, 0.04])  # all positive, sample std > 0 for parametric
    assert fn(r, 0.80) < 0, f"{fn.__name__} clamped a negative loss measure to >= 0"


# --- Coherence + monotonicity invariants -----------------------------------


def test_es_ge_var_coherence_small_samples_sweep():
    for seed in range(150):
        r = np.random.default_rng(seed).normal(0, 1, 100)
        for c in (0.90, 0.95, 0.975, 0.99):
            assert historical_es(r, c) >= historical_var(r, c) - 1e-12, f"seed={seed} c={c}"
            assert parametric_gaussian_es(r, c) >= parametric_gaussian_var(r, c) - 1e-12


def test_measures_monotone_in_confidence():
    r = np.random.default_rng(7).normal(0, 1, 5000)
    for lo, hi in ((0.90, 0.95), (0.95, 0.99)):
        assert historical_var(r, hi) >= historical_var(r, lo) - 1e-9
        assert historical_es(r, hi) >= historical_es(r, lo) - 1e-9
        assert parametric_gaussian_var(r, hi) >= parametric_gaussian_var(r, lo) - 1e-9


# --- Horizon (drift-aware) golden ------------------------------------------


def test_horizon_drift_aware_golden():
    """Multi-day parametric scales drift ~h and vol ~sqrt(h): -h*mu + sqrt(h)*sigma*z_c.
    A naive sqrt(h)*(1-day measure) mis-scales the drift and is REJECTED here."""
    r = np.array([-1.0, 3.0])  # mu=1, sigma=sqrt(8)
    mu, sig = r.mean(), r.std(ddof=1)
    spec = RiskMeasureSpec("VaR", "parametric_gaussian", 0.99, holding_period_days=10)
    correct = -10 * mu + math.sqrt(10) * sig * norm.ppf(0.99)
    wrong = math.sqrt(10) * (-mu + sig * norm.ppf(0.99))
    assert compute_measure(spec, r) == pytest.approx(correct, abs=1e-9)
    assert compute_measure(spec, r) != pytest.approx(wrong)
    assert parametric_gaussian_var(r, 0.99, horizon=10) == pytest.approx(correct, abs=1e-9)


def test_historical_multi_day_rejected_at_construction():
    with pytest.raises(ValueError, match="historical"):
        RiskMeasureSpec("VaR", "historical", 0.99, holding_period_days=5)


# --- Kupiec POF: EXACT golden (not just finite) ----------------------------


def test_kupiec_exact_golden():
    # x=50, N=500, p=0.05: hand-computed LR = 20.6542189127...
    r50 = kupiec_pof_test(500, 50, 0.95)
    assert r50.lr_stat == pytest.approx(20.6542189127, abs=1e-8)
    assert r50.reject and r50.p_value == pytest.approx(5.50158e-06, rel=1e-3)
    # x=0, N=500: LR = -2*N*ln(1-p) = 51.2932943876
    r0 = kupiec_pof_test(500, 0, 0.95)
    assert r0.lr_stat == pytest.approx(51.2932943876, abs=1e-8) and r0.reject
    # well-calibrated x=25 (pihat=p): LR=0, not rejected
    r25 = kupiec_pof_test(500, 25, 0.95)
    assert r25.lr_stat == pytest.approx(0.0, abs=1e-9) and not r25.reject
    # x=N boundary is finite: LR = -2*N*ln(p)
    rN = kupiec_pof_test(500, 500, 0.95)
    assert rN.lr_stat == pytest.approx(-2 * 500 * math.log(0.05), abs=1e-8)


def test_kupiec_extreme_confidence_no_domain_error():
    """Kupiec must not throw a math domain error inside its declared domain 0<c<1 (codex R8): the
    stable log form (log(c)/log1p(-c) and integer-count ratios) keeps p=1-c and pihat=x/n from
    rounding to 0/1. Exact hand-verified LRs pin the tail — the power_divergence oracle underflows
    at c→0, so these are golden-pinned (not oracle-cross-checked): honest boundary."""
    assert kupiec_pof_test(100, 50, 1e-20).lr_stat == pytest.approx(4466.540749876102, rel=1e-12)
    r = kupiec_pof_test(2**54, 2**54 - 1, 0.95)  # pihat=(n-1)/n rounds to 1.0 without the fix
    assert math.isfinite(r.lr_stat)
    assert r.lr_stat == pytest.approx(1.0793263000703608e17, abs=64.0)  # tight: ULP≈16 (codex R9/R10)
    # the deviance (bd0) rewrite leaves normal-confidence LRs UNCHANGED (regression guard)
    assert kupiec_pof_test(500, 50, 0.95).lr_stat == pytest.approx(20.6542189127, abs=1e-8)
    assert kupiec_pof_test(500, 0, 0.95).lr_stat == pytest.approx(51.2932943876, abs=1e-8)


def test_kupiec_large_n_near_null_deviance_no_cancellation():
    """The LR is the sum of two NON-NEGATIVE Loader deviance terms bd0(x,np)+bd0(n-x,n(1-p)), so
    near-null at huge N does NOT catastrophically cancel (codex R10: the sum-of-log-ratios form
    false-accepted and false-rejected at n~1e35/1e24, and hit OverflowError/domain error)."""
    # false-accept case: true LR ≈ 4 > crit(3.8415) → must REJECT (the cancelling form clamped to 0)
    r = kupiec_pof_test(10**35, 5000000000000004578732586021528437, 0.95)
    assert r.lr_stat == pytest.approx(4.0, abs=1e-9) and r.reject is True
    # false-reject case: true LR 3.84145882060 < crit → must NOT reject
    r = kupiec_pof_test(10**24, 50000000000427208655996, 0.95)
    assert r.lr_stat == pytest.approx(3.8414588206036, abs=1e-9) and r.reject is False
    # legal-domain edges that previously raised OverflowError / math domain error:
    assert kupiec_pof_test(1, 0, math.nextafter(0.0, 1.0)).lr_stat == pytest.approx(
        1488.8801438427624, rel=1e-12
    )  # c = smallest positive float
    assert math.isfinite(kupiec_pof_test(10**18, 1, 0.95).lr_stat)  # x=1, huge N


def test_kupiec_float_upper_edge_no_hang_finite_or_failclosed():
    """At the float upper edge (n ~ 1e291-1e308) the Loader deviance must not infinite-loop, must
    return the FINITE true LR, and must fail closed (not leak OverflowError) beyond float range
    (codex R11: x+mean overflowed to inf → 2*x*v = inf*0 = nan → `while True` spun forever)."""
    import signal

    def _timed(fn, secs=10):
        def _handler(signum, frame):
            raise TimeoutError("Kupiec call did not terminate (infinite loop regression)")

        old = signal.signal(signal.SIGALRM, _handler)
        signal.setitimer(signal.ITIMER_REAL, secs)
        try:
            return fn()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)

    # exact null at the float upper edge → LR=0, terminates fast (the SIGALRM catches a hang)
    c = 0.1
    pc, qc = c.as_integer_ratio()
    k = 4 * 10**291
    n, x = qc * k, (qc - pc) * k
    assert x * qc == n * (qc - pc)  # exact null
    assert _timed(lambda: kupiec_pof_test(n, x, c)).lr_stat == 0.0
    # finite true LR at huge counts (was mis-reported as inf); 80-digit reference 5.8857500056...e305
    assert kupiec_pof_test(17 * 10**307, 9 * 10**307, 0.5).lr_stat == pytest.approx(
        5.885750005611753e305, rel=1e-12
    )
    # beyond float range → fail closed with ValueError, not a raw OverflowError
    with pytest.raises(ValueError):
        kupiec_pof_test(3 * 10**308, 2 * 10**308, 0.5)


def test_kupiec_exact_null_no_false_reject_large_n():
    """At an EXACT null (x/n == 1-c exactly) the deviance-form LR must be exactly 0 — no
    false rejection from catastrophic cancellation of two O(N) log-likelihoods at large N
    (codex R9: the subtraction form gave lr=74, reject=True for n=2**54)."""
    c, n, x = 0.95, 2**54, 900719925474100
    pc, qc = c.as_integer_ratio()
    assert x * qc == n * (qc - pc)  # x/n == 1-c exactly (integer identity)
    r = kupiec_pof_test(n, x, c)
    assert r.lr_stat == 0.0 and r.p_value == 1.0 and r.reject is False
    # the near-null LR is the TRUE ~1e-29 (deviance form), not ~3.7e-13 cancellation noise
    r25 = kupiec_pof_test(500, 25, 0.95)
    assert r25.lr_stat < 1e-20 and not r25.reject


def test_kupiec_verdict_self_consistent_and_ambiguous_fails_closed():
    """reject must be self-consistent with p_value < (1-tc); when the two equivalent float forms
    (lr>crit vs p_value<1-tc) disagree because LR is within double-precision resolution of the
    critical value, the verdict fails closed rather than emitting a wrong/contradictory reject
    (codex R12: at n=1e30 the LR was just below the true crit yet `lr>crit` said reject)."""
    # near-critical counterexamples → LR within the double-precision error envelope of crit → fail-closed.
    # (codex R12: the two float predicates DISAGREE; codex R13: they AGREE yet BOTH are wrong — the true
    # LR is 2.2e-15 below the true crit — so an explicit envelope, not just a mismatch check, is needed.)
    with pytest.raises(ValueError, match="ambiguous"):
        kupiec_pof_test(10**30, 500000000000000979981992270027, 0.5, test_confidence=0.95)
    with pytest.raises(ValueError, match="ambiguous"):
        kupiec_pof_test(10**34, 5000000000000000097998199227002665, 0.5, test_confidence=0.95)


def test_kupiec_extreme_test_confidence_still_decidable():
    """The ambiguity window is RELATIVE (scaled by max(|lr|,|crit|)), and an exact integer null
    short-circuits, so clearly-decidable results at extreme test_confidence are NOT spuriously
    flagged ambiguous (codex R14: a fixed absolute 1e-11 window + `1-tc` rounding broke tiny tc)."""
    # exact null (x/n == 1-c) at tiny tc → LR=0, not rejected (crit>0), NOT ambiguous
    r = kupiec_pof_test(100, 50, 0.5, test_confidence=1e-8)
    assert r.lr_stat == 0.0 and r.reject is False and r.p_value == 1.0
    # tc so small that 1-tc rounds to 1.0 — the exact-null short-circuit still returns cleanly
    assert kupiec_pof_test(100, 50, 0.5, test_confidence=1e-20).reject is False
    # LR ≈ 1e-12 is 6000x the tiny critical value → clearly REJECT, must not be flagged ambiguous
    r = kupiec_pof_test(4 * 10**12, 2 * 10**12 + 1, 0.5, test_confidence=1e-8)
    assert r.reject is True and math.isfinite(r.lr_stat)


def test_kupiec_double_underflow_fails_closed():
    """When LR AND crit both underflow to 0.0 (a NON-null decision — the exact null is short-circuited
    — at extreme tc and huge n), the verdict underflowed and must fail closed, not silently accept a
    clear reject (codex R15: true LR=4.9e-332 vs crit=1.6e-340, LR/crit≈3e8, yet both round to 0)."""
    c = math.nextafter(0.5, 1.0)
    pc, qc = c.as_integer_ratio()
    d = qc - pc
    inv = pow(d, -1, qc)                          # d*n ≡ 1 (mod qc) ⇒ dev_num = x*qc - n*d = -1
    n = inv + qc * ((10**300 - inv) // qc)
    x = (n * d - 1) // qc
    assert x * qc - n * d == -1 and 0 <= x <= n   # non-null (dev_num != 0), n ~ 1e300
    with pytest.raises(ValueError, match="ambiguous"):
        kupiec_pof_test(n, x, c, test_confidence=1e-170)
    # third underflow class (codex R16): LR rounds to 0 but crit is a nonzero SUBNORMAL (scale != 0),
    # so scale==0 alone misses it — the whole subnormal comparison domain must fail closed. Here the
    # true LR=9.86e-324 > true crit=6.28e-324 (should REJECT) yet float LR=0, crit=1e-323.
    n2 = inv + qc * ((5 * 10**291 - inv) // qc)
    x2 = (n2 * d - 1) // qc
    assert x2 * qc - n2 * d == -1 and 0 <= x2 <= n2
    with pytest.raises(ValueError, match="ambiguous"):
        kupiec_pof_test(n2, x2, c, test_confidence=2e-162)
    # every non-borderline verdict is self-consistent: reject == (p_value < 1-tc)
    for n, x, c, tc in [
        (500, 50, 0.95, 0.95), (500, 0, 0.95, 0.95), (500, 25, 0.95, 0.95),
        (500, 500, 0.95, 0.95), (500, 29, 0.95, 0.50), (2000, 150, 0.95, 0.95),
        (100, 50, 1e-20, 0.95), (1000, 5, 0.99, 0.95),
    ]:
        r = kupiec_pof_test(n, x, c, test_confidence=tc)
        assert r.reject == (r.p_value < (1.0 - tc)), (n, x, c, tc, r)


def test_kupiec_reject_and_ppf_relationship():
    res = kupiec_pof_test(500, 50, 0.95)
    assert res.reject == (res.lr_stat > chi2.ppf(0.95, 1))
    assert res.reject == (res.p_value < 0.05)


def test_kupiec_rejects_bad_or_non_integer_counts():
    for bad in (
        lambda: kupiec_pof_test(0, 0, 0.95),
        lambda: kupiec_pof_test(100, 101, 0.95),
        lambda: kupiec_pof_test(100, 5, 1.5),
        lambda: kupiec_pof_test(100.9, 5, 0.95),   # non-integer N — no silent truncation
        lambda: kupiec_pof_test(100, 5.9, 0.95),   # non-integer x
    ):
        with pytest.raises(ValueError):
            bad()


def test_count_exceedances_strict_vs_inclusive_scalar_and_array():
    r = np.array([-0.05, -0.03, -0.03, 0.02])
    assert count_exceedances(r, 0.03, convention="strict") == 1     # only -0.05 > 0.03 loss
    assert count_exceedances(r, 0.03, convention="inclusive") == 3
    v = np.array([0.04, 0.02, 0.10, 0.01])
    assert count_exceedances(r, v, convention="strict") == 2
    with pytest.raises(ValueError):
        count_exceedances(r, np.array([0.1, 0.2]))  # array shape mismatch


def test_count_exceedances_shape_and_convention_guards():
    """count_exceedances fails closed on 0-D/2-D returns and unknown convention; array forecast
    with inclusive works; kupiec_from_returns rejects 2-D end-to-end (codex R5)."""
    with pytest.raises(ValueError):
        count_exceedances(np.array([[0.01, -0.02], [0.0, -0.05]]), 0.03)  # 2-D returns
    with pytest.raises(ValueError):
        count_exceedances(np.array(0.01), 0.03)                            # 0-D returns
    with pytest.raises(ValueError):
        count_exceedances(np.array([0.01, -0.05]), 0.03, convention="nonsense")
    r = np.array([-0.05, -0.03, 0.02])
    v = np.array([0.04, 0.03, 0.10])
    assert count_exceedances(r, v, convention="inclusive") == 2  # -0.05<=-0.04, -0.03<=-0.03
    with pytest.raises(ValueError):
        kupiec_from_returns(np.array([[0.01, -0.05]]), 0.03, 0.95)  # 2-D end-to-end


def test_kupiec_from_returns_end_to_end():
    r = np.random.default_rng(11).normal(0, 1, 2000)
    res = kupiec_from_returns(r, historical_var(r, 0.95), 0.95)
    assert res.n_obs == 2000 and 0 <= res.n_exceedances <= 2000 and not res.reject


# --- public-path coverage (codex R4: compute_measure dispatch + kupiec end-to-end) ----------


def test_compute_measure_dispatch_all_four_combinations():
    """compute_measure must dispatch to the CORRECT (measure, method) function — a misdispatch
    (e.g. historical ES → VaR) reddens here (codex R4: the public dispatch path was uncovered)."""
    r = np.random.default_rng(3).normal(0, 1, 200)
    assert compute_measure(RiskMeasureSpec("VaR", "historical", 0.95), r) == historical_var(r, 0.95)
    assert compute_measure(RiskMeasureSpec("ES", "historical", 0.95), r) == historical_es(r, 0.95)
    assert compute_measure(RiskMeasureSpec("VaR", "parametric_gaussian", 0.95), r) == parametric_gaussian_var(r, 0.95)
    assert compute_measure(RiskMeasureSpec("ES", "parametric_gaussian", 0.95), r) == parametric_gaussian_es(r, 0.95)
    # ES != VaR on this sample so a measure misdispatch cannot be silently equal
    assert historical_es(r, 0.95) != historical_var(r, 0.95)
    assert parametric_gaussian_es(r, 0.95) != parametric_gaussian_var(r, 0.95)
    # horizon dispatch (parametric only)
    spec_h = RiskMeasureSpec("ES", "parametric_gaussian", 0.99, holding_period_days=10)
    assert compute_measure(spec_h, r) == parametric_gaussian_es(r, 0.99, horizon=10)
    assert compute_measure(spec_h, r) != parametric_gaussian_es(r, 0.99, horizon=1)  # horizon must flow


def test_kupiec_from_returns_convention_and_tc_end_to_end():
    """kupiec_from_returns must honor convention (strict/inclusive → different exceedance count)
    and its test_confidence (codex R4: the end-to-end path was uncovered)."""
    r = np.array([-0.05, -0.03, -0.03, 0.02, -0.03])
    strict = kupiec_from_returns(r, 0.03, 0.95, convention="strict")
    incl = kupiec_from_returns(r, 0.03, 0.95, convention="inclusive")
    assert strict.n_exceedances == 1 and incl.n_exceedances == 4  # boundary r==-v only inclusive
    # test_confidence must FLOW END-TO-END: construct exactly 29 exceedances / 500 at var_c=0.95
    # (expected 25) so LR≈0.644 lands BETWEEN crit@0.5 (0.455) and crit@0.95 (3.84) — reject flips
    # with test_confidence, so a hardcoded tc=0.95 reddens.
    r2 = np.zeros(500)
    r2[:29] = -3.0  # 29 clear exceedances of the scalar VaR forecast v=2.0 (loss 3 > 2)
    loose = kupiec_from_returns(r2, 2.0, 0.95, test_confidence=0.50)
    strict_tc = kupiec_from_returns(r2, 2.0, 0.95, test_confidence=0.95)
    assert loose.n_exceedances == 29 and strict_tc.n_exceedances == 29
    assert loose.reject and not strict_tc.reject  # tc=0.5 rejects, tc=0.95 does not — discriminating


def test_historical_var_exact_boundary_no_float_off_by_one():
    """The EXACT decimal tail mass (Decimal(str(c))) gives the correct VaR rank at boundary
    confidences where float(1-c) is off by float noise — no ULP heuristic that mis-fires at the
    extremes (codex R4/R5). arange(n) → srt[k]=k → VaR=-k → rank=k+1."""
    assert historical_var(np.arange(40.0), 0.95) == -1.0    # 5% of 40 = rank 2 (NOT rank 3)
    assert historical_var(np.arange(10.0), 0.70) == -2.0    # 30% of 10 = rank 3 (NOT rank 4)
    assert historical_var(np.arange(20.0), 0.95) == 0.0     # 5% of 20 = rank 1
    # codex R5 counterexamples the 16-ULP snap got wrong (under-snap large N, over-snap near-int):
    assert historical_var(np.arange(1_000_000.0), 0.999999) == 0.0                 # rank 1 (was rank 2)
    assert historical_var(np.arange(40.0), float(np.nextafter(0.95, 0.0))) == -2.0  # genuine → rank 3
    assert historical_var(np.arange(40.0), 0.9499999999975) == -2.0                 # genuine → rank 3
    # a GENUINE fractional tail mass: N=7, c=0.80 → n*alpha=1.4 → rank 2
    assert historical_var(np.arange(7.0), 0.80) == -1.0


def test_exact_tail_rank_huge_n_and_decimal_context_invariant():
    """The IMPL exact-rational tail rank is correct at astronomically large n WITHOUT allocating an
    array, and is immune to the global Decimal arithmetic context (codex R6: Decimal's 28-digit
    context rounded n*alpha for large n → off-by-one; forcing localcontext(prec=2) even broke n=40).
    Fraction is unbounded-exact and context-free. (The REAL oracle helper is tested in the spine
    suite so a single-side oracle regression cannot stay green — codex R7.)"""
    from decimal import localcontext

    from app.math.risk_measures.var_es import _exact_tail_split
    from app.math.risk_measures.spine_binding import _historical_rank_oracle

    n, c = 4_750_000_000_000_001, float(np.nextafter(0.95, 0.0))
    assert _exact_tail_split(n, c)[2] == 237_500_000_000_002         # impl, no array allocated
    assert _historical_rank_oracle(n, c) == 237_500_000_000_002      # REAL oracle helper agrees
    with localcontext() as ctx:  # immune to a hostile Decimal context (prec=2 truncates arithmetic)
        ctx.prec = 2
        assert _exact_tail_split(40, 0.949)[2] == 3                  # exact m=40*0.051=2.04 → ceil 3
        assert _exact_tail_split(n, c)[2] == 237_500_000_000_002
        assert _historical_rank_oracle(n, c) == 237_500_000_000_002


def test_historical_partial_weight_single_rounding():
    """The fractional boundary weight is float(frac/n) — Fraction division THEN one rounding, not
    float(frac)/n which double-rounds by 1 ULP (codex R7). n=451, c=0.2964304278149499."""
    from fractions import Fraction

    from app.math.risk_measures.var_es import _exact_tail_split, _historical_tail

    n, c = 451, 0.2964304278149499
    srt = np.sort(np.random.default_rng(0).normal(0, 1, n))
    w, _j, _alpha = _historical_tail(srt, c)
    floor_m, frac, _rank = _exact_tail_split(n, c)
    assert isinstance(frac, Fraction) and frac != 0
    assert w[floor_m] == float(frac / n)              # single rounding (the fix)
    assert float(frac / n) != float(frac) / n         # this input actually discriminates the two


# --- codex R2 mutation goldens (each empirically RED-then-revert verified) --


def test_horizon_es_drift_aware_golden():
    """Multi-day parametric ES scales drift ~h, vol ~sqrt(h). A naive sqrt(h)*(1-day ES)
    mis-scales the drift (mu!=0) and is REJECTED (codex R2 fake-green #1: line only pinned VaR)."""
    r = np.array([-1.0, 3.0])  # mu=1 (!=0), sigma=sqrt(8)
    mu, sig = r.mean(), r.std(ddof=1)
    alpha, z = 0.01, norm.ppf(0.01)
    correct = -10 * mu + math.sqrt(10) * sig * norm.pdf(z) / alpha
    wrong = math.sqrt(10) * (-mu + sig * norm.pdf(z) / alpha)  # sqrt(h)*one_day_ES mis-scales drift
    spec = RiskMeasureSpec("ES", "parametric_gaussian", 0.99, holding_period_days=10)
    assert compute_measure(spec, r) == pytest.approx(correct, abs=1e-9)
    assert compute_measure(spec, r) != pytest.approx(wrong)
    assert parametric_gaussian_es(r, 0.99, horizon=10) == pytest.approx(correct, abs=1e-9)
    assert abs(correct - wrong) > 6.0  # drift mis-scale is a large, unambiguous gap (~6.84)


def test_historical_es_integer_boundary_golden():
    """Integer alpha*N boundary: exact mean of the worst k losses (codex R2 #2 coverage)."""
    r = np.array([-0.20, -0.12, -0.05, -0.02, 0.0, 0.03, 0.06, 0.11])  # N=8
    # c=0.75, alpha=0.25, alpha*N=2: ES = -(r_(1)+r_(2))/8 /0.25 = -(-0.20-0.12)/2 = 0.16
    assert historical_var(r, 0.75) == pytest.approx(0.12, abs=1e-12)
    assert historical_es(r, 0.75) == pytest.approx(0.16, abs=1e-12)


def test_historical_es_tie_multiplicity_golden():
    """Ties carry MULTIPLICITY: VaR/ES must not np.unique-dedup the sample (codex R2 #3).
    N=8 with -0.10 repeated x3; c=0.75, alpha=0.25, alpha*N=2."""
    r = np.array([-0.10, -0.10, -0.10, -0.02, 0.0, 0.01, 0.03, 0.05])
    assert historical_var(r, 0.75) == pytest.approx(0.10, abs=1e-12)
    assert historical_es(r, 0.75) == pytest.approx(0.10, abs=1e-12)
    # np.unique would drop the -0.10 multiplicity → length-6 sample → a DIFFERENT (0.0733) answer.
    assert historical_es(np.unique(r), 0.75) != pytest.approx(0.10, abs=1e-3)


def test_historical_es_structural_coherence_degenerate():
    """ES is written structurally as VaR + dot(w, L_tail-VaR)/alpha (codex R3), so ES>=VaR holds
    at the float level. Reverting to the raw -dot(w,srt)/alpha reddens here because it dips below
    VaR on huge equal magnitudes (sum(w)!=alpha + dot rounding).
    - N=100 all -1e12, c=0.90: raw ES = 999999999999.9999 < VaR = 1e12 (positive territory).
    - N=100 all +1e12, c=0.99: VaR/ES = -1e12 (NEGATIVE territory) — pins that a max(0,·) clamp
      on the structural form outputs -1e12, not 0 (codex R3 P1-2 reachable-clamp)."""
    neg = np.full(100, -1e12)
    for c in (0.90, 0.95, 0.99, np.nextafter(0.99, 1.0)):
        assert historical_es(neg, c) >= historical_var(neg, c)
        assert historical_es(neg, c) == pytest.approx(1e12, abs=1e-3)
    pos = np.full(100, 1e12)  # losses all -1e12 → VaR/ES negative, must NOT clamp to 0
    for c in (0.90, 0.99):
        assert historical_es(pos, c) >= historical_var(pos, c)
        assert historical_es(pos, c) == pytest.approx(-1e12, abs=1e-3)
    # broad ULP/tie/large-magnitude coherence: never dips (structural form + shared tail)
    for seed in range(60):
        g = np.random.default_rng(seed)
        x = g.choice([-1e10, -1e10, -5e9, 0.0, 3e9], size=int(g.integers(5, 80)))
        for cc in (0.80, 0.90, 0.95, 0.99, np.nextafter(0.95, 0.0)):
            assert historical_es(x, cc) >= historical_var(x, cc), f"seed={seed} c={cc}"


def test_count_exceedances_rejects_non_finite():
    """count_exceedances fails closed on NaN/inf in EITHER returns or forecast (codex R2 #4)."""
    with pytest.raises(ValueError):
        count_exceedances(np.array([0.01, np.nan, -0.02]), 0.03)
    with pytest.raises(ValueError):
        count_exceedances(np.array([0.01, np.inf, -0.02]), 0.03)
    with pytest.raises(ValueError):
        count_exceedances(np.array([0.01, -0.02]), np.array([0.03, np.inf]))


def test_kupiec_non_default_test_confidence_golden():
    """reject must use the LR test's OWN test_confidence, not a hardcoded 0.95 (codex R3 P1-4):
    N=500, x=29 gives LR≈0.644 — rejects at test_confidence=0.50 (crit≈0.455) but NOT at 0.95
    (crit≈3.84). A mutation hardcoding 0.95 reddens on the loose case."""
    lr = kupiec_pof_test(500, 29, 0.95).lr_stat
    r_loose = kupiec_pof_test(500, 29, 0.95, test_confidence=0.50)
    r_strict = kupiec_pof_test(500, 29, 0.95, test_confidence=0.95)
    assert r_loose.reject == (lr > float(chi2.ppf(0.50, 1)))
    assert r_strict.reject == (lr > float(chi2.ppf(0.95, 1)))
    assert r_loose.reject and not r_strict.reject  # the discriminating pair


def test_kupiec_p_value_exact_for_all_x_not_just_x50():
    """p_value = chi2.sf(LR, 1) must be exact for EVERY x, not only x=50 (codex R2 #5):
    a constant/wrong-for-x!=50 p_value mutation reddens on x in {0, 12, 25, 500}."""
    for n, x in [(500, 0), (500, 25), (500, 50), (500, 500), (250, 12)]:
        res = kupiec_pof_test(n, x, 0.95)
        assert res.p_value == pytest.approx(float(chi2.sf(res.lr_stat, 1)), rel=1e-9, abs=1e-15)
    # absolute anchors so the relationship above cannot be satisfied by a degenerate constant.
    # (x=25 is well-calibrated → deviance-form LR ≈ 2.5e-29 → p_value ≈ 1 to ~4e-15; codex R9.)
    assert kupiec_pof_test(500, 25, 0.95).p_value == pytest.approx(1.0, abs=1e-9)            # LR≈0
    assert kupiec_pof_test(500, 0, 0.95).p_value == pytest.approx(7.9547e-13, rel=1e-3)      # LR=51.293


# --- Fail-closed adversarial (种坏门必抓) -----------------------------------


@pytest.mark.parametrize("fn", [historical_var, historical_es, parametric_gaussian_var, parametric_gaussian_es])
def test_fail_closed_non_finite_and_empty(fn):
    with pytest.raises(ValueError):
        fn(np.array([0.01, np.nan, -0.02]), 0.95)
    with pytest.raises(ValueError):
        fn(np.array([0.01, np.inf]), 0.95)
    with pytest.raises(ValueError):
        fn(np.array([]), 0.95)


@pytest.mark.parametrize("fn", [historical_var, historical_es, parametric_gaussian_var, parametric_gaussian_es])
@pytest.mark.parametrize("c", [0.0, 1.0, -0.1, 1.5])
def test_fail_closed_bad_confidence(fn, c):
    with pytest.raises(ValueError):
        fn(np.random.default_rng(0).normal(0, 1, 50), c)


@pytest.mark.parametrize("fn", [parametric_gaussian_var, parametric_gaussian_es])
def test_parametric_needs_two_obs(fn):
    with pytest.raises(ValueError):
        fn(np.array([0.01]), 0.95)


@pytest.mark.parametrize("fn", [parametric_gaussian_var, parametric_gaussian_es])
def test_finite_input_can_reject_non_finite_output(fn):
    # sample std of {-1e308, 1e308} overflows → output would be inf → fail-closed
    with pytest.raises(ValueError, match="non-finite"):
        fn(np.array([-1e308, 1e308]), 0.99)


@pytest.mark.parametrize("fn", [parametric_gaussian_var, parametric_gaussian_es])
def test_horizon_must_be_positive_integer(fn):
    r = np.random.default_rng(0).normal(0, 1, 50)
    with pytest.raises(ValueError):
        fn(r, 0.95, horizon=0)
    with pytest.raises(ValueError):
        fn(r, 0.95, horizon=1.9)  # non-integer — no silent truncation


# --- RiskMeasureSpec typed object (canonical identity) ---------------------


def test_spec_validation_and_canonical_content_address():
    from app.lineage.ids import content_hash

    s = RiskMeasureSpec("VaR", "historical", 0.99)
    # spec_id is a canonical content_hash — recomputed, not stored, not overridable.
    assert s.spec_id == "riskmeasure_" + content_hash(
        {"measure": "VaR", "method": "historical", "confidence": 0.99, "holding_period_days": 1}
    )
    assert RiskMeasureSpec("VaR", "historical", 0.99).spec_id == s.spec_id
    assert RiskMeasureSpec("ES", "historical", 0.99).spec_id != s.spec_id
    for bad in (
        lambda: RiskMeasureSpec("nope", "historical", 0.99),
        lambda: RiskMeasureSpec("VaR", "nope", 0.99),
        lambda: RiskMeasureSpec("VaR", "historical", 1.5),
        lambda: RiskMeasureSpec("VaR", "historical", 0.99, holding_period_days=0),
        lambda: RiskMeasureSpec("VaR", "historical", 0.99, holding_period_days=1.9),  # non-int
    ):
        with pytest.raises(ValueError):
            bad()


def test_spec_id_not_externally_overridable():
    # spec_id is a read-only property; there is no constructor field to override it.
    s = RiskMeasureSpec("VaR", "historical", 0.99)
    with pytest.raises((AttributeError, TypeError)):
        s.spec_id = "riskmeasure_forged"  # type: ignore[misc]
