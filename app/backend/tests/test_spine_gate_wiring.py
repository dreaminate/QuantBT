"""Mathematical Spine · 接进生产 promote 路径（overfit gate）的【对抗式】测试。

命门接生产：信任层 `run_overfit_gate` 的红绿全建在 DSR 估计器上。本测证明——若 DSR 实现漂离
数学定义（脊柱一致性门拒），gate **绝不**产出「证据充分」，而是降级到 insufficient_evidence
（复用既有非 promote sink），诚实标 math-inconsistency。正常路径（DSR 一致）color 不变、不破基线。
决策 D-MATH-SPINE：守门器自身估计器跑偏 = 系统错误。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import app.eval.overfit_gate as overfit_gate
from app.eval.n_eff import n_eff_from_matrix
from app.eval.overfit_gate import run_overfit_gate
from app.eval.spine_bindings import verify_dsr_consistency
from app.lineage.spine import LABEL_PROOF_BACKED


def _green_setup():
    """1 列强 alpha + 9 列噪声（凑够 PBO min_n=10），alpha 列为评估目标 → 真信号可 green。"""
    rng = np.random.default_rng(7)
    cols = [rng.normal(loc=0.004, scale=0.01, size=600)]
    for _ in range(9):
        cols.append(rng.normal(loc=0.0, scale=0.01, size=600))
    mat = np.column_stack(cols)
    return mat[:, 0], mat


# 种漂移 DSR（丢 E[max] 通缩）——已知坏估计器。
def _drifted_dsr(*, returns, n_trials, periods_per_year=252, var_sr_hat=None):
    arr = np.asarray(returns, dtype=float)
    if arr.size < 3:
        return 0.0
    std = arr.std(ddof=1)
    if std <= 0:
        return 0.0
    return float(__import__("scipy.stats", fromlist=["norm"]).norm.cdf(arr.mean() / std * math.sqrt(arr.size - 1)))


# ── 正常路径：DSR 一致 → 记录 spine_consistency、color 不变 ─────────────────────
def test_gate_records_spine_consistency_when_dsr_consistent():
    target, mat = _green_setup()
    v = run_overfit_gate(target, n_eff=n_eff_from_matrix(mat), returns_matrix=mat, asset_class="crypto")
    assert v.spine_consistency is not None
    assert v.spine_consistency["dsr"]["promotable"] is True
    assert v.spine_consistency["dsr"]["granted_label"] == LABEL_PROOF_BACKED
    assert v.color == "green", f"DSR 一致的正常路径不该被脊柱改判：{v.reason}"


# ── 命门：DSR 漂移 → gate 降级 insufficient_evidence，挡住本会 green 的裁决 ───────
def test_gate_downgrades_to_insufficient_when_dsr_drifts(monkeypatch):
    drifted_decision = verify_dsr_consistency(impl=_drifted_dsr)
    assert drifted_decision.promotable is False  # 前提：漂移确实被脊柱门拒
    monkeypatch.setattr(overfit_gate, "dsr_spine_decision", lambda: drifted_decision)

    target, mat = _green_setup()  # 这套数据本会 green
    v = run_overfit_gate(target, n_eff=n_eff_from_matrix(mat), returns_matrix=mat, asset_class="crypto")
    assert v.color == "insufficient_evidence", "DSR 漂移却仍放行 = 守门器坏却假绿灯"
    assert v.spine_consistency["dsr"]["promotable"] is False
    assert "数学一致性失败" in v.reason
    assert "不得 promote" in v.reason


def test_drift_overrides_a_would_be_green(monkeypatch):
    # 先确认无漂移时这套数据确实 green（隔离：漂移是唯一改判因素）。
    target, mat = _green_setup()
    v_ok = run_overfit_gate(target, n_eff=n_eff_from_matrix(mat), returns_matrix=mat, asset_class="crypto")
    assert v_ok.color == "green"

    drifted_decision = verify_dsr_consistency(impl=_drifted_dsr)
    monkeypatch.setattr(overfit_gate, "dsr_spine_decision", lambda: drifted_decision)
    v_drift = run_overfit_gate(target, n_eff=n_eff_from_matrix(mat), returns_matrix=mat, asset_class="crypto")
    assert v_drift.color == "insufficient_evidence"  # 漂移把 green 翻成证据无效


# ── 逃生阀：check_spine_consistency=False → 跳过（向后兼容） ─────────────────────
def test_check_spine_consistency_false_skips():
    target, mat = _green_setup()
    v = run_overfit_gate(target, n_eff=n_eff_from_matrix(mat), returns_matrix=mat,
                         asset_class="crypto", check_spine_consistency=False)
    assert v.spine_consistency is None
    assert v.color == "green"


# ── 漂移不掩盖真红：本就 red 的也不会被脊柱误改成 green（脊柱只会更严不会放水）──────
def test_spine_never_loosens_a_red(monkeypatch):
    rng = np.random.default_rng(3)
    mat = rng.normal(size=(600, 50)) * 0.01  # 纯噪声
    target = mat[:, 0]
    v = run_overfit_gate(target, n_eff=n_eff_from_matrix(mat), returns_matrix=mat, asset_class="crypto")
    assert v.color != "green"  # 噪声本就非 green
    assert v.spine_consistency["dsr"]["promotable"] is True  # 脊柱不改判一致的估计器


# ── codex P2-1 修：生产 staleness 真可达（pinned≠live → fresh 子句拒）─────────────
def test_dsr_pinned_fingerprint_matches_current_source():
    """tripwire：dsr.py 实现链一改即硬失败，逼显式重核 + 刷新 pinned（= 刷新 binding 审定动作）。"""
    from app.eval.spine_bindings import DSR_PINNED_FINGERPRINT, dsr_code_fingerprint

    assert DSR_PINNED_FINGERPRINT == dsr_code_fingerprint(), (
        "dsr.py 实现链已改 → 必须重核 DSR↔数学定义一致(test_spine_dsr_binding) 并把 "
        "DSR_PINNED_FINGERPRINT 更新为新指纹（显式刷新 TheoryImplementationBinding 的审定动作）"
    )


def test_production_staleness_reachable_with_stale_pin():
    # 模拟 dsr.py 改了但 pinned 常量没刷新：binding 记录=旧 pinned，live=当前 → §6 fresh 子句真拒。
    dec = verify_dsr_consistency(pinned_code_hash="stale000pinned00")
    assert dec.promotable is False
    assert any("fresh" in v and "未刷新" in v for v in dec.violations)


def test_production_consistent_when_pin_matches():
    # pinned == live（正常）→ fresh 过、promotable（数值也一致）。
    from app.eval.spine_bindings import DSR_PINNED_FINGERPRINT

    dec = verify_dsr_consistency(pinned_code_hash=DSR_PINNED_FINGERPRINT)
    assert dec.promotable is True
    assert dec.granted_label == LABEL_PROOF_BACKED


# ── codex P2-2 修：DSR 执行/签名漂移致抛错 → fail-closed（不崩 gate）──────────────
def test_gate_fail_closed_when_dsr_spine_check_raises(monkeypatch):
    def _boom():
        raise RuntimeError("DSR 签名漂移")

    monkeypatch.setattr(overfit_gate, "dsr_spine_decision", _boom)
    target, mat = _green_setup()
    v = run_overfit_gate(target, n_eff=n_eff_from_matrix(mat), returns_matrix=mat, asset_class="crypto")
    assert v.color == "insufficient_evidence"  # 抛错也 fail-closed，不让 promote 报错
    assert v.spine_consistency["dsr"]["promotable"] is False
    assert v.spine_consistency["dsr"]["granted_label"] == "execution_error"
    assert "执行失败" in v.spine_consistency["dsr"]["violations"][0]


def test_drift_verdict_does_not_report_dsr_numbers(monkeypatch):
    # 估计器不可信时不报 DSR 单点数字（NaN），防被误读为"修复后好夏普"。
    drifted_decision = verify_dsr_consistency(impl=_drifted_dsr)
    monkeypatch.setattr(overfit_gate, "dsr_spine_decision", lambda: drifted_decision)
    target, mat = _green_setup()
    v = run_overfit_gate(target, n_eff=n_eff_from_matrix(mat), returns_matrix=mat, asset_class="crypto")
    assert v.dsr_conservative != v.dsr_conservative  # NaN
