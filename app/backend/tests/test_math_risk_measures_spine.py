"""Mathematical Spine · VaR/ES/Kupiec 绑定的【对抗式】测试（金融数学 kernel P0-A 命门）。

codex R2 治理裁决落地：风险度量 kernel 接 canonical spine。这里把【真实】``var_es.py`` /
``backtest.py`` 绑进脊柱，用【独立】oracle（numpy 逆CDF 分位 / 稠密网格 Riemann 积分 / scipy
power_divergence）对账，并种漂移实现证明被抓；外加真源码指纹 staleness（改实现任一环→门 fresh 拒）。

诚实边界：门校验「声明的 binding + ConsistencyCheck 结果 + 内容指纹是否自洽」，不自证数学命题——
实现是否真的对，靠这里独立 oracle 的内容质量 + 跨厂商 Verifier（codex）。
"""

from __future__ import annotations

import inspect
import math

import numpy as np
import pytest
from scipy.stats import norm

from app.lineage import content_hash
from app.lineage.spine import LABEL_CHALLENGED, LABEL_PROOF_BACKED, PROOF_BACKED
from app.lineage.spine_binder import code_fingerprint
from app.lineage.spine_ledger import SpineLedger
from app.math.risk_measures import spine_binding as sb


# ── 理论产物：三条都是有真实定义/推导的 proof_backed ──────────────────────────
@pytest.mark.parametrize("art", [sb.VAR_ARTIFACT, sb.ES_ARTIFACT, sb.KUPIEC_ARTIFACT])
def test_artifacts_are_proof_backed_with_real_definition(art):
    assert art.proof_status == PROOF_BACKED
    assert art.statement and art.derivation and art.definition
    assert art.assumptions and art.failure_conditions
    assert art.artifact_id.startswith("math_")


# ── 独立 oracle 忠实重算（sanity：oracle 与真 impl 在 fixtures 上一致）──────────
def test_var_oracle_matches_real_impl():
    for fx in sb._var_es_fixtures():
        impl = (
            sb._ve.historical_var(fx["returns"], fx["confidence"])
            if fx["method"] == "historical"
            else sb._ve.parametric_gaussian_var(fx["returns"], fx["confidence"], horizon=fx["horizon"])
        )
        oracle = sb._var_oracle(**fx)
        assert abs(impl - oracle) <= 1e-6, (fx, impl, oracle)


def test_var_oracle_matches_impl_on_boundary_counterexamples():
    """impl and the INDEPENDENT decimal-rank oracle agree on the exact-boundary confidences where
    float(1-c)*n mis-rounds (codex R4/R5). An oracle using round(n*alpha,9) — or the impl using a
    float/ULP-snap rank — would diverge here, so this pins both to the exact decimal rank."""
    for n, c in [(40, 0.95), (10, 0.70), (1_000_000, 0.999999),
                 (40, float(np.nextafter(0.95, 0.0))), (40, 0.9499999999975), (7, 0.80)]:
        r = np.sort(np.random.default_rng(n).normal(0, 1, n))
        impl = sb._ve.historical_var(r, c)
        oracle = sb._var_oracle(returns=r, confidence=c, method="historical")
        assert impl == oracle, (n, c, impl, oracle)


def test_var_oracle_actually_calls_the_rank_helper(monkeypatch):
    """`_var_oracle` must route through `_historical_rank_oracle` — proven by monkeypatching the
    helper and observing the oracle's output change (codex R7: a huge-N test that re-implements the
    rank formula inline would let a single-side oracle regression stay green)."""
    r = np.arange(10.0)
    assert sb._var_oracle(returns=r, confidence=0.70, method="historical") == -2.0  # rank 3 → srt[2]
    monkeypatch.setattr(sb, "_historical_rank_oracle", lambda n, c: 1)  # force rank 1
    assert sb._var_oracle(returns=r, confidence=0.70, method="historical") == 0.0   # srt[0]=0 → -0.0
    monkeypatch.undo()
    assert sb._var_oracle(returns=r, confidence=0.70, method="historical") == -2.0


def test_es_oracle_matches_real_impl_within_grid_tolerance():
    for fx in sb._var_es_fixtures():
        impl = (
            sb._ve.historical_es(fx["returns"], fx["confidence"])
            if fx["method"] == "historical"
            else sb._ve.parametric_gaussian_es(fx["returns"], fx["confidence"], horizon=fx["horizon"])
        )
        oracle = sb._es_oracle(**fx)
        assert abs(impl - oracle) <= 1e-7, (fx, impl, oracle)  # codex R4: tightened from 1e-5


def test_es_tolerance_is_tight_and_consistent():
    """ES tolerance is 1e-7 in BOTH the binding metadata and the consistency check, and a 5e-6
    ES drift must FAIL (codex R4: a 1e-5 tolerance let a 5e-6 drift pass the gate 假绿)."""
    assert sb.build_es_binding().tolerance == 1e-7

    def _drift_es(returns, confidence):
        return sb._ve.historical_es(returns, confidence) + 5e-6

    assert sb.es_consistency_check(impl=_drift_es).result == "fail"


