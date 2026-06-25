"""Mathematical Spine · DSR 绑定的【对抗式】测试（全链贯穿第一段 · finding spine-consistency-gate/01）。

命门：DSR（信任层核心估计器）若实现漂离数学定义，Spine 数值一致性对账必判 fail、一致性门
必拒升级。这里把【真实】`eval/dsr.py` 绑进脊柱，用【独立】oracle（scipy 矩）对账，并种漂移
impl 证明被抓；外加真源码指纹 staleness（改 dsr.py 任一环→门 fresh 子句拒）。
"""

from __future__ import annotations

import inspect
import math

import numpy as np
import pytest
from scipy.stats import norm

from app.eval.dsr import deflated_sharpe_ratio
from app.eval.spine_bindings import (
    DSR_ARTIFACT,
    build_dsr_binding,
    dsr_code_fingerprint,
    dsr_consistency_check,
    dsr_oracle,
    verify_dsr_consistency,
    _fixtures,
    _DSR_IMPL_CHAIN,
)
from app.lineage import content_hash
from app.lineage.spine import LABEL_CHALLENGED, LABEL_PROOF_BACKED, PROOF_BACKED
from app.lineage.spine_binder import code_fingerprint
from app.lineage.spine_ledger import SpineLedger


# 种漂移：丢掉 E[max] 通缩 + denom（退回裸 Sharpe 显著性）——已知坏实现，对账必抓。
def _drifted_dsr(*, returns, n_trials, periods_per_year=252, var_sr_hat=None):
    arr = np.asarray(returns, dtype=float)
    n = arr.size
    if n < 3:
        return 0.0
    std = arr.std(ddof=1)
    if std <= 0:
        return 0.0
    sr_pp = arr.mean() / std
    z = sr_pp * math.sqrt(n - 1)  # BUG: 无通缩、无 studentize denom
    return float(norm.cdf(z))


# ── 理论产物 ─────────────────────────────────────────────────────────────────
def test_dsr_artifact_is_proof_backed_with_real_definition():
    assert DSR_ARTIFACT.proof_status == PROOF_BACKED
    assert DSR_ARTIFACT.statement and DSR_ARTIFACT.derivation
    assert DSR_ARTIFACT.assumptions and DSR_ARTIFACT.failure_conditions
    assert DSR_ARTIFACT.artifact_id.startswith("math_")


# ── 独立 oracle 忠实重算（sanity：oracle 与真 impl 一致）────────────────────────
def test_dsr_oracle_matches_real_impl():
    for fx in _fixtures():
        impl_out = deflated_sharpe_ratio(**fx)
        oracle_out = dsr_oracle(**fx)
        assert abs(impl_out - oracle_out) <= 1e-6, (fx, impl_out, oracle_out)


# ── 正确实现 → 一致性 pass + 门放行 proof_backed ──────────────────────────────
def test_dsr_consistency_check_passes_on_real_impl():
    cc = dsr_consistency_check()
    assert cc.result == "pass", cc.failure_reason


def test_dsr_full_green_promotes_to_proof_backed():
    d = verify_dsr_consistency(requested_label=LABEL_PROOF_BACKED)
    assert d.promotable is True, d.verdict_text
    assert d.granted_label == LABEL_PROOF_BACKED
    assert "pit-bound(§6 estimator 绑 PIT)" in d.matched_rules
    assert "consistency-pass(§6 实现↔定义一致)" in d.matched_rules


# ── 命门：种漂移实现 → oracle 对账 fail → 门拒 ───────────────────────────────
def test_dsr_drift_caught_by_consistency_check():
    cc = dsr_consistency_check(impl=_drifted_dsr)
    assert cc.result == "fail"
    assert "实现偏离定义" in cc.failure_reason


def test_dsr_drift_rejected_by_gate():
    d = verify_dsr_consistency(requested_label=LABEL_PROOF_BACKED, impl=_drifted_dsr)
    assert d.promotable is False
    assert any("consistency-pass" in v and "不一致" in v for v in d.violations)
    assert d.granted_label == LABEL_CHALLENGED


# ── 真源码指纹：改 dsr.py 任一环 → 指纹变 → staleness 抓 ──────────────────────
def test_fingerprint_is_real_source_hash():
    fp = dsr_code_fingerprint()
    # 指纹 = content_hash(整条实现链的 inspect.getsource)
    sources = [{"qualname": fn.__qualname__, "src": inspect.getsource(fn)} for fn in _DSR_IMPL_CHAIN]
    assert fp == content_hash(sources)
    assert fp == dsr_code_fingerprint()  # 稳定
    assert build_dsr_binding().code_content_hash == fp


def test_fingerprint_covers_whole_chain_not_just_main():
    # 只指纹主函数 vs 指纹整条链 → 不同；证明 helper（_skew 等）改动也会变指纹（防绕过）。
    only_main = code_fingerprint(deflated_sharpe_ratio)
    whole_chain = code_fingerprint(*_DSR_IMPL_CHAIN)
    assert only_main != whole_chain

    def _unrelated():
        return 1.0

    assert code_fingerprint(_unrelated) != code_fingerprint(deflated_sharpe_ratio)


def test_stale_binding_rejected_when_source_fingerprint_drifts():
    # 模拟 dsr.py 被改但 binding 未刷新：运行时指纹 ≠ binding 记录的指纹 → 门 fresh 子句拒。
    d = verify_dsr_consistency(
        requested_label=LABEL_PROOF_BACKED,
        current_code_hash="0000deadbeef0000",  # 假装实现已漂移
    )
    assert d.promotable is False
    assert any("fresh" in v and "未刷新" in v for v in d.violations)


# ── 落账（append-only）────────────────────────────────────────────────────────
def test_dsr_binding_recorded_to_ledger(tmp_path):
    led = SpineLedger(tmp_path)
    led.record_artifact(DSR_ARTIFACT)
    b = build_dsr_binding()
    led.record_binding(b)
    led.record_check(dsr_consistency_check())
    latest = led.latest_binding(DSR_ARTIFACT.artifact_id)
    assert latest["code_content_hash"] == dsr_code_fingerprint()
    assert led.checks_for(b.binding_id)[0]["result"] == "pass"
    ok, issues = led.verify_chain()
    assert ok, issues
