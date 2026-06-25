"""R23 conformal 校准区间接进 model_eval（价值闭环：conformal→模型台）对抗测试。

门必抓：
- **留出覆盖率 ≈ 1−α**（多种子均值；split-conformal 在真留出集上达标，命门）。
- abstain（非回归/无 OOS/calib 不足）→ 绝不返假区间（不假绿灯）。band 随 α 单调（小 α 更宽）。
- sentinel：刻意太窄的带在留出集上欠覆盖（证覆盖率是真判别器）。
- training_job_eval additive 含 conformal_interval，且不破 charts/metrics。JSON-safe。
"""

from __future__ import annotations

import json
import math

import numpy as np

from app.eval.model_eval import conformal_prediction_band


def _reg(n: int, sigma: float = 1.0, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    yt = rng.standard_normal(n) * 5.0
    yp = yt + rng.standard_normal(n) * sigma          # 残差 ~ N(0,σ)
    return {"spec": {"task": "regression"}, "oos_predictions": {"y_true": yt.tolist(), "y_pred": yp.tolist()}}


def test_holdout_coverage_consistent_with_conformal_level():
    """**命门（评审纠偏·不假绿灯）**：留出覆盖率 MC 均值与 split-conformal **总体**水平 k/(m+1) 一致（容 MC 噪声）。

    诚实口径：conformal 保证的是**总体**覆盖 k/(m+1)≥1−α（k=⌈(m+1)(1−α)⌉ 的 +1 校正），单 job/有限 seed 的
    **经验**均值是带噪估计、可略低于 1−α——故断言「均值≈k/(m+1) 容几个 MC 标准误」，**绝不**称「经验均值≥1−α=达标」
    （那是把 sub-nominal 估计渲染成达标=假绿灯）。同时核 k/(m+1)≥1−α（总体保证真成立）。
    """
    m = 400 // 2                                   # calib 大小（_reg n=400 → 前半 200）
    for alpha in (0.1, 0.05):
        k = math.ceil((m + 1) * (1 - alpha))
        level = k / (m + 1)                         # split-conformal 总体覆盖
        assert level >= 1 - alpha - 1e-12           # +1 校正 ⇒ 总体保证 ≥1−α（真成立）
        covs = [r["empirical_coverage"] for s in range(80)
                if (r := conformal_prediction_band(_reg(400, seed=s), alpha=alpha)) and not r["abstained"]]
        mean = float(np.mean(covs))
        se = (level * (1 - level) / m) ** 0.5 / (len(covs) ** 0.5)   # 均值的 MC 标准误
        assert len(covs) > 60 and abs(mean - level) <= 5 * se + 0.005, \
            f"α={alpha} 经验覆盖均值 {mean:.4f} 偏离总体水平 {level:.4f} 超 MC 容差（疑实现漂）"


def test_coverage_is_genuine_holdout_not_circular_sentinel():
    """**门有牙（评审/mutation 纠偏·核心命门）**：覆盖率必须是**真留出**、非循环自证 calib。

    种坏：calib 残差 σ=1、test 残差 σ=3（不同分布）→ 按 calib 校准的带在更宽的 test 上**严重欠覆盖**（实测≈0.3-0.5）。
    若实现把覆盖算在 calib 上（循环自证 bug，如 `np.mean(|calib|<=q)`）→ 恒≈1−α≈0.9、此断言立崩。故能抓循环自证。
    """
    rng = np.random.default_rng(0)
    n = 400
    mid = n // 2
    yt = rng.standard_normal(n) * 5.0
    resid = np.concatenate([rng.standard_normal(mid) * 1.0, rng.standard_normal(n - mid) * 3.0])  # calib σ1 / test σ3
    r = conformal_prediction_band(
        {"spec": {"task": "regression"}, "oos_predictions": {"y_true": yt.tolist(), "y_pred": (yt - resid).tolist()}},
        alpha=0.1,
    )
    assert not r["abstained"]
    assert r["empirical_coverage"] < 0.7, \
        f"分布漂移下真留出覆盖应显著欠（<0.7），得 {r['empirical_coverage']}——疑覆盖算在 calib 上（循环自证）"


def test_too_narrow_band_undercovers_sentinel():
    """Sentinel（门有牙）：把带人为减半 → 留出覆盖率显著 < 目标（证 empirical_coverage 是真判别器）。"""
    under = []
    for s in range(60):
        r = conformal_prediction_band(_reg(400, seed=s), alpha=0.1)
        if r and not r["abstained"]:
            # 用半带重算留出覆盖（模拟"带算窄了"的坏实现）
            res = np.asarray(_reg(400, seed=s)["oos_predictions"]["y_true"]) - \
                  np.asarray(_reg(400, seed=s)["oos_predictions"]["y_pred"])
            test = res[len(res) // 2:]
            under.append(float(np.mean(np.abs(test) <= r["band_half_width"] * 0.5)))
    assert np.mean(under) < 0.9 - 0.05, f"半带竟仍达标 {np.mean(under):.3f}？覆盖率判别力失效"


def test_too_narrow_band_undercovers_sentinel():
    """Sentinel（门有牙）：把带人为减半 → 留出覆盖率显著 < 目标（证 empirical_coverage 是真判别器）。"""
    under = []
    for s in range(60):
        r = conformal_prediction_band(_reg(400, seed=s), alpha=0.1)
        if r and not r["abstained"]:
            # 用半带重算留出覆盖（模拟"带算窄了"的坏实现）
            res = np.asarray(_reg(400, seed=s)["oos_predictions"]["y_true"]) - \
                  np.asarray(_reg(400, seed=s)["oos_predictions"]["y_pred"])
            test = res[len(res) // 2:]
            under.append(float(np.mean(np.abs(test) <= r["band_half_width"] * 0.5)))
    assert np.mean(under) < 0.9 - 0.05, f"半带竟仍达标 {np.mean(under):.3f}？覆盖率判别力失效"


def test_band_widens_as_alpha_shrinks():
    base = conformal_prediction_band(_reg(600, seed=1), alpha=0.2)["band_half_width"]
    tight = conformal_prediction_band(_reg(600, seed=1), alpha=0.05)["band_half_width"]
    assert tight > base                                # 更高置信(小 α) → 更宽带


def test_abstain_small_calib():
    """calib 不足（n=12→calib=6<⌈1/0.1⌉−1=9）→ abstained，band/coverage 为 None（不假绿灯）。"""
    r = conformal_prediction_band(_reg(12), alpha=0.1)
    assert r["abstained"] is True and r["band_half_width"] is None and r["empirical_coverage"] is None
    assert "证据不足" in r["note"]


def test_only_regression_other_tasks_none():
    """白名单（codex P2）：仅 task=='regression' 出区间；classification/**lambdarank(排序)**/未知任务→None。

    种坏：把回归 OOS 贴 lambdarank 任务标签——绝不对排序 job 发残差校准区间（假信号）。
    """
    reg_oos = _reg(400, seed=0)["oos_predictions"]
    assert conformal_prediction_band({"spec": {"task": "classification"}, "oos_predictions": reg_oos}) is None
    assert conformal_prediction_band({"spec": {"task": "lambdarank"}, "oos_predictions": reg_oos}) is None
    assert conformal_prediction_band({"spec": {"task": "ranking"}, "oos_predictions": reg_oos}) is None
    assert conformal_prediction_band({"oos_predictions": reg_oos}) is None              # 未知/缺 task
    # 适用面：显式 regression 才出区间
    assert conformal_prediction_band({"spec": {"task": "regression"}, "oos_predictions": reg_oos}) is not None


def test_not_applicable_missing_oos_and_mismatch():
    assert conformal_prediction_band({"spec": {"task": "regression"}}) is None          # 无 OOS
    assert conformal_prediction_band({"spec": {"task": "regression"},
                                      "oos_predictions": {"y_true": [1.0], "y_pred": [1.0, 2.0]}}) is None  # 长度不一致


def test_conformal_band_json_safe():
    for r in (conformal_prediction_band(_reg(400, seed=0)), conformal_prediction_band(_reg(12))):
        json.dumps(r)                                  # abstain(None 字段) 与正常都 JSON-safe


def test_training_job_eval_includes_conformal_interval(tmp_path, monkeypatch):
    """集成：training_job_eval additive 含 conformal_interval，且 charts/metrics 不破。"""
    from app import main
    from types import SimpleNamespace

    art = tmp_path / "art"
    art.mkdir()
    result = {**_reg(400, seed=0), "feature_importance": {"f1": 0.5}}
    (art / "result.json").write_text(json.dumps(result), encoding="utf-8")
    job = SimpleNamespace(status="succeeded", model="ridge", family="linear",
                          artifact_dir=str(art), metrics={})
    monkeypatch.setattr(main.TRAINING_SERVICE, "get_job", lambda jid: job)
    out = main.training_job_eval("j1")
    assert "conformal_interval" in out and out["conformal_interval"]["abstained"] is False
    assert out["conformal_interval"]["empirical_coverage"] is not None
    assert "charts" in out and "metrics" in out        # additive 不破原字段
    json.dumps(out)


def test_training_job_eval_passes_cpcv_distribution(tmp_path, monkeypatch):
    """集成（R4 闭环）：training_job_eval 透传 result.json 的 cpcv_distribution；无则 None（不假绿灯：未算≠已算）。"""
    from app import main
    from types import SimpleNamespace

    # result 含 cpcv_distribution → 透传
    art = tmp_path / "art"
    art.mkdir()
    cpcv = {"status": "ok", "metric": "r2", "baseline": 0.0, "n_paths": 5, "q05": 0.4}
    (art / "result.json").write_text(json.dumps({**_reg(400, seed=0), "cpcv_distribution": cpcv}), encoding="utf-8")
    job = SimpleNamespace(status="succeeded", model="ridge", family="linear", artifact_dir=str(art), metrics={})
    monkeypatch.setattr(main.TRAINING_SERVICE, "get_job", lambda jid: job)
    out = main.training_job_eval("j1")
    assert out["cpcv_distribution"] == cpcv

    # result 无 cpcv_distribution（默认关）→ None（不编造）
    art2 = tmp_path / "art2"
    art2.mkdir()
    (art2 / "result.json").write_text(json.dumps(_reg(400, seed=0)), encoding="utf-8")
    job2 = SimpleNamespace(status="succeeded", model="ridge", family="linear", artifact_dir=str(art2), metrics={})
    monkeypatch.setattr(main.TRAINING_SERVICE, "get_job", lambda jid: job2)
    assert main.training_job_eval("j2")["cpcv_distribution"] is None
