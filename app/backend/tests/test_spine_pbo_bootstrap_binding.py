"""Mathematical Spine · PBO + Bootstrap 经脊柱绑定的【对抗式】测试（三角补齐·finding 02）。

把信任层三角的另两支估计器（CSCV-PBO / Bootstrap CI）经脊柱 property-based 绑定，并接进
生产 `run_overfit_gate`。命门：任一支实现漂离数学定义（性质违反 / 源 staleness / 执行抛错）→
gate fail-closed 降级 insufficient_evidence，绝不在坏估计器上产「证据充分」。
"""

from __future__ import annotations

import numpy as np
import pytest

import app.eval.overfit_gate as overfit_gate
from app.eval.bootstrap import BootstrapCI, bootstrap_sharpe_ci
from app.eval.n_eff import n_eff_from_matrix
from app.eval.overfit_gate import run_overfit_gate
from app.eval.pbo import PBOResult, cscv_pbo
from app.eval.spine_bindings import (
    BOOTSTRAP_ARTIFACT,
    BOOTSTRAP_PINNED_FINGERPRINT,
    PBO_ARTIFACT,
    PBO_PINNED_FINGERPRINT,
    bootstrap_code_fingerprint,
    bootstrap_consistency_check,
    pbo_code_fingerprint,
    pbo_consistency_check,
    verify_bootstrap_consistency,
    verify_pbo_consistency,
)
from app.lineage.spine import LABEL_PROOF_BACKED, PROOF_BACKED


def _green_setup():
    rng = np.random.default_rng(7)
    cols = [rng.normal(loc=0.004, scale=0.01, size=600)]
    for _ in range(9):
        cols.append(rng.normal(loc=0.0, scale=0.01, size=600))
    mat = np.column_stack(cols)
    return mat[:, 0], mat


# 种漂移 PBO：sign 反转（pbo→1−pbo）——真信号本应低 pbo，反转后变高 → P4/P5 必抓。
def _drifted_pbo(rm, s_blocks=8, **kw):
    r = cscv_pbo(rm, s_blocks=s_blocks, **kw)
    return PBOResult(
        pbo=1.0 - r.pbo, n_strategies=r.n_strategies, n_combinations=r.n_combinations,
        s_blocks=r.s_blocks, lambda_logit_mean=r.lambda_logit_mean,
        expected_combinations_full=r.expected_combinations_full, enumerated_full=r.enumerated_full,
    )


# 种漂移 bootstrap：lower/upper 交换 → B1(lower≤upper) 必抓。
def _drifted_bootstrap(returns, **kw):
    ci = bootstrap_sharpe_ci(returns, **kw)
    return BootstrapCI(estimate=ci.estimate, lower=ci.upper, upper=ci.lower, n_boot=ci.n_boot, method=ci.method)


# ── PBO 绑定 ─────────────────────────────────────────────────────────────────
def test_pbo_artifact_proof_backed():
    assert PBO_ARTIFACT.proof_status == PROOF_BACKED
    assert PBO_ARTIFACT.statement and PBO_ARTIFACT.derivation


def test_pbo_properties_pass_on_real_impl():
    assert pbo_consistency_check().result == "pass"


def test_pbo_full_green_promotes():
    d = verify_pbo_consistency(pinned_code_hash=PBO_PINNED_FINGERPRINT)
    assert d.promotable is True, d.verdict_text
    assert d.granted_label == LABEL_PROOF_BACKED


def test_pbo_drift_caught_by_property_check():
    cc = pbo_consistency_check(impl=_drifted_pbo)
    assert cc.result == "fail"
    assert "实现偏离定义" in cc.failure_reason


def test_pbo_drift_rejected_by_gate():
    d = verify_pbo_consistency(impl=_drifted_pbo, pinned_code_hash=PBO_PINNED_FINGERPRINT)
    assert d.promotable is False


def test_pbo_pinned_fingerprint_matches_source():
    assert PBO_PINNED_FINGERPRINT == pbo_code_fingerprint(), (
        "pbo.py 实现链已改 → 重核性质 + 更新 PBO_PINNED_FINGERPRINT"
    )


