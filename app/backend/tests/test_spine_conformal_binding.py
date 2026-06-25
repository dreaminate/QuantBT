"""Mathematical Spine · Conformal 预测区间经脊柱绑定的【对抗式】测试（覆盖定理·接 model_eval band）。

split conformal 有可机器证伪的覆盖定理 P(Y∈C)≥1−α。漂移（区间过窄/错分位）→ MC 留出覆盖掉
1−α 下 → 脊柱 property 一致性 fail → `conformal_prediction_band` fail-soft 标 abstained（坏 conformal
不给假覆盖的 band）。finding 04。
"""

from __future__ import annotations

import numpy as np
import pytest

import app.eval.model_eval as model_eval
from app.eval.conformal import ConformalInterval, split_conformal_interval
from app.eval.model_eval import conformal_prediction_band
from app.eval.spine_bindings import (
    CONFORMAL_ARTIFACT,
    CONFORMAL_PINNED_FINGERPRINT,
    conformal_code_fingerprint,
    conformal_consistency_check,
    verify_conformal_consistency,
)
from app.lineage.spine import LABEL_PROOF_BACKED, PROOF_BACKED


# 种漂移 conformal：区间砍半（q→0.5q）→ 欠覆盖 → C1 覆盖定理 property 必破。
def _drifted_conformal(calib, prediction, alpha, *, max_width=None):
    iv = split_conformal_interval(calib, prediction, alpha, max_width=max_width)
    if iv.abstained:
        return iv
    q = (iv.upper - iv.lower) / 2.0
    return ConformalInterval(lower=prediction - q * 0.5, upper=prediction + q * 0.5,
                             alpha=alpha, method="split", n_cal=iv.n_cal, abstained=False)


def _regression_result(n=200, seed=7):
    rng = np.random.default_rng(seed)
    y_true = rng.normal(0.0, 1.0, n)
    y_pred = y_true + rng.normal(0.0, 0.3, n)  # 残差 ~ N(0,0.3)
    return {"spec": {"task": "regression"},
            "oos_predictions": {"y_true": y_true.tolist(), "y_pred": y_pred.tolist()}}


# ── Conformal 绑定 ───────────────────────────────────────────────────────────
def test_conformal_artifact_proof_backed():
    assert CONFORMAL_ARTIFACT.proof_status == PROOF_BACKED
    assert CONFORMAL_ARTIFACT.statement and CONFORMAL_ARTIFACT.derivation


def test_conformal_properties_pass_on_real_impl():
    assert conformal_consistency_check().result == "pass"


def test_conformal_full_green_promotes():
    d = verify_conformal_consistency(pinned_code_hash=CONFORMAL_PINNED_FINGERPRINT)
    assert d.promotable is True, d.verdict_text
    assert d.granted_label == LABEL_PROOF_BACKED


def test_conformal_drift_caught_by_coverage_property():
    cc = conformal_consistency_check(impl=_drifted_conformal)
    assert cc.result == "fail"  # 区间砍半 → 覆盖掉 1−α 下 → C1 破
    assert "实现偏离定义" in cc.failure_reason


def test_conformal_drift_rejected_by_gate():
    d = verify_conformal_consistency(impl=_drifted_conformal, pinned_code_hash=CONFORMAL_PINNED_FINGERPRINT)
    assert d.promotable is False


# codex P2 修：split 漂移成 [finite, +inf] 也必抓（C3 查双端点有限，封死 C1 蒙混 100% 覆盖 + inf 半宽）。
def _inf_upper_conformal(calib, prediction, alpha, *, max_width=None):
    iv = split_conformal_interval(calib, prediction, alpha, max_width=max_width)
    if iv.abstained:
        return iv
    return ConformalInterval(lower=iv.lower, upper=float("inf"), alpha=alpha,
                             method="split", n_cal=iv.n_cal, abstained=False)


def test_conformal_inf_upper_drift_caught():
    cc = conformal_consistency_check(impl=_inf_upper_conformal)
    assert cc.result == "fail"  # C3 双端点有限 → inf upper 被抓（不再蒙混过 C1/C2）
    assert "C3" in cc.failure_reason


def test_conformal_pinned_fingerprint_matches_source():
    assert CONFORMAL_PINNED_FINGERPRINT == conformal_code_fingerprint(), (
        "conformal.py 实现链已改 → 重核覆盖 + 更新 CONFORMAL_PINNED_FINGERPRINT"
    )


def test_conformal_staleness_reachable_with_stale_pin():
    d = verify_conformal_consistency(pinned_code_hash="stale0conformal0")
    assert d.promotable is False
    assert any("fresh" in v and "未刷新" in v for v in d.violations)


# ── 生产 wire：model_eval conformal_prediction_band fail-soft ────────────────
def test_band_carries_spine_consistency():
    model_eval._conformal_spine_status.cache_clear()
    band = conformal_prediction_band(_regression_result(), alpha=0.1)
    assert band is not None
    assert band["spine_consistency"]["conformal"]["promotable"] is True
    assert band["abstained"] is False  # 一致 → 正常出 band


def test_band_fail_soft_on_conformal_drift(monkeypatch):
    monkeypatch.setattr(
        model_eval, "_conformal_spine_status",
        lambda: {"promotable": False, "granted_label": "challenged", "violations": ["覆盖掉 1−α 下"]},
    )
    band = conformal_prediction_band(_regression_result(), alpha=0.1)
    assert band["abstained"] is True  # 守门估计器漂移 → 不给假覆盖的 band
    assert band["spine_consistency"]["conformal"]["promotable"] is False
    assert "数学一致性失败" in band["note"]
    assert "可信" not in band["note"]  # R7 禁词不泄露（codex P2 教训）