def test_kupiec_oracle_matches_real_impl():
    # oracle + impl both return (lr, p_value, reject) — full-tuple agreement (codex R3).
    for fx in sb._kupiec_fixtures():
        impl, oracle = sb._kupiec_impl(**fx), sb._kupiec_oracle(**fx)
        assert all(abs(a - b) <= 1e-6 for a, b in zip(impl, oracle)), (fx, impl, oracle)


# ── 正确实现 → 一致性 pass + 门放行 proof_backed（含 pit-bound）─────────────────
@pytest.mark.parametrize(
    "verify", [sb.verify_var_consistency, sb.verify_es_consistency, sb.verify_kupiec_consistency]
)
def test_full_green_promotes_to_proof_backed(verify):
    d = verify(requested_label=LABEL_PROOF_BACKED)
    assert d.promotable is True, d.verdict_text
    assert d.granted_label == LABEL_PROOF_BACKED
    assert "pit-bound(§6 estimator 绑 PIT)" in d.matched_rules
    assert "consistency-pass(§6 实现↔定义一致)" in d.matched_rules


# ── 命门：种漂移实现 → oracle 对账 fail → 门拒 ────────────────────────────────
def test_es_naive_tail_mean_drift_caught_and_rejected():
    """naive mean(r[r<=q]) 尾均值（R1 的坏实现）→ 独立网格 oracle 不一致 → 门拒。"""

    def _naive_es(returns, confidence):
        arr = np.asarray(returns, float)
        q = np.quantile(arr, 1.0 - float(confidence), method="inverted_cdf")
        return -arr[arr <= q].mean()

    cc = sb.es_consistency_check(impl=_naive_es)
    assert cc.result == "fail" and "实现偏离定义" in cc.failure_reason
    d = sb.verify_es_consistency(requested_label=LABEL_PROOF_BACKED, impl=_naive_es)
    assert d.promotable is False and d.granted_label == LABEL_CHALLENGED
    assert any("consistency-pass" in v and "不一致" in v for v in d.violations)


def test_var_linear_quantile_drift_caught():
    """VaR 漂成 numpy 'linear' 插值分位（≠ inverted_cdf 定义）→ 对账 fail。"""

    def _linear_var(returns, confidence):
        return -float(np.quantile(np.asarray(returns, float), 1.0 - float(confidence), method="linear"))

    cc = sb.var_consistency_check(impl=_linear_var)
    assert cc.result == "fail"


# ── 真源码指纹：改实现任一环（含 helper）→ 指纹变 → staleness 抓 ────────────────
def test_fingerprints_are_real_source_hash_and_path_independent():
    """The fingerprint = content_hash({chain-fingerprint, public-api SOURCE TEXT}). It folds the
    package source TEXT (path-free), NOT the module object whose repr embeds the absolute checkout
    path — so it is reproducible across CI / other checkouts (codex R9 export coverage + R10 path)."""
    for fp_fn, chain in (
        (sb.var_code_fingerprint, sb._VAR_IMPL_CHAIN),
        (sb.es_code_fingerprint, sb._ES_IMPL_CHAIN),
        (sb.kupiec_code_fingerprint, sb._KUPIEC_IMPL_CHAIN),
    ):
        expected = content_hash(
            {"chain": code_fingerprint(*chain), "public_api": sb._public_api_source()}
        )
        assert fp_fn() == expected
    # no absolute checkout path leaks into the fingerprint inputs (path-independence)
    api_src = sb._public_api_source()
    assert "/Users/" not in api_src and "\\Users\\" not in api_src
    for chain in (sb._VAR_IMPL_CHAIN, sb._ES_IMPL_CHAIN, sb._KUPIEC_IMPL_CHAIN):
        for fn in chain:
            assert "/Users/" not in inspect.getsource(fn)


def test_fingerprint_covers_whole_chain_not_just_main():
    only_main = code_fingerprint(sb._ve.historical_es)
    whole_chain = code_fingerprint(*sb._ES_IMPL_CHAIN)
    assert only_main != whole_chain  # helper (_historical_tail/_tail_weights) 改动也会变指纹


def test_pinned_fingerprints_match_live_source():
    """已审定指纹 == live 源指纹；改 var_es.py/backtest.py 未重审 → 此处 RED 提醒刷新常量。"""
    assert sb.VAR_PINNED_FINGERPRINT == sb.var_code_fingerprint()
    assert sb.ES_PINNED_FINGERPRINT == sb.es_code_fingerprint()
    assert sb.KUPIEC_PINNED_FINGERPRINT == sb.kupiec_code_fingerprint()