def test_pbo_staleness_reachable_with_stale_pin():
    d = verify_pbo_consistency(pinned_code_hash="stale00pbo000000")
    assert d.promotable is False
    assert any("fresh" in v and "未刷新" in v for v in d.violations)


# ── Bootstrap 绑定 ───────────────────────────────────────────────────────────
def test_bootstrap_artifact_proof_backed():
    assert BOOTSTRAP_ARTIFACT.proof_status == PROOF_BACKED
    assert BOOTSTRAP_ARTIFACT.statement and BOOTSTRAP_ARTIFACT.derivation


def test_bootstrap_properties_pass_on_real_impl():
    assert bootstrap_consistency_check().result == "pass"


def test_bootstrap_full_green_promotes():
    d = verify_bootstrap_consistency(pinned_code_hash=BOOTSTRAP_PINNED_FINGERPRINT)
    assert d.promotable is True, d.verdict_text
    assert d.granted_label == LABEL_PROOF_BACKED


def test_bootstrap_drift_caught_by_property_check():
    cc = bootstrap_consistency_check(impl=_drifted_bootstrap)
    assert cc.result == "fail"
    assert "实现偏离定义" in cc.failure_reason


def test_bootstrap_drift_rejected_by_gate():
    d = verify_bootstrap_consistency(impl=_drifted_bootstrap, pinned_code_hash=BOOTSTRAP_PINNED_FINGERPRINT)
    assert d.promotable is False


def test_bootstrap_pinned_fingerprint_matches_source():
    assert BOOTSTRAP_PINNED_FINGERPRINT == bootstrap_code_fingerprint(), (
        "bootstrap.py 实现链已改 → 重核性质 + 更新 BOOTSTRAP_PINNED_FINGERPRINT"
    )


def test_bootstrap_staleness_reachable_with_stale_pin():
    d = verify_bootstrap_consistency(pinned_code_hash="stale00boot00000")
    assert d.promotable is False
    assert any("fresh" in v and "未刷新" in v for v in d.violations)


# ── 生产 gate：三支全核，任一漂移 fail-closed ─────────────────────────────────
def test_gate_checks_all_three_estimators_when_consistent():
    target, mat = _green_setup()
    v = run_overfit_gate(target, n_eff=n_eff_from_matrix(mat), returns_matrix=mat, asset_class="crypto")
    assert set(v.spine_consistency.keys()) == {"dsr", "pbo", "bootstrap"}
    assert all(v.spine_consistency[k]["promotable"] for k in ("dsr", "pbo", "bootstrap"))
    assert v.color == "green", v.reason


def test_gate_fail_closed_when_pbo_drifts(monkeypatch):
    drifted = verify_pbo_consistency(impl=_drifted_pbo, pinned_code_hash=PBO_PINNED_FINGERPRINT)
    assert drifted.promotable is False
    monkeypatch.setattr(overfit_gate, "pbo_spine_decision", lambda: drifted)
    target, mat = _green_setup()
    v = run_overfit_gate(target, n_eff=n_eff_from_matrix(mat), returns_matrix=mat, asset_class="crypto")
    assert v.color == "insufficient_evidence"
    assert v.spine_consistency["pbo"]["promotable"] is False
    assert "pbo" in v.reason and "不得 promote" in v.reason


def test_gate_fail_closed_when_bootstrap_drifts(monkeypatch):
    drifted = verify_bootstrap_consistency(impl=_drifted_bootstrap, pinned_code_hash=BOOTSTRAP_PINNED_FINGERPRINT)
    assert drifted.promotable is False
    monkeypatch.setattr(overfit_gate, "bootstrap_spine_decision", lambda: drifted)
    target, mat = _green_setup()
    v = run_overfit_gate(target, n_eff=n_eff_from_matrix(mat), returns_matrix=mat, asset_class="crypto")
    assert v.color == "insufficient_evidence"
    assert v.spine_consistency["bootstrap"]["promotable"] is False
    assert "bootstrap" in v.reason
