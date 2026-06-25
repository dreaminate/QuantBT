"""Mathematical Spine · MinTRL + PSR 经脊柱绑定的【对抗式】测试（交叉校验恒等式·接 cold_start）。

MinTRL/PSR 有两条精确解析恒等式（强于纯统计 property）：M1 n=MinTRL→PSR≡confidence；
M4 PSR(r,E[max_N])≡DSR(r,N)。漂移即恒等式破 → 脊柱一致性 fail → run verdict cold_start 标
dsr_applicable=False（呈现层 fail-soft 诚实标，不动治理闸门）。finding 03。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import app.run_verdict as run_verdict
from app.eval.dsr import MinTRLResult, minimum_track_record_length, probabilistic_sharpe_ratio
from app.eval.spine_bindings import (
    MINTRL_ARTIFACT,
    MINTRL_PINNED_FINGERPRINT,
    mintrl_code_fingerprint,
    mintrl_consistency_check,
    verify_mintrl_consistency,
)
from app.lineage.spine import LABEL_PROOF_BACKED, PROOF_BACKED
from app.run_verdict import _cold_start_evidence


# 种漂移 MinTRL：min_trl 放大 1.5× → 代回 PSR 的 z 偏 → M1 交叉校验必破。
def _drifted_mintrl(returns, sr_benchmark=0.0, confidence=0.95):
    m = minimum_track_record_length(returns, sr_benchmark, confidence)
    if m.status != "ok":
        return m
    return MinTRLResult(m.min_trl * 1.5, math.ceil(m.min_trl * 1.5), m.status,
                        m.n_observed, m.confidence, m.sr_benchmark, m.sr_per_period)


# 种漂移 PSR：整体 +0.1 偏移 → 与 DSR 不再相等 → M4 互校验必破。
def _drifted_psr(returns, sr_benchmark=0.0):
    return min(1.0, probabilistic_sharpe_ratio(returns, sr_benchmark) + 0.1)


def _ok_returns():
    return list(np.linspace(0.0005, 0.0025, 250))


# ── MinTRL 绑定 ──────────────────────────────────────────────────────────────
def test_mintrl_artifact_proof_backed():
    assert MINTRL_ARTIFACT.proof_status == PROOF_BACKED
    assert MINTRL_ARTIFACT.statement and MINTRL_ARTIFACT.derivation


def test_mintrl_properties_pass_on_real_impl():
    assert mintrl_consistency_check().result == "pass"


def test_mintrl_full_green_promotes():
    d = verify_mintrl_consistency(pinned_code_hash=MINTRL_PINNED_FINGERPRINT)
    assert d.promotable is True, d.verdict_text
    assert d.granted_label == LABEL_PROOF_BACKED


def test_mintrl_drift_caught_by_cross_check():
    cc = mintrl_consistency_check(mintrl_impl=_drifted_mintrl)
    assert cc.result == "fail"  # M1 交叉校验恒等式破
    assert "实现偏离定义" in cc.failure_reason


def test_psr_drift_caught_by_cross_check():
    cc = mintrl_consistency_check(psr_impl=_drifted_psr)
    assert cc.result == "fail"  # M4 PSR-DSR 互校验破


def test_mintrl_drift_rejected_by_gate():
    d = verify_mintrl_consistency(mintrl_impl=_drifted_mintrl, pinned_code_hash=MINTRL_PINNED_FINGERPRINT)
    assert d.promotable is False


def test_mintrl_pinned_fingerprint_matches_source():
    assert MINTRL_PINNED_FINGERPRINT == mintrl_code_fingerprint(), (
        "dsr.py PSR/MinTRL 链已改 → 重核交叉校验 + 更新 MINTRL_PINNED_FINGERPRINT"
    )


def test_mintrl_staleness_reachable_with_stale_pin():
    d = verify_mintrl_consistency(pinned_code_hash="stale0mintrl0000")
    assert d.promotable is False
    assert any("fresh" in v and "未刷新" in v for v in d.violations)


# ── 生产 wire：run verdict cold_start fail-soft ──────────────────────────────
def test_cold_start_carries_spine_consistency():
    run_verdict._mintrl_spine_status.cache_clear()
    ev = _cold_start_evidence(_ok_returns())
    assert "spine_consistency" in ev
    assert ev["spine_consistency"]["mintrl"]["promotable"] is True
    assert ev["dsr_applicable"] is True  # 一致时正常（status ok）


def test_cold_start_fail_soft_on_mintrl_drift(monkeypatch):
    monkeypatch.setattr(
        run_verdict, "_mintrl_spine_status",
        lambda: {"promotable": False, "granted_label": "challenged", "violations": ["M1 交叉校验破"]},
    )
    ev = _cold_start_evidence(_ok_returns())
    assert ev["dsr_applicable"] is False  # 守门估计器漂移 → 不谈 DSR
    assert ev["spine_consistency"]["mintrl"]["promotable"] is False
    assert "数学一致性失败" in ev["note"]


# ── codex P2-1 修：正信号被误判成 never_significant 也必抓（不再静默跳过 M1）─────
def _never_sig_mintrl(returns, sr_benchmark=0.0, confidence=0.95):
    m = minimum_track_record_length(returns, sr_benchmark, confidence)
    return MinTRLResult(float("inf"), float("inf"), "never_significant",
                        m.n_observed, confidence, sr_benchmark, m.sr_per_period)


def test_mintrl_misclassify_positive_as_never_sig_caught():
    cc = mintrl_consistency_check(mintrl_impl=_never_sig_mintrl)
    assert cc.result == "fail"  # 正信号 fixture status≠ok → status_ok 性质破（不再蒙混）
    assert "M1status_ok" in cc.failure_reason


# ── codex P2-2 修：fail-soft note 不含 R7 禁词（守门移到最后）────────────────────
def test_cold_start_fail_soft_note_has_no_banned_words(monkeypatch):
    from app.run_verdict import _BANNED_VERDICT_WORDS

    monkeypatch.setattr(
        run_verdict, "_mintrl_spine_status",
        lambda: {"promotable": False, "granted_label": "challenged", "violations": ["x"]},
    )
    ev = _cold_start_evidence(_ok_returns())
    for w in _BANNED_VERDICT_WORDS:
        assert w not in ev["note"], f"cold_start fail-soft note 含 R7 禁词 {w!r}：{ev['note']}"