def test_public_exports_folded_into_every_fingerprint():
    """The package public __init__ (its export bindings) is folded into ALL THREE fingerprints, so
    re-binding a public export (e.g. historical_var = historical_es) trips staleness — the exports
    were previously in no chain, so a re-bind was a fake-green (codex R9)."""
    pkg_src = sb._public_api_source()
    assert "historical_var" in pkg_src and "historical_es" in pkg_src
    # each fingerprint materially depends on the package source: the bare chain fingerprint differs
    # from the real one (which folds in the public-api source via content_hash).
    assert code_fingerprint(*sb._VAR_IMPL_CHAIN) != sb.var_code_fingerprint()
    assert code_fingerprint(*sb._ES_IMPL_CHAIN) != sb.es_code_fingerprint()
    assert code_fingerprint(*sb._KUPIEC_IMPL_CHAIN) != sb.kupiec_code_fingerprint()


def test_public_path_sources_are_in_fingerprint_chains():
    """The public dispatch + spec construction invariants materially contribute to the VaR/ES
    fingerprint (codex R4/R5): removing compute_measure's dispatch or RiskMeasureSpec's validation
    changes the source → live fingerprint drifts → the pinned tripwire + gate fresh clause fire."""
    for chain in (sb._VAR_IMPL_CHAIN, sb._ES_IMPL_CHAIN):
        assert sb._spec.compute_measure in chain
        assert sb._spec.RiskMeasureSpec in chain
        # each materially contributes: dropping it changes the chain fingerprint
        for member in (sb._spec.compute_measure, sb._spec.RiskMeasureSpec):
            without = tuple(f for f in chain if f is not member)
            assert code_fingerprint(*chain) != code_fingerprint(*without)
    # Kupiec end-to-end path + public return contract + numerical helpers are fingerprinted too
    # (codex R8/R10): a shape change to KupiecResult, a behavior change in count_exceedances, or a
    # numerical change in the bd0 deviance helper must all trip the fresh clause.
    for member in (
        sb._bt.kupiec_from_returns,
        sb._bt.count_exceedances,
        sb._bt.KupiecResult,
        sb._bt._bd0,
        sb._bt._int_ratio,
    ):
        assert member in sb._KUPIEC_IMPL_CHAIN
        without = tuple(f for f in sb._KUPIEC_IMPL_CHAIN if f is not member)
        assert code_fingerprint(*sb._KUPIEC_IMPL_CHAIN) != code_fingerprint(*without)


def test_stale_binding_rejected_when_source_fingerprint_drifts():
    d = sb.verify_es_consistency(
        requested_label=LABEL_PROOF_BACKED, current_code_hash="0000deadbeef0000"
    )
    assert d.promotable is False
    assert any("fresh" in v and "未刷新" in v for v in d.violations)


def test_default_verify_path_enforces_staleness(monkeypatch):
    """codex R3 P1-1: the DEFAULT verify_* path (no explicit hashes) records the PINNED
    fingerprint for the binding and reads the LIVE fingerprint for current — so if the source
    drifts (live != pinned), the default gate rejects. (An earlier default self-fingerprinted
    both, making staleness undetectable by default.)"""
    for verify, live_fp_name in (
        (sb.verify_var_consistency, "var_code_fingerprint"),
        (sb.verify_es_consistency, "es_code_fingerprint"),
        (sb.verify_kupiec_consistency, "kupiec_code_fingerprint"),
    ):
        assert verify(requested_label=LABEL_PROOF_BACKED).promotable  # clean state promotes
        monkeypatch.setattr(sb, live_fp_name, lambda: "0000deadbeef0000")
        d = verify(requested_label=LABEL_PROOF_BACKED)  # no explicit hashes → default path
        assert not d.promotable and any("fresh" in v for v in d.violations), (verify, d.verdict_text)
        monkeypatch.undo()


# ── 落账（append-only ledger 可校验）──────────────────────────────────────────
def test_bindings_recorded_to_ledger(tmp_path):
    led = SpineLedger(tmp_path)
    led.record_artifact(sb.ES_ARTIFACT)
    b = sb.build_es_binding()
    led.record_binding(b)
    led.record_check(sb.es_consistency_check())
    latest = led.latest_binding(sb.ES_ARTIFACT.artifact_id)
    assert latest["code_content_hash"] == sb.es_code_fingerprint()
    assert led.checks_for(b.binding_id)[0]["result"] == "pass"
    ok, issues = led.verify_chain()
    assert ok, issues


# ── 与纯数学层交叉：spine oracle 独立复算命中主 golden ─────────────────────────
def test_spine_es_oracle_reproduces_fractional_boundary_golden():
    """独立网格 oracle 应独立复现主测试的 AT fractional 黄金 0.0914（不同算路、同一定义）。"""
    r = np.array([-0.10, -0.07, -0.05, -0.02, 0.01, 0.03, 0.06])
    got = sb._es_oracle(returns=r, confidence=0.80, method="historical")
    assert got == pytest.approx(0.0914285714285714, abs=1e-6)
    assert got != pytest.approx(0.085, abs=1e-4)  # naive tail-mean rejected by the oracle too
